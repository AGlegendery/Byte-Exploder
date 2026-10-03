# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
exploder_core.py
----------------
Core engine for Byte Exploder: turn any file (or folder, or text) into a PNG
image by writing its bytes into pixels, then scramble those pixels with a
key-derived, block-chained XOR so the result is unreadable without the
matching key.

Pipeline
    file/folder/text --> raw bytes --> square RGB array --> block split
                     --> per-pixel XOR + block-chain XOR --> PNG

Scrambling, for the block at (y, x) in raster order (byte i of the block in
row-major order, both patterns repeat every 32 bytes):
    enc[i] = plain[i] ^ master_key[(i + x + y) % 32] ^ chain[i % 32]
    chain  = sha256(chain + enc_block)          (starts at sha256(master_key))

The image is processed one horizontal band of `block_size` rows at a time, so
no stage keeps more than one full copy of the image in RAM.

The key material needed to reverse the process is returned as a dict
(`key_info`). It can be stored next to the image as a .key JSON file, or hidden
inside the image's pixels via `key_embed` (see `embed_key` below).

This is a hobby/utility obfuscation tool, not a vetted cryptographic product.
"""

from __future__ import annotations

import base64
import hashlib
import io
import json
import math
import os
import struct
import tempfile
import zipfile
import zlib
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from typing import Any, BinaryIO, Callable, Dict, Optional, Tuple

import numpy as np
from PIL import Image

from key_embed import (
    build_carrier,
    carrier_cells_needed,
    footer_rows,
    read_footer,
    read_key_from_carrier,
)

# Optional: better RAM detection on Windows/Linux.
try:
    import psutil  # type: ignore
except Exception:  # pragma: no cover
    psutil = None


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_BLOCK = 16
APP_SECRET = b"AG_APP_SALT_X9"   # static salt mixed into the KDF
VERSION = "EXPLD8.2.3"
MIN_BLOCK_SIZE = 8
MAX_BLOCK_SIZE = 64

TEXT_FILE_NAME = "text.txt"      # file name recorded for text input
_KEY_LEN = 32                    # SHA-256 digest size; XOR patterns repeat every 32 bytes
_IO_CHUNK = 4 * 1024 * 1024      # target size of one file read / one PNG deflate job

# Disable PIL's decompression-bomb guard (our images can be large by design).
Image.MAX_IMAGE_PIXELS = None


# --------------------------------------------------------------------------- #
# Block sizing
# --------------------------------------------------------------------------- #
def calculate_dynamic_block_size(file_size_bytes: int) -> int:
    mb = file_size_bytes / (1024 * 1024)
    if mb < 1:
        return 8
    elif mb < 10:
        return 12
    elif mb < 50:
        return 16
    elif mb < 200:
        return 24
    elif mb < 500:
        return 32
    elif mb < 1024:
        return 48
    return 64


# --------------------------------------------------------------------------- #
# Key derivation + scrambling
# --------------------------------------------------------------------------- #
def kdf(shape, salt: bytes) -> bytes:
    h = hashlib.sha256()
    h.update(APP_SECRET)
    h.update(str(shape).encode())
    h.update(salt)
    return h.digest()


def _key_patterns(master_key: bytes, n: int) -> np.ndarray:
    """(32, n) table: row s is the pixel-XOR pattern of every block whose
    (x + y) % 32 == s."""
    k = np.frombuffer(master_key, np.uint8)
    idx = (np.arange(n)[None, :] + np.arange(_KEY_LEN)[:, None]) % _KEY_LEN
    return k[idx]


def _band_to_blocks(band: np.ndarray, bs: int) -> np.ndarray:
    """(bs, W, 3) band -> new (W // bs, bs*bs*3) array, one flattened block per
    row, left to right."""
    nbx = band.shape[1] // bs
    return band.reshape(bs, nbx, bs * 3).transpose(1, 0, 2).reshape(nbx, -1)


def _blocks_to_band(blocks: np.ndarray, bs: int) -> np.ndarray:
    """Inverse of _band_to_blocks."""
    nbx = blocks.shape[0]
    return blocks.reshape(nbx, bs, bs * 3).transpose(1, 0, 2).reshape(bs, nbx * bs, 3)


# --------------------------------------------------------------------------- #
# RAM guard
# --------------------------------------------------------------------------- #
def _available_ram_bytes() -> int:
    if psutil is not None:
        try:
            return int(psutil.virtual_memory().available)
        except Exception:
            pass
    try:
        if hasattr(os, "sysconf"):
            pages = os.sysconf("SC_AVPHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            return int(pages) * int(page_size)
    except Exception:
        pass
    return 0


def _ensure_safe_ram(estimated_bytes: int, fraction: float, on_log: Optional[Callable[[str], None]] = None):
    avail = _available_ram_bytes()
    if avail <= 0:
        if on_log:
            on_log("[i] Safe mode: RAM availability could not be detected; proceeding best-effort.")
        return

    limit = int(avail * float(fraction))
    if estimated_bytes > limit:
        raise MemoryError(
            "Safe Encode/Decoding is enabled, but the estimated memory needed for this single output image "
            f"is too high (need ~{estimated_bytes / 1024 / 1024:.1f} MB, limit ~{limit / 1024 / 1024:.1f} MB).\n"
            "Tip: use a smaller input file, increase block size, or disable Safe mode if you have enough RAM."
        )


# --------------------------------------------------------------------------- #
# PNG writer
# --------------------------------------------------------------------------- #
def _png_chunk(f: BinaryIO, tag: bytes, data: bytes) -> None:
    f.write(struct.pack(">I", len(data)))
    f.write(tag)
    f.write(data)
    f.write(struct.pack(">I", zlib.crc32(data, zlib.crc32(tag)) & 0xFFFFFFFF))


def _deflate_job(raw: np.ndarray, last: bool) -> bytes:
    c = zlib.compressobj(1, zlib.DEFLATED, -15)
    return c.compress(raw) + c.flush(zlib.Z_FINISH if last else zlib.Z_SYNC_FLUSH)


class _SideBySide:
    """Rows of `left` followed by the same rows of `right`, built only when a
    slice is requested (so the full-width image is never materialized)."""

    def __init__(self, left: np.ndarray, right: np.ndarray):
        self.left, self.right = left, right
        self.shape = (left.shape[0], left.shape[1] + right.shape[1], 3)

    def __getitem__(self, idx):
        return np.concatenate((self.left[idx], self.right[idx]), axis=-2)


def _square_side(padded: int, key_info: Dict[str, Any]) -> int:
    """Smallest square side N > padded whose bottom N - padded rows (N wide)
    can carry the embedded key."""
    need = carrier_cells_needed(key_info)
    n = padded + 1
    while (n - padded) * n * 3 < need:
        n += 1
    return n


def _write_png(f: BinaryIO, parts, on_progress=None) -> None:
    """Write RGB uint8 arrays of equal width, stacked top to bottom, as a PNG.

    Every row uses PNG filter "Up" (difference to the row above: it is what
    keeps repetitive inputs compressible after scrambling) and the rows are
    deflated at level 1 in independent jobs on a thread pool (pigz-style
    raw-deflate segments joined by sync flushes). That is many times faster
    than PIL's encoder and never copies the whole image.
    """
    width = parts[0].shape[1]
    height = sum(p.shape[0] for p in parts)
    row_bytes = width * 3 + 1
    step = max(1, _IO_CHUNK // row_bytes)
    # (rows, row above them) per job; the row above the image is all zeros.
    jobs = []
    above = np.zeros((width, 3), np.uint8)
    for p in parts:
        for y in range(0, p.shape[0], step):
            jobs.append((p[y:y + step], above))
            above = p[min(y + step, p.shape[0]) - 1]
    workers = min(8, os.cpu_count() or 1)

    f.write(b"\x89PNG\r\n\x1a\n")
    _png_chunk(f, b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    _png_chunk(f, b"IDAT", b"\x78\x01")  # zlib header: deflate, 32K window

    adler = 1
    pending: deque = deque()
    with ThreadPoolExecutor(max_workers=workers) as pool:
        try:
            for i, (rows, above) in enumerate(jobs):
                flat = rows.reshape(rows.shape[0], -1)
                raw = np.empty((rows.shape[0], row_bytes), np.uint8)
                raw[:, 0] = 2  # filter type "Up"
                raw[0, 1:] = flat[0] - above.reshape(-1)
                raw[1:, 1:] = flat[1:] - flat[:-1]  # uint8 wraps mod 256, as PNG wants
                adler = zlib.adler32(raw, adler)
                pending.append(pool.submit(_deflate_job, raw, i == len(jobs) - 1))
                while len(pending) > workers:
                    _png_chunk(f, b"IDAT", pending.popleft().result())
                if on_progress:
                    on_progress(i / len(jobs))
            while pending:
                _png_chunk(f, b"IDAT", pending.popleft().result())
        finally:
            for fut in pending:
                fut.cancel()

    _png_chunk(f, b"IDAT", struct.pack(">I", adler & 0xFFFFFFFF))
    _png_chunk(f, b"IEND", b"")


def _replace_atomically(path: str, write: Callable[[BinaryIO], Any]) -> Any:
    """Run write(f) on `path + ".part"` and move it into place only on success,
    so a failed or cancelled run never leaves a half-written file behind."""
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            result = write(f)
        os.replace(part, path)
        return result
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


# --------------------------------------------------------------------------- #
# Key info (JSON) serialization
# --------------------------------------------------------------------------- #
def _to_jsonable(obj: Any) -> Any:
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, bytes):
        return {"__bytes__": base64.b64encode(obj).decode("ascii")}
    if isinstance(obj, (tuple, list)):
        return [_to_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): _to_jsonable(v) for k, v in obj.items()}
    return str(obj)


def _from_jsonable(obj: Any) -> Any:
    if isinstance(obj, list):
        return [_from_jsonable(x) for x in obj]
    if isinstance(obj, dict):
        if "__bytes__" in obj and isinstance(obj["__bytes__"], str):
            return base64.b64decode(obj["__bytes__"].encode("ascii"))
        return {k: _from_jsonable(v) for k, v in obj.items()}
    return obj


def save_key_info(key_info: Dict[str, Any], path: str) -> None:
    data = _to_jsonable(key_info)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_key_info(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    data = _from_jsonable(data)
    if not isinstance(data, dict):
        raise ValueError("Invalid key format")
    return data


# --------------------------------------------------------------------------- #
# Folder <-> ZIP
# --------------------------------------------------------------------------- #
def _zip_folder_to_temp(folder_path: str, on_log=None) -> str:
    def log(m: str):
        if on_log:
            on_log(m)

    folder_path = os.path.abspath(folder_path)
    if not os.path.isdir(folder_path):
        raise NotADirectoryError(folder_path)

    fd, tmp_zip = tempfile.mkstemp(suffix=".zip", prefix="expld_folder_")
    os.close(fd)

    log(f"[i] Zipping folder -> {tmp_zip}")
    log("[i] ZIP mode: STORE (no compression), Zip64 enabled")

    try:
        with zipfile.ZipFile(tmp_zip, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zf:
            for root, _, files in os.walk(folder_path):
                for name in files:
                    full = os.path.join(root, name)
                    rel = os.path.relpath(full, folder_path).replace("\\", "/")
                    zf.write(full, arcname=rel)

        if os.path.getsize(tmp_zip) == 0:
            raise RuntimeError("ZIP creation failed (empty archive).")

        log(f"[OK] Folder zipped. Size: {os.path.getsize(tmp_zip):,} bytes")
        return tmp_zip
    except Exception:
        try:
            if os.path.exists(tmp_zip):
                os.remove(tmp_zip)
        except Exception:
            pass
        raise


def _extract_zip_to_folder(zip_path: str, out_folder: str, on_log=None) -> None:
    def log(m: str):
        if on_log:
            on_log(m)

    zip_path = os.path.abspath(zip_path)
    out_folder = os.path.abspath(out_folder)

    if not os.path.exists(zip_path):
        raise FileNotFoundError(zip_path)

    os.makedirs(out_folder, exist_ok=True)
    log(f"[i] Extracting ZIP -> {out_folder}")

    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_folder)

    log("[OK] ZIP extracted.")


# --------------------------------------------------------------------------- #
# Encoder
# --------------------------------------------------------------------------- #
def _read_into_image(src: BinaryIO, data_size: int, arr: np.ndarray, size: int, progress) -> None:
    """Stream [8-byte length header + data] row-major into arr[:size, :size]."""
    row_bytes = size * 3
    rows_per_read = max(1, _IO_CHUNK // row_bytes)
    buf = np.empty(rows_per_read * row_bytes, np.uint8)
    mv = memoryview(buf)
    remaining = data_size

    for r0 in range(0, size, rows_per_read):
        rows = min(rows_per_read, size - r0)
        end = rows * row_bytes
        pos = 0
        if r0 == 0:
            buf[:8] = np.frombuffer(struct.pack(">Q", data_size), np.uint8)
            pos = 8
        while pos < end and remaining > 0:
            n = src.readinto(mv[pos:pos + min(end - pos, remaining)])
            if not n:
                raise IOError("Input ended before the expected size (was it modified while encoding?).")
            pos += n
            remaining -= n
        buf[pos:end] = 0
        arr[r0:r0 + rows, :size] = buf[:end].reshape(rows, size, 3)
        progress(10 * (r0 + rows) / size)
        if remaining == 0:
            break  # the rest of arr is already zero


def _encode_stream(
    src: BinaryIO,
    data_size: int,
    output_image_path: str,
    meta: Dict[str, Any],
    block_size: Optional[int],
    safe_mode: bool,
    safe_ram_fraction: float,
    embed_key: bool,
    log,
    progress,
) -> Dict[str, Any]:
    log(f"[+] File size: {data_size} bytes")

    if block_size is None:
        block_size = calculate_dynamic_block_size(data_size)
        log(f"[+] Dynamic block size: {block_size}")
    else:
        log(f"[+] Custom block size: {block_size}")
    bs = int(block_size)

    size = math.ceil(math.sqrt(math.ceil((8 + data_size) / 3)))
    padded = -(-size // bs) * bs
    padded_shape = (padded, padded, 3)
    log(f"[+] Image padded to {padded_shape}")

    if safe_mode:
        log("[i] Safe Encode enabled (RAM check)")
        _ensure_safe_ram(padded * padded * 3, safe_ram_fraction, on_log=log)

    salt = hashlib.sha256(src.read(64)).digest()
    src.seek(0)

    arr = np.zeros(padded_shape, np.uint8)
    _read_into_image(src, data_size, arr, size, progress)

    nbx = padded // bs
    log(f"[+] Total blocks: {nbx * nbx}")
    progress(10)

    master_key = kdf(padded_shape, salt)
    chain = hashlib.sha256(master_key).digest()
    log("[+] Key material generated")

    # --- scramble, one band of block rows at a time ---
    n = bs * bs * 3
    reps = -(-n // _KEY_LEN)
    kp = _key_patterns(master_key, n)
    xs = np.arange(nbx) * bs
    for y in range(0, padded, bs):
        band = arr[y:y + bs]
        blocks = _band_to_blocks(band, bs)
        blocks ^= kp[(xs + y) % _KEY_LEN]
        # The chain depends on each encrypted block, so this part is sequential.
        for blk in blocks:
            blk ^= np.frombuffer(chain * reps, np.uint8, n)
            h = hashlib.sha256(chain)
            h.update(blk)
            chain = h.digest()
        band[...] = _blocks_to_band(blocks, bs)
        progress(10 + 70 * (y + bs) / padded)
    log("[+] Blocks encrypted")

    key_info = {
        "version": VERSION,
        "orig_shape": (size, size),
        "padded_shape": padded_shape,
        "block_size": bs,
        "salt": salt.hex(),
        **meta,
        "file_size": int(data_size),
    }

    parts = [arr]
    # --- optionally hide the key inside the pixels ---
    # The key goes into extra rows below the image; a matching strip of noise
    # on the right keeps the whole image square.
    if embed_key:
        log("[+] Embedding key into image (hidden carrier rows)")
        key_info["key_embedded"] = True
        side = _square_side(padded, key_info)
        strip = np.frombuffer(os.urandom(padded * (side - padded) * 3), np.uint8)
        parts = [
            _SideBySide(arr, strip.reshape(padded, side - padded, 3)),
            build_carrier(side, key_info, rows=side - padded),
        ]
        log(f"[+] Key embedded. The .key file is now optional. Image: {side} x {side}")

    _replace_atomically(
        output_image_path,
        lambda f: _write_png(f, parts, on_progress=lambda frac: progress(80 + 20 * frac)),
    )
    progress(100)
    log(f"[OK] Encrypted image saved: {output_image_path}")
    return key_info


def encode_file(
    input_path: str,
    output_image_path: str,
    block_size: int | None = None,
    safe_mode: bool = False,
    safe_ram_fraction: float = 0.25,
    embed_key: bool = False,
    on_progress=None,
    on_log=None,
):
    """Encode a file or folder into a scrambled PNG.

    If `embed_key` is True, the key material is hidden inside the image's pixels
    (see key_embed) and no separate .key file is strictly required to decode.
    The function still returns `key_info` so the caller may also save it.
    """
    def log(msg):
        if on_log:
            on_log(msg)

    def progress(val):
        if on_progress:
            on_progress(int(val))

    if not os.path.exists(input_path):
        raise FileNotFoundError(input_path)

    temp_zip_path: Optional[str] = None
    is_folder = os.path.isdir(input_path)
    folder_name: Optional[str] = None

    actual_input = input_path
    if is_folder:
        folder_name = os.path.basename(os.path.abspath(input_path))
        temp_zip_path = _zip_folder_to_temp(input_path, on_log=log)
        actual_input = temp_zip_path
        log(f"[+] Folder detected. Encoding as ZIP: {folder_name}")

    try:
        log(f"[+] Version: {VERSION}")
        log(f"[+] Input: {input_path}")
        meta = {
            "input_is_folder": bool(is_folder),
            "input_is_text": False,
            "folder_name": folder_name,
            "file_name": os.path.basename(actual_input),
            "file_ext": os.path.splitext(actual_input)[1],
        }
        with open(actual_input, "rb") as src:
            return _encode_stream(
                src, os.fstat(src.fileno()).st_size, output_image_path, meta,
                block_size, safe_mode, safe_ram_fraction, embed_key, log, progress,
            )
    finally:
        if temp_zip_path and os.path.exists(temp_zip_path):
            try:
                os.remove(temp_zip_path)
                log("[i] Temp ZIP removed.")
            except Exception:
                pass


def encode_text(
    text: str,
    output_image_path: str,
    block_size: int | None = None,
    embed_key: bool = False,
    on_progress=None,
    on_log=None,
):
    """Encode a text (stored as UTF-8) into a scrambled PNG. Returns key_info,
    which records `input_is_text` so the decoder can show it as text."""
    def log(msg):
        if on_log:
            on_log(msg)

    def progress(val):
        if on_progress:
            on_progress(int(val))

    data = text.encode("utf-8")
    log(f"[+] Version: {VERSION}")
    log(f"[+] Input: text ({len(text):,} characters)")
    meta = {
        "input_is_folder": False,
        "input_is_text": True,
        "folder_name": None,
        "file_name": TEXT_FILE_NAME,
        "file_ext": os.path.splitext(TEXT_FILE_NAME)[1],
    }
    return _encode_stream(
        io.BytesIO(data), len(data), output_image_path, meta,
        block_size, False, 0.25, embed_key, log, progress,
    )


# --------------------------------------------------------------------------- #
# Decoder
# --------------------------------------------------------------------------- #
class _PayloadSink:
    """Receives the decoded stream ([8-byte length header][payload][padding])
    and writes exactly the payload to `out`."""

    def __init__(self, out: BinaryIO, capacity: int, expected_size: Optional[int]):
        self.out = out
        self.capacity = capacity
        self.expected_size = expected_size
        self.header = b""
        self.remaining: Optional[int] = None

    def feed(self, data: bytes) -> bool:
        """Consume `data`; return True once the whole payload has been written."""
        mv = memoryview(data)
        if self.remaining is None:
            need = 8 - len(self.header)
            self.header += bytes(mv[:need])
            mv = mv[need:]
            if len(self.header) < 8:
                return False
            length = struct.unpack(">Q", self.header)[0]
            if length > self.capacity or (
                self.expected_size is not None and length != self.expected_size
            ):
                raise ValueError(
                    "Wrong key for this image (or the image is corrupted): "
                    "the decoded length header does not match."
                )
            self.remaining = length
        take = min(self.remaining, len(mv))
        if take:
            self.out.write(mv[:take])
            self.remaining -= take
        return self.remaining == 0


def _carrier_footer(img: Image.Image) -> Optional[Tuple[int, int]]:
    """(extra_rows, blob_len) if `img` ends with an embedded-key carrier."""
    w, h = img.size
    tail_rows = min(h, footer_rows(w))
    footer = read_footer(np.asarray(img.crop((0, h - tail_rows, w, h))))
    if footer is None or not 0 < footer[0] < h:
        return None
    return footer


def _read_embedded_key(img: Image.Image) -> Optional[Dict[str, Any]]:
    footer = _carrier_footer(img)
    if footer is None:
        return None
    extra_rows, blob_len = footer
    w, h = img.size
    return read_key_from_carrier(np.asarray(img.crop((0, h - extra_rows, w, h))), blob_len)


def _open_rgb(im: Image.Image) -> Image.Image:
    img = im if im.mode == "RGB" else im.convert("RGB")
    img.load()
    return img


def _decode_to(
    image_path: str,
    out: BinaryIO,
    key_info: Optional[dict],
    safe_mode: bool,
    safe_ram_fraction: float,
    log,
    progress,
) -> Dict[str, Any]:
    """Decode `image_path` and write the original bytes to `out`. Returns the
    key_info that was used (the embedded one if `key_info` was None)."""
    if not os.path.exists(image_path):
        raise FileNotFoundError(image_path)

    log(f"[+] Image: {image_path}")

    with Image.open(image_path) as im:
        if safe_mode:
            log("[i] Safe Decode enabled (RAM check)")
            # PIL holds the decoded image at 4 bytes per pixel.
            _ensure_safe_ram(im.size[0] * im.size[1] * 4, safe_ram_fraction, on_log=log)
        img = _open_rgb(im)
        progress(5)

        # --- resolve the key: embedded in pixels, or supplied externally ---
        if key_info is None:
            log("[i] No external key given; looking for an embedded key...")
            key_info = _read_embedded_key(img)
            if key_info is None:
                raise ValueError("No key supplied and no embedded key found in the image.")
            log("[OK] Embedded key extracted from image.")

        orig_h, orig_w = (int(v) for v in key_info["orig_shape"])
        padded_shape = tuple(int(v) for v in key_info["padded_shape"])
        bs = int(key_info["block_size"])
        salt = bytes.fromhex(key_info["salt"])
        expected_size = key_info.get("file_size")
        expected_size = int(expected_size) if expected_size is not None else None

        # When the key was embedded the image is bigger than the encrypted
        # area (top-left exp_w x exp_h): carrier rows below it and, in square
        # images, a noise strip on the right. Also when a backup .key is used.
        w, h = img.size
        exp_h, exp_w = padded_shape[0], padded_shape[1]
        if (w, h) != (exp_w, exp_h):
            footer = _carrier_footer(img) if w >= exp_w and h > exp_h else None
            if footer is None or h - footer[0] != exp_h:
                raise ValueError(
                    f"Image size mismatch. expected={(exp_w, exp_h)}, got={(w, h)}"
                )

        nbx = exp_w // bs
        log(f"[+] Total blocks: {nbx * (exp_h // bs)}")
        progress(10)

        master_key = kdf(padded_shape, salt)
        chain = hashlib.sha256(master_key).digest()

        n = bs * bs * 3
        kp = _key_patterns(master_key, n)
        chain_idx = np.arange(n) % _KEY_LEN
        xs = np.arange(nbx) * bs
        sink = _PayloadSink(out, orig_h * orig_w * 3 - 8, expected_size)

        for y in range(0, exp_h, bs):
            blocks = _band_to_blocks(np.asarray(img.crop((0, y, exp_w, y + bs))), bs)
            if not blocks.flags.writeable:  # one-block-wide image: still a view
                blocks = blocks.copy()
            # Chain values come from the encrypted blocks, so hash before XOR.
            links = []
            for blk in blocks:
                links.append(chain)
                h_ = hashlib.sha256(chain)
                h_.update(blk)
                chain = h_.digest()
            blocks ^= np.frombuffer(b"".join(links), np.uint8).reshape(nbx, _KEY_LEN)[:, chain_idx]
            blocks ^= kp[(xs + y) % _KEY_LEN]

            rows = min(bs, orig_h - y)
            band = _blocks_to_band(blocks, bs)
            if sink.feed(band[:rows, :orig_w].tobytes()):
                break
            progress(10 + 85 * (y + bs) / exp_h)
        else:
            raise ValueError("Image ended before the whole file was decoded.")

    progress(100)
    return key_info


def decode_image(
    image_path: str,
    output_file_path: str,
    key_info: Optional[dict] = None,
    safe_mode: bool = False,
    safe_ram_fraction: float = 0.25,
    on_progress=None,
    on_log=None,
):
    """Decode a scrambled PNG back into the original file/folder.

    If `key_info` is None, the key is read from inside the image (embedded
    mode). If the image has no embedded key and none is supplied, this raises.
    Returns the key_info that was used.
    """
    def log(msg):
        if on_log:
            on_log(msg)

    def progress(val):
        if on_progress:
            on_progress(int(val))

    key_info = _replace_atomically(
        output_file_path,
        lambda out: _decode_to(image_path, out, key_info, safe_mode, safe_ram_fraction, log, progress),
    )
    log(f"[OK] File restored: {output_file_path}")

    # ---------------- folder restore ----------------
    if bool(key_info.get("input_is_folder")):
        folder_name = key_info.get("folder_name") or "restored_folder"
        base = os.path.splitext(output_file_path)[0]
        out_folder = base + "_" + folder_name
        try:
            _extract_zip_to_folder(output_file_path, out_folder, on_log=log)
            log(f"[OK] Folder restored: {out_folder}")
        finally:
            try:
                os.remove(output_file_path)
                log("[i] Temporary restored ZIP removed.")
            except Exception:
                pass
    return key_info


def decode_to_bytes(
    image_path: str,
    key_info: Optional[dict] = None,
    on_progress=None,
    on_log=None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Decode an image in memory. Returns (data, key_info); for text input,
    `data.decode("utf-8")` is the original text."""
    def log(msg):
        if on_log:
            on_log(msg)

    def progress(val):
        if on_progress:
            on_progress(int(val))

    buf = io.BytesIO()
    key_info = _decode_to(image_path, buf, key_info, False, 0.25, log, progress)
    return buf.getvalue(), key_info


def read_embedded_key(image) -> Optional[Dict[str, Any]]:
    """Return the key_info hidden in the image, or None if it has none.
    `image` is a path or an already opened PIL image."""
    if isinstance(image, Image.Image):
        return _read_embedded_key(_open_rgb(image))
    with Image.open(image) as im:
        return _read_embedded_key(_open_rgb(im))
