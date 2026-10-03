# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
photo_safe.py
-------------
Photo-safe images: small files or texts that survive being sent as a
compressed photo (for example in Telegram without "Send as document"), which
re-encodes the image as JPEG and may shrink it.

Normal Byte Exploder images store one byte in every color channel of every
pixel, so any lossy step destroys them. A photo-safe image stores one bit per
square tile in its brightness instead (dark tile = 0, light tile = 1); the tile
colors come from the app palette and carry no data. Brightness of whole tiles
survives JPEG (tested down to quality 40) and resizing (down to half size). The
price is capacity: at most CAPACITY bytes per image, after zlib compression.

Layout: a square of G x G tiles, `cell` px each, side G * cell <= 1280 px so
messengers don't shrink it.
    tile row 0          timing pattern light, dark, light, ... (G is even) -
                        the reader finds G from it, whatever the pixel size
    tile rows 1..G-1    data bits, row-major; unused tiles are random
Data stream (big-endian):
    MAGIC(4) | flags(1) | [salt(16) if the key is embedded] | body_len(4) | body | crc32(4)
    body = keystream(salt) XOR [zlib](meta_len(2) | meta JSON | payload)
Without an embedded key the salt lives only in the key file.

Like the rest of the app this is obfuscation, not vetted cryptography.
"""

from __future__ import annotations

import hashlib
import json
import os
import struct
import zlib
from typing import Any, Dict, Optional, Tuple

import numpy as np
from PIL import Image

MAGIC = b"BXP1"
FLAG_KEY_EMBEDDED = 1
FLAG_COMPRESSED = 2
_SECRET = b"BXP_PHOTO_SAFE_v1"

MAX_SIDE = 1280             # Telegram and most messengers keep photos up to this size
MIN_CELL, MAX_CELL = 4, 16  # px per tile
MIN_GRID = 16
MAX_GRID = MAX_SIDE // MIN_CELL                        # 320 tiles per side
_HEADER = len(MAGIC) + 1 + 16 + 4                      # with an embedded salt
CAPACITY = (MAX_GRID - 1) * MAX_GRID // 8 - _HEADER - 4  # max body bytes
MAX_SIDE_TO_SCAN = 4096     # bigger images are never photo-safe

# Tile colors: brightness (luma) is all that matters; dark ones stay far below
# 128 and light ones far above, with moderate saturation so JPEG's color
# subsampling can't push luma across.
_DARK = np.array([[35, 58, 140], [11, 79, 77], [74, 31, 61]], np.uint8)       # lapis, deep teal, plum
_LIGHT = np.array([[237, 240, 238], [159, 227, 221], [245, 207, 122]], np.uint8)  # plaster, turquoise, saffron


class NotPhotoSafe(ValueError):
    pass


class TooBigForPhoto(ValueError):
    def __init__(self, size: int):
        super().__init__(f"Too big for a photo-safe image ({size} bytes after compression, max {CAPACITY}).")
        self.size = size


def _keystream(salt: bytes, n: int) -> np.ndarray:
    key = hashlib.sha256(_SECRET + salt).digest()
    blocks = (hashlib.sha256(key + struct.pack(">Q", i)).digest() for i in range(-(-n // 32)))
    return np.frombuffer(b"".join(blocks), np.uint8)[:n]


def _xor(data: bytes, salt: bytes) -> bytes:
    return (np.frombuffer(data, np.uint8) ^ _keystream(salt, len(data))).tobytes()


def _inner(payload: bytes, meta: Dict[str, Any]) -> Tuple[bytes, int]:
    meta_json = json.dumps(meta, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    inner = struct.pack(">H", len(meta_json)) + meta_json + payload
    packed = zlib.compress(inner, 9)
    if len(packed) < len(inner):
        return packed, FLAG_COMPRESSED
    return inner, 0


def body_size(payload: bytes, meta: Dict[str, Any]) -> int:
    """Bytes the payload takes in a photo-safe image (compare with CAPACITY)."""
    return len(_inner(payload, meta)[0])


def encode(payload: bytes, meta: Dict[str, Any], output_path: str, embed_key: bool) -> Dict[str, Any]:
    """Write a photo-safe PNG and return its key_info (salt + meta)."""
    inner, flags = _inner(payload, meta)
    if len(inner) > CAPACITY:
        raise TooBigForPhoto(len(inner))

    salt = os.urandom(16)
    if embed_key:
        flags |= FLAG_KEY_EMBEDDED
    head = MAGIC + bytes([flags]) + (salt if embed_key else b"") + struct.pack(">I", len(inner))
    stream = head + _xor(inner, salt)
    stream += struct.pack(">I", zlib.crc32(stream) & 0xFFFFFFFF)
    bits = np.unpackbits(np.frombuffer(stream, np.uint8))

    grid_side = MIN_GRID
    while (grid_side - 1) * grid_side < bits.size:
        grid_side += 2  # stays even, so the timing row has a whole number of periods
    cell = min(MAX_CELL, max(MIN_CELL, MAX_SIDE // grid_side))

    rng = np.random.default_rng()
    grid = np.empty((grid_side, grid_side), np.uint8)
    grid[0] = np.arange(grid_side) % 2 == 0
    data = rng.integers(0, 2, (grid_side - 1) * grid_side, dtype=np.uint8)
    data[:bits.size] = bits
    grid[1:] = data.reshape(grid_side - 1, grid_side)

    shade = rng.integers(0, len(_DARK), grid.shape)
    tiles = np.where(grid[..., None] == 1, _LIGHT[shade], _DARK[shade])
    pixels = np.repeat(np.repeat(tiles, cell, axis=0), cell, axis=1)
    Image.fromarray(pixels).save(output_path, format="PNG")

    return {
        "version": "BXP1",
        "mode": "photo-safe",
        "salt": salt.hex(),
        "grid": grid_side,
        "key_embedded": bool(embed_key),
        **meta,
    }


def _grid_side(luma: np.ndarray) -> Optional[int]:
    """Number of tiles per side, from the frequency of the timing row."""
    row = luma[:2].mean(axis=0)  # inside tile row 0 even after shrinking to half size
    spectrum = np.abs(np.fft.rfft(row - row.mean()))
    if spectrum.size < 3:
        return None
    periods = int(np.argmax(spectrum[1:]) + 1)
    side = 2 * periods
    return side if MIN_GRID <= side <= 2 * MAX_GRID else None


def _read_tiles(luma: np.ndarray, side: int) -> np.ndarray:
    """Mean brightness of the middle of every tile -> 0/1, shape (side, side)."""
    h, w = luma.shape
    integral = np.zeros((h + 1, w + 1))
    integral[1:, 1:] = luma.cumsum(0).cumsum(1)

    def bounds(length):
        cs = length / side
        i = np.arange(side)
        a = np.floor((i + 0.3) * cs).astype(int)
        b = np.maximum(a + 1, np.floor((i + 0.7) * cs).astype(int))
        return a, np.minimum(b, length)

    y0, y1 = bounds(h)
    x0, x1 = bounds(w)
    sums = (integral[np.ix_(y1, x1)] - integral[np.ix_(y0, x1)]
            - integral[np.ix_(y1, x0)] + integral[np.ix_(y0, x0)])
    area = np.outer(y1 - y0, x1 - x0)
    return (sums / area > 128).astype(np.uint8)


def read_stream(img: Image.Image) -> bytes:
    """Recover the raw data stream from a (possibly JPEG-compressed or resized)
    photo-safe image. Raises NotPhotoSafe if it isn't one."""
    w, h = img.size
    if max(w, h) > MAX_SIDE_TO_SCAN or abs(w - h) > max(2, w // 100):
        raise NotPhotoSafe("Not a photo-safe image.")
    luma = np.asarray(img.convert("L"), np.float64)
    side = _grid_side(luma)
    if side is None:
        raise NotPhotoSafe("Not a photo-safe image.")
    tiles = _read_tiles(luma, side)
    stream = np.packbits(tiles[1:].reshape(-1)).tobytes()
    if stream[:4] != MAGIC:
        raise NotPhotoSafe("Not a photo-safe image.")
    return stream


def _parse(stream: bytes) -> Tuple[int, Optional[bytes], bytes]:
    """(flags, embedded salt or None, encrypted body); checks the CRC."""
    flags = stream[4]
    pos = 5
    salt = None
    if flags & FLAG_KEY_EMBEDDED:
        salt = stream[pos:pos + 16]
        pos += 16
    (body_len,) = struct.unpack(">I", stream[pos:pos + 4])
    pos += 4
    end = pos + body_len
    if end + 4 > len(stream):
        raise ValueError("Photo-safe image is damaged (bad length).")
    (crc,) = struct.unpack(">I", stream[end:end + 4])
    if zlib.crc32(stream[:end]) & 0xFFFFFFFF != crc:
        raise ValueError("Photo-safe image is damaged (checksum mismatch).")
    return flags, salt, stream[pos:end]


def has_embedded_key(stream: bytes) -> bool:
    return bool(stream[4] & FLAG_KEY_EMBEDDED)


def decode_stream(stream: bytes, key_info: Optional[Dict[str, Any]] = None) -> Tuple[bytes, Dict[str, Any]]:
    """Return (payload, meta). Uses the salt in the image, or the key file's."""
    flags, salt, body = _parse(stream)
    if salt is None:
        if not key_info or not key_info.get("salt"):
            raise ValueError("No key supplied and no embedded key found in the image.")
        salt = bytes.fromhex(key_info["salt"])
    inner = _xor(body, salt)
    try:
        if flags & FLAG_COMPRESSED:
            inner = zlib.decompress(inner)
        (meta_len,) = struct.unpack(">H", inner[:2])
        meta = json.loads(inner[2:2 + meta_len].decode("utf-8"))
        if not isinstance(meta, dict):
            raise ValueError
    except (zlib.error, ValueError, struct.error, UnicodeDecodeError):
        raise ValueError("Wrong key for this image (photo-safe data did not decode).") from None
    return inner[2 + meta_len:], meta


def decode(image, key_info: Optional[Dict[str, Any]] = None) -> Tuple[bytes, Dict[str, Any]]:
    """Decode a photo-safe image given as a path or an opened PIL image."""
    if isinstance(image, Image.Image):
        return decode_stream(read_stream(image), key_info)
    with Image.open(image) as im:
        return decode_stream(read_stream(im), key_info)
