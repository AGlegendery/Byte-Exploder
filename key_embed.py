# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
key_embed.py
------------
Embed and extract key material inside an image's pixel data instead of storing
it in PNG text/EXIF metadata.

Why not metadata?
  Metadata chunks (tEXt, EXIF, XMP, ...) are trivial to read with any tool
  (exiftool, PIL's Image.info, `strings`, ...). Storing the key there means it
  travels in plain sight. Here the key is hidden in the least-significant bits
  (LSBs) of pixels and XOR-masked with a keystream, so a casual inspection of
  the file's metadata reveals nothing.

How it stays robust:
  In this project the image *is* the encrypted file, so flipping LSBs inside
  the encrypted payload would corrupt the data. To avoid that, the key is NOT
  written into the encrypted pixels at all. Instead we append a few extra
  "carrier" rows below the encrypted image and hide the key in THEIR LSBs. The
  encrypted pixels stay untouched; on decode we read the key from the carrier
  rows, strip them off, and decrypt the original region exactly.

Carrier layout (all indices are rows of the final image):
    rows [0, H)                 -> the encrypted image, untouched
    rows [H, total - 1)         -> blob bits, row-major over LSBs of channels
    row  [total - 1]            -> footer: magic(4) + rows(4) + blob_len(4)

The blob is zlib-compressed, keystream-masked JSON of key_info, framed with a
magic marker. The mask is lightweight obfuscation, not a second cipher: the
real protection is the encryption the rest of the program performs.
"""

from __future__ import annotations

import hashlib
import json
import struct
from typing import Any, Dict, Optional, Tuple

import numpy as np

try:
    import zlib
    _HAVE_ZLIB = True
except Exception:  # pragma: no cover
    _HAVE_ZLIB = False

# Marker that identifies our footer / blob.
_MAGIC = b"EKB1"
_FOOTER_LEN = 12  # magic(4) + rows(4) + blob_len(4)

# Tag used to derive the masking keystream. Changing it breaks older carriers.
_MASK_TAG = b"EXPLD_EMBED_MASK_v1"


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _keystream(n: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < n:
        out += hashlib.sha256(_MASK_TAG + struct.pack(">Q", counter)).digest()
        counter += 1
    return bytes(out[:n])


def _mask(data: bytes) -> bytes:
    ks = _keystream(len(data))
    return bytes(b ^ k for b, k in zip(data, ks))


def _compress(raw: bytes) -> bytes:
    return zlib.compress(raw, 9) if _HAVE_ZLIB else raw


def _decompress(data: bytes) -> bytes:
    return zlib.decompress(data) if _HAVE_ZLIB else data


def _build_blob(key_info: Dict[str, Any]) -> bytes:
    """Serialize -> compress -> mask -> prefix magic."""
    raw = json.dumps(key_info, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return _MAGIC + _mask(_compress(raw))


def _parse_blob(blob: bytes) -> Dict[str, Any]:
    if blob[:4] != _MAGIC:
        raise ValueError("Embedded key blob is corrupt (magic mismatch).")
    raw = _decompress(_mask(blob[4:]))
    return json.loads(raw.decode("utf-8"))


def _bytes_to_bits(data: bytes) -> np.ndarray:
    return np.unpackbits(np.frombuffer(data, dtype=np.uint8))


def _bits_to_bytes(bits: np.ndarray) -> bytes:
    return np.packbits(bits).tobytes()


def _write_bits_into_lsb(cells: np.ndarray, bits: np.ndarray) -> None:
    """In-place: set LSB of cells[:len(bits)] to bits."""
    n = bits.size
    cells[:n] = (cells[:n] & 0xFE) | bits.astype(np.uint8)


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def carrier_cells_needed(key_info: Dict[str, Any]) -> int:
    """LSB cells (channel values) a carrier for `key_info` needs at minimum."""
    return len(_build_blob(key_info)) * 8 + _FOOTER_LEN * 8


def build_carrier(width: int, key_info: Dict[str, Any], rows: Optional[int] = None) -> np.ndarray:
    """
    Return the (extra_rows, width, 3) carrier rows that hide `key_info`, meant
    to be appended below the encrypted image. `rows` asks for more rows than
    the minimum (the encoder uses it to make the whole image square).

    The carrier rows (flattened, row-major over channels) hold:
        [ blob bits at the front ][ ...noise... ][ footer in the last 96 LSBs ]
    The footer (magic + extra_rows + blob_len) sits at the very end of the whole
    image, so it can be located without knowing the layout in advance. This works
    for any image width, including tiny ones.
    """
    cells_per_row = width * 3
    if cells_per_row <= 0:
        raise ValueError("Image has zero width.")

    blob = _build_blob(key_info)
    blob_bits = _bytes_to_bits(blob)
    footer_bits_len = _FOOTER_LEN * 8

    # Carrier must hold the blob at the front and the footer at the very end,
    # without the two overlapping.
    cells_needed = blob_bits.size + footer_bits_len
    extra_rows = max(int(np.ceil(cells_needed / cells_per_row)), rows or 0)
    carrier_cells = extra_rows * cells_per_row

    # Carrier filled with masked pseudo-random bytes so the LSB noise blends in.
    carrier = np.frombuffer(
        _keystream(carrier_cells), dtype=np.uint8
    ).reshape(extra_rows, width, 3).copy()
    flat = carrier.reshape(-1)

    # blob at the front
    _write_bits_into_lsb(flat, blob_bits)

    # footer in the last 96 LSB cells of the carrier (== end of whole image)
    footer = _MAGIC + struct.pack(">I", extra_rows) + struct.pack(">I", len(blob))
    footer_bits = _bytes_to_bits(footer)
    flat[carrier_cells - footer_bits_len:] = (
        (flat[carrier_cells - footer_bits_len:] & 0xFE) | footer_bits.astype(np.uint8)
    )
    return carrier


def embed_key_in_image(encrypted_arr: np.ndarray, key_info: Dict[str, Any]) -> np.ndarray:
    """
    Return a new array: the encrypted image with carrier rows appended that
    hide `key_info`. The original encrypted rows are copied unchanged.
    """
    if encrypted_arr.ndim != 3 or encrypted_arr.shape[2] != 3:
        raise ValueError("Expected an (H, W, 3) RGB array.")
    carrier = build_carrier(encrypted_arr.shape[1], key_info)
    return np.vstack([encrypted_arr, carrier]).astype(np.uint8)


def footer_rows(width: int) -> int:
    """How many trailing image rows the 96-cell footer can span."""
    return -(-(_FOOTER_LEN * 8) // (width * 3))


def read_footer(tail: np.ndarray) -> Optional[Tuple[int, int]]:
    """
    Return (extra_rows, blob_len) from the footer in the last 96 LSBs of `tail`
    (the whole image, or just its last `footer_rows(width)` rows), or None if
    there is no embedded key.
    """
    flat = tail.reshape(-1)
    footer_bits_len = _FOOTER_LEN * 8
    if flat.size < footer_bits_len:
        return None
    footer = _bits_to_bytes((flat[-footer_bits_len:] & 1).astype(np.uint8))
    if footer[:4] != _MAGIC:
        return None
    (extra_rows,) = struct.unpack(">I", footer[4:8])
    (blob_len,) = struct.unpack(">I", footer[8:12])
    return extra_rows, blob_len


def read_key_from_carrier(carrier: np.ndarray, blob_len: int) -> Dict[str, Any]:
    """Decode key_info from exactly the carrier rows (as built by build_carrier)."""
    flat = carrier.reshape(-1)
    blob_bits_needed = blob_len * 8
    if blob_bits_needed > flat.size - _FOOTER_LEN * 8:
        raise ValueError("Embedded key blob is truncated.")
    blob_bits = (flat[:blob_bits_needed] & 1).astype(np.uint8)
    return _parse_blob(_bits_to_bytes(blob_bits))


def image_has_embedded_key(full_arr: np.ndarray) -> bool:
    """Quick check: do the last 96 LSBs of the image start with our magic?"""
    try:
        if full_arr.ndim != 3 or full_arr.shape[2] != 3:
            return False
        return read_footer(full_arr) is not None
    except Exception:
        return False


def extract_key_and_strip(full_arr: np.ndarray) -> Tuple[Dict[str, Any], np.ndarray]:
    """
    Read the embedded key and return (key_info, encrypted_arr) where
    encrypted_arr is `full_arr` with the carrier rows removed.

    Raises ValueError if no valid embedded key is present.
    """
    if full_arr.ndim != 3 or full_arr.shape[2] != 3:
        raise ValueError("Expected an (H, W, 3) RGB array.")
    if full_arr.size < _FOOTER_LEN * 8:
        raise ValueError("Image too small to contain an embedded key.")

    footer = read_footer(full_arr)
    if footer is None:
        raise ValueError("No embedded key found (footer magic mismatch).")
    extra_rows, blob_len = footer

    total_rows = full_arr.shape[0]
    if extra_rows <= 0 or extra_rows >= total_rows:
        raise ValueError("Embedded key footer is invalid (bad row count).")

    key_info = read_key_from_carrier(full_arr[total_rows - extra_rows:], blob_len)
    encrypted_arr = full_arr[:total_rows - extra_rows].copy()
    return key_info, encrypted_arr
