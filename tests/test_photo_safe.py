"""
Tests for photo-safe images: they must survive what a messenger does to a
photo (JPEG re-encoding, shrinking) and reject the wrong key.
"""

import io
import os
import sys
import tempfile

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from PIL import Image  # noqa: E402

import photo_safe  # noqa: E402

META = {"file_name": "note.bin", "file_size": 0, "input_is_text": False, "input_is_folder": False}


def _sent_as_photo(path: str, quality: int, side=None) -> Image.Image:
    """What a messenger does to an image sent as a photo."""
    img = Image.open(path).convert("RGB")
    if side:
        img = img.resize((side, side), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality, subsampling=2)
    buf.seek(0)
    return Image.open(buf)


def test_survives_jpeg_and_resizing():
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "p.png")
        for size in (0, 50, 3000, photo_safe.CAPACITY - 200):
            payload = os.urandom(size)  # random data: no help from compression
            photo_safe.encode(payload, META, png, embed_key=True)
            img = Image.open(png)
            assert img.width == img.height <= photo_safe.MAX_SIDE
            for quality, side in ((95, None), (87, None), (60, None), (40, None), (80, img.width * 3 // 4), (75, img.width // 2)):
                got, meta = photo_safe.decode(_sent_as_photo(png, quality, side))
                assert got == payload, (size, quality, side)
                assert meta["file_name"] == "note.bin"


def test_text_compresses_beyond_raw_capacity():
    text = ("سلام، این یک پیام آزمایشی است. Hello! " * 2000).encode("utf-8")
    assert len(text) > photo_safe.CAPACITY
    assert photo_safe.body_size(text, META) <= photo_safe.CAPACITY
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "t.png")
        photo_safe.encode(text, META, png, embed_key=True)
        assert photo_safe.decode(_sent_as_photo(png, 80))[0] == text


def test_key_file_mode_and_wrong_key():
    with tempfile.TemporaryDirectory() as tmp:
        a, b = os.path.join(tmp, "a.png"), os.path.join(tmp, "b.png")
        key_a = photo_safe.encode(b"first secret", META, a, embed_key=False)
        key_b = photo_safe.encode(b"second secret", META, b, embed_key=False)
        assert photo_safe.decode(_sent_as_photo(a, 85), key_a)[0] == b"first secret"
        for key in (None, key_b):
            try:
                photo_safe.decode(a, key)
            except ValueError as e:
                assert "key" in str(e).lower()
            else:
                raise AssertionError("decoding without the right key should fail")


def test_too_big_is_rejected():
    with tempfile.TemporaryDirectory() as tmp:
        try:
            photo_safe.encode(os.urandom(photo_safe.CAPACITY + 1), META, os.path.join(tmp, "x.png"), True)
        except photo_safe.TooBigForPhoto:
            pass
        else:
            raise AssertionError("oversized payload should be rejected")


def test_normal_images_are_not_photo_safe():
    with tempfile.TemporaryDirectory() as tmp:
        png = os.path.join(tmp, "noise.png")
        Image.frombytes("RGB", (300, 300), os.urandom(300 * 300 * 3)).save(png)
        try:
            photo_safe.decode(png)
        except photo_safe.NotPhotoSafe:
            pass
        else:
            raise AssertionError("random image should not be detected as photo-safe")
