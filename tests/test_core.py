"""
Roundtrip tests for Byte Exploder.

Runnable either with pytest:
    pytest -q
or directly:
    python tests/test_core.py
"""

import hashlib
import math
import os
import struct
import sys
import tempfile

# Make the project root importable when run directly.
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402

from exploder_core import (  # noqa: E402
    decode_image,
    decode_to_bytes,
    encode_file,
    encode_text,
    kdf,
    read_embedded_key,
)


def _roundtrip(tmp, data: bytes, embed: bool, safe: bool):
    src = os.path.join(tmp, "in.bin")
    with open(src, "wb") as f:
        f.write(data)
    png = os.path.join(tmp, f"enc_{int(embed)}_{int(safe)}.png")
    key_info = encode_file(src, png, embed_key=embed, safe_mode=safe)
    out = os.path.join(tmp, f"out_{int(embed)}_{int(safe)}.bin")
    decode_image(png, out, key_info=None if embed else key_info, safe_mode=safe)
    with open(out, "rb") as f:
        got = f.read()
    assert hashlib.sha256(got).digest() == hashlib.sha256(data).digest(), (
        f"roundtrip mismatch (embed={embed}, safe={safe})"
    )


def _reference_encrypt(data: bytes, bs: int) -> np.ndarray:
    """Straightforward per-block version of the scheme, as the original engine
    implemented it. The fast engine must produce exactly these pixels so that
    images made by older versions keep decoding."""
    raw = struct.pack(">Q", len(data)) + data
    size = math.ceil(math.sqrt(math.ceil(len(raw) / 3)))
    flat = np.zeros(size * size * 3, np.uint8)
    flat[:len(raw)] = np.frombuffer(raw, np.uint8)
    p = -(-size // bs) * bs
    arr = np.pad(flat.reshape(size, size, 3), ((0, p - size), (0, p - size), (0, 0)))

    key = kdf(arr.shape, hashlib.sha256(data[:64]).digest())
    k = np.frombuffer(key, np.uint8)
    chain = hashlib.sha256(key).digest()
    for y in range(0, p, bs):
        for x in range(0, p, bs):
            b = arr[y:y + bs, x:x + bs].copy().reshape(-1)
            b ^= k[(np.arange(b.size) + x + y) % k.size]
            b ^= np.resize(np.frombuffer(chain, np.uint8), b.size)
            chain = hashlib.sha256(chain + b.tobytes()).digest()
            arr[y:y + bs, x:x + bs] = b.reshape(bs, bs, 3)
    return arr


def test_all_modes():
    data = (b"Byte Exploder roundtrip test. " * 400)  # ~12 KB
    with tempfile.TemporaryDirectory() as tmp:
        for embed in (False, True):
            for safe in (False, True):
                _roundtrip(tmp, data, embed=embed, safe=safe)


def test_various_sizes_embedded():
    with tempfile.TemporaryDirectory() as tmp:
        for size in (0, 1, 100, 1024, 50_000):
            _roundtrip(tmp, os.urandom(size), embed=True, safe=False)


def test_matches_reference_scheme():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        png = os.path.join(tmp, "enc.png")
        for size in (0, 5, 4097, 30_000):
            data = os.urandom(size)
            with open(src, "wb") as f:
                f.write(data)
            for bs in (8, 9, 16, 64):
                encode_file(src, png, block_size=bs)
                got = np.asarray(Image.open(png))
                assert np.array_equal(got, _reference_encrypt(data, bs)), (size, bs)


def test_key_not_in_metadata():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(20_000))
        png = os.path.join(tmp, "enc.png")
        key_info = encode_file(src, png, embed_key=True)
        raw = open(png, "rb").read()
        assert key_info["salt"].encode() not in raw, "salt leaked into raw PNG bytes"
        assert b"orig_shape" not in raw, "key JSON leaked into raw PNG bytes"
        assert Image.open(png).info == {} or "key" not in Image.open(png).info


def test_backup_key_decodes_embedded_image():
    # The app saves a backup .key next to an embedded-key image and fills it in
    # automatically; decoding with it must ignore the carrier rows.
    data = os.urandom(30_000)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        with open(src, "wb") as f:
            f.write(data)
        png = os.path.join(tmp, "enc.png")
        key_info = encode_file(src, png, embed_key=True)
        for safe in (False, True):
            out = os.path.join(tmp, f"out_{safe}.bin")
            decode_image(png, out, key_info=key_info, safe_mode=safe)
            assert open(out, "rb").read() == data


def test_embedded_images_are_square():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        png = os.path.join(tmp, "enc.png")
        out = os.path.join(tmp, "out.bin")
        for size in (0, 1, 5000, 120_000):
            data = os.urandom(size)
            with open(src, "wb") as f:
                f.write(data)
            key_info = encode_file(src, png, embed_key=True)
            w, h = Image.open(png).size
            assert w == h, (size, w, h)
            for key in (None, key_info):  # embedded key, then the backup key
                decode_image(png, out, key_info=key)
                assert open(out, "rb").read() == data


def test_old_tall_embedded_layout_still_decodes():
    # Images from earlier versions put the carrier rows below the image without
    # widening it, so they were taller than wide.
    from key_embed import embed_key_in_image
    data = os.urandom(3000)
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        with open(src, "wb") as f:
            f.write(data)
        png = os.path.join(tmp, "plain.png")
        key_info = encode_file(src, png)
        key_info["key_embedded"] = True
        tall = embed_key_in_image(np.asarray(Image.open(png)), key_info)
        assert tall.shape[0] > tall.shape[1]
        old = os.path.join(tmp, "old.png")
        Image.fromarray(tall).save(old)
        out = os.path.join(tmp, "out.bin")
        decode_image(old, out)
        assert open(out, "rb").read() == data


def test_text_roundtrip():
    text = "سلام دنیا — Hello 👋\nline 2\r\ntabs\tand  spaces " * 50
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "text.png")
        for embed in (False, True):
            key_info = encode_text(text, png, embed_key=embed)
            assert key_info["input_is_text"] is True
            data, used_key = decode_to_bytes(png, key_info=None if embed else key_info)
            assert data.decode("utf-8") == text
            assert used_key["input_is_text"] is True
        assert read_embedded_key(png)["input_is_text"] is True


def test_wrong_key_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = os.path.join(tmp, "a.bin"), os.path.join(tmp, "b.bin")
        for p in (a, b):
            with open(p, "wb") as f:
                f.write(os.urandom(10_000))  # same size -> same image shape
        key_a = encode_file(a, os.path.join(tmp, "a.png"))
        encode_file(b, os.path.join(tmp, "b.png"))
        out = os.path.join(tmp, "out.bin")
        try:
            decode_image(os.path.join(tmp, "b.png"), out, key_info=key_a)
        except ValueError:
            pass
        else:
            raise AssertionError("decoding with the wrong key should fail")
        assert not os.path.exists(out) and not os.path.exists(out + ".part")


def test_cancel_leaves_no_partial_file():
    with tempfile.TemporaryDirectory() as tmp:
        src = os.path.join(tmp, "in.bin")
        with open(src, "wb") as f:
            f.write(os.urandom(9_000_000))  # several PNG deflate jobs
        png = os.path.join(tmp, "enc.png")
        # 50 -> while scrambling, 85 -> while writing the PNG
        for threshold in (50, 85):
            def cancel_at(p):
                if p > threshold:
                    raise RuntimeError("CANCELLED")
            try:
                encode_file(src, png, on_progress=cancel_at)
            except RuntimeError:
                pass
            else:
                raise AssertionError("encode should have been cancelled")
            assert not os.path.exists(png) and not os.path.exists(png + ".part")


def test_folder_roundtrip():
    with tempfile.TemporaryDirectory() as tmp:
        folder = os.path.join(tmp, "docs")
        os.makedirs(os.path.join(folder, "sub"))
        files = {"a.txt": b"hello", os.path.join("sub", "b.bin"): os.urandom(5000)}
        for rel, content in files.items():
            with open(os.path.join(folder, rel), "wb") as f:
                f.write(content)
        png = os.path.join(tmp, "docs.png")
        key_info = encode_file(folder, png)
        out = os.path.join(tmp, "restored.zip")
        decode_image(png, out, key_info=key_info)
        restored = os.path.join(tmp, "restored_docs")
        for rel, content in files.items():
            assert open(os.path.join(restored, rel), "rb").read() == content


if __name__ == "__main__":
    test_all_modes()
    test_various_sizes_embedded()
    test_matches_reference_scheme()
    test_key_not_in_metadata()
    test_backup_key_decodes_embedded_image()
    test_text_roundtrip()
    test_wrong_key_is_rejected()
    test_cancel_leaves_no_partial_file()
    test_folder_roundtrip()
    print("All tests passed.")
