# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
web_api.py
----------
Python side of the webview UI (app.py). pywebview exposes the public methods
of `Api` to the page as `window.pywebview.api.<name>(...)`; every call runs on
its own thread, so slow work never freezes the window.

Encoding/decoding run as jobs on background threads. The page polls
`job_status` for progress, new log lines and the result, and can `cancel`.

Errors are returned as {"code": ..., <args>}; the page turns them into text in
the current UI language (web/i18n.js).
"""

from __future__ import annotations

import base64
import io
import itertools
import json
import os
import subprocess
import sys
import threading
import zipfile
from typing import Any, Callable, Dict, Optional, Tuple

import webview
from PIL import Image

import photo_safe
from exploder_core import (
    MAX_BLOCK_SIZE,
    MIN_BLOCK_SIZE,
    TEXT_FILE_NAME,
    decode_image,
    decode_to_bytes,
    encode_file,
    encode_text,
    load_key_info,
    read_embedded_key,
    save_key_info,
)

# Images up to this size get a thumbnail and an embedded-key check when picked
# (both need the whole PNG decoded); bigger ones are only inspected on decode.
PREVIEW_MAX_FILE = 150 * 1024 * 1024
THUMB_SIZE = 360
PEEK_BYTES = 3 * 128 * 128  # first bytes of an input file, drawn as pixels
LANGUAGES = ("fa", "en")
# Inputs bigger than this can't fit a photo-safe image even after compression.
PHOTO_MAX_INPUT = 8 * 1024 * 1024
# Formats a messenger produces when it compresses a photo.
LOSSY_FORMATS = {"JPEG", "MPO", "WEBP", "HEIF", "AVIF"}

IMAGE_TYPES = ("Images (*.png;*.expld;*.jpg;*.jpeg;*.webp)", "All files (*.*)")
KEY_TYPES = ("Key files (*.json)", "All files (*.*)")
OUTPUT_TYPES = {
    ".png": ("PNG image (*.png)", "All files (*.*)"),
    ".expld": ("EXPLD image (*.expld)", "All files (*.*)"),
}


def _dialog(kind: str):
    """pywebview >= 6 uses webview.FileDialog.X, older versions X_DIALOG."""
    enum = getattr(webview, "FileDialog", None)
    if enum is not None:
        return getattr(enum, kind)
    return getattr(webview, f"{kind}_DIALOG")


def _first(result) -> Optional[str]:
    if not result:
        return None
    if isinstance(result, str):
        return result
    return result[0]


def _err(code: str, **args) -> Dict[str, Any]:
    return {"code": code, **args}


class _Compressed(Exception):
    """A normal image that went through lossy compression (sent as a photo)."""


def _friendly(e: BaseException) -> Dict[str, Any]:
    """Map an exception to an error code the page can translate."""
    msg = str(e)
    if isinstance(e, photo_safe.TooBigForPhoto):
        return _err("too_big_photo", size=e.size, capacity=photo_safe.CAPACITY)
    if isinstance(e, _Compressed):
        return _err("compressed")
    if msg.startswith("Photo-safe image is damaged"):
        return _err("photo_damaged")
    if isinstance(e, MemoryError):
        return _err("memory", message=msg)
    if isinstance(e, FileNotFoundError):
        return _err("not_found", path=e.filename or msg)
    if isinstance(e, PermissionError):
        return _err("permission", path=e.filename or msg)
    if msg.startswith("Wrong key"):
        return _err("wrong_key")
    if msg.startswith("Image size mismatch"):
        return _err("size_mismatch")
    if msg.startswith("No key supplied"):
        return _err("no_key")
    if "cannot identify image file" in msg:
        return _err("not_image")
    return _err("raw", message=msg)


def _key_summary(key_info: Dict[str, Any]) -> Dict[str, Any]:
    if key_info.get("input_is_text"):
        kind = "text"
    elif key_info.get("input_is_folder"):
        kind = "folder"
    else:
        kind = "file"
    return {
        "kind": kind,
        "name": key_info.get("folder_name") if kind == "folder" else key_info.get("file_name"),
        "size": key_info.get("file_size"),
        "block_size": key_info.get("block_size"),
        "embedded": bool(key_info.get("key_embedded")),
    }


def _settings_path() -> str:
    if sys.platform.startswith("win"):
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "ByteExploder", "settings.json")


def _load_settings() -> Dict[str, Any]:
    try:
        with open(_settings_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _photo_payload(mode: str, path: str, text: str) -> Tuple[bytes, Dict[str, Any]]:
    """Bytes and meta for a photo-safe image; raises TooBigForPhoto early for
    inputs that can't fit even after compression."""
    if mode == "text":
        data = text.encode("utf-8")
        return data, {"file_name": TEXT_FILE_NAME, "file_size": len(data),
                      "input_is_text": True, "input_is_folder": False}
    if os.path.isdir(path):
        total = sum(os.path.getsize(os.path.join(r, f)) for r, _, fs in os.walk(path) for f in fs)
        if total > PHOTO_MAX_INPUT:
            raise photo_safe.TooBigForPhoto(total)
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            for root, _, files in os.walk(path):
                for name in files:
                    full = os.path.join(root, name)
                    zf.write(full, arcname=os.path.relpath(full, path).replace("\\", "/"))
        data = buf.getvalue()
        folder = os.path.basename(os.path.normpath(path))
        return data, {"file_name": folder + ".zip", "file_size": len(data),
                      "input_is_text": False, "input_is_folder": True, "folder_name": folder}
    size = os.path.getsize(path)
    if size > PHOTO_MAX_INPUT:
        raise photo_safe.TooBigForPhoto(size)
    with open(path, "rb") as f:
        data = f.read()
    return data, {"file_name": os.path.basename(path), "file_size": len(data),
                  "input_is_text": False, "input_is_folder": False}


def _photo_stream(img: Image.Image) -> Optional[bytes]:
    try:
        return photo_safe.read_stream(img)
    except photo_safe.NotPhotoSafe:
        return None


def _write_atomically(path: str, data: bytes) -> None:
    part = path + ".part"
    try:
        with open(part, "wb") as f:
            f.write(data)
        os.replace(part, path)
    except BaseException:
        try:
            os.remove(part)
        except OSError:
            pass
        raise


class _Cancelled(Exception):
    pass


class _Job:
    _ids = itertools.count(1)

    def __init__(self):
        self.id = next(self._ids)
        self.state = "running"  # running | done | error | cancelled
        self.progress = 0
        self.logs: list = []
        self.result: Any = None
        self.error: Optional[Dict[str, Any]] = None
        self.cancel = threading.Event()
        self.thread: Optional[threading.Thread] = None

    def log(self, msg) -> None:
        self.logs.append(str(msg))

    def on_progress(self, p) -> None:
        if self.cancel.is_set():
            raise _Cancelled()
        self.progress = int(p)


class Api:
    def __init__(self, initial_image: Optional[str] = None):
        self._window = None
        self._jobs: Dict[int, _Job] = {}
        self._initial_image = initial_image
        self._settings = _load_settings()

    def _attach(self, window) -> None:
        self._window = window
        window.events.closing += self._on_closing

    def _on_closing(self):
        # Let running jobs stop at their next progress point so they can
        # remove their half-written ".part" files.
        running = [j for j in self._jobs.values() if j.state == "running"]
        for job in running:
            job.cancel.set()
        for job in running:
            job.thread.join(timeout=10)

    # ------------------------------------------------------------ dialogs
    def _ask_open(self, kind: str, types=()) -> Optional[str]:
        return _first(self._window.create_file_dialog(_dialog(kind), file_types=types))

    def _ask_save(self, directory: str, name: str, types=()) -> Optional[str]:
        return _first(self._window.create_file_dialog(
            _dialog("SAVE"), directory=directory, save_filename=name, file_types=types
        ))

    def pick_file(self):
        return self._ask_open("OPEN")

    def pick_folder(self):
        return self._ask_open("FOLDER")

    def pick_image(self):
        return self._ask_open("OPEN", IMAGE_TYPES)

    def pick_key(self):
        return self._ask_open("OPEN", KEY_TYPES)

    # ------------------------------------------------------------ settings
    def initial_state(self):
        lang = self._settings.get("language")
        return {
            "image": self._initial_image,
            "lang": lang if lang in LANGUAGES else None,
            "tour_done": bool(self._settings.get("tour_done")),
            "photo_capacity": photo_safe.CAPACITY,
        }

    def set_language(self, lang: str):
        if lang not in LANGUAGES:
            return False
        self._settings["language"] = lang
        return self._save_settings()

    def set_tour_done(self):
        self._settings["tour_done"] = True
        return self._save_settings()

    def _save_settings(self) -> bool:
        try:
            path = _settings_path()
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as f:
                json.dump(self._settings, f, indent=2)
        except OSError:
            return False
        return True

    # ------------------------------------------------------------ info
    def describe_input(self, path: str):
        """Kind and size of an input, plus its first bytes (base64) so the
        page can draw them as pixels."""
        if not path or not os.path.exists(path):
            return {"error": _err("path_missing")}
        name = os.path.basename(os.path.normpath(path))
        if os.path.isdir(path):
            return {"kind": "folder", "name": name}
        try:
            with open(path, "rb") as f:
                head = f.read(PEEK_BYTES)
            return {
                "kind": "file",
                "name": name,
                "size": os.path.getsize(path),
                "head": base64.b64encode(head).decode("ascii"),
            }
        except OSError as e:
            return {"error": _friendly(e)}

    def image_info(self, path: str):
        """Dimensions, a pixel-exact thumbnail and (for images that are not too
        big) whether a key is embedded."""
        if not path or not os.path.exists(path):
            return {"error": _err("path_missing")}
        size = os.path.getsize(path)
        # The app saves "<image>_key.json" next to every image it makes.
        sibling_key = os.path.splitext(path)[0] + "_key.json"
        try:
            with Image.open(path) as im:
                info: Dict[str, Any] = {
                    "name": os.path.basename(path),
                    "size": size,
                    "width": im.width,
                    "height": im.height,
                    "thumb": None,
                    "key": None,
                    "key_checked": False,
                    "sibling_key": sibling_key if os.path.isfile(sibling_key) else None,
                    "photo_safe": False,
                    "compressed": False,
                }
                if size <= PREVIEW_MAX_FILE:
                    rgb = im if im.mode == "RGB" else im.convert("RGB")
                    stream = _photo_stream(rgb)
                    if stream is not None:
                        info["photo_safe"] = True
                        if photo_safe.has_embedded_key(stream):
                            _, meta = photo_safe.decode_stream(stream)
                            info["key"] = _key_summary({**meta, "key_embedded": True})
                    else:
                        info["compressed"] = im.format in LOSSY_FORMATS
                        key_info = read_embedded_key(rgb)
                        info["key"] = _key_summary(key_info) if key_info else None
                    info["key_checked"] = True
                    thumb = rgb.copy()
                    # Nearest keeps scrambled pixels crisp; tiles average better.
                    thumb.thumbnail((THUMB_SIZE, THUMB_SIZE), Image.BOX if stream else Image.NEAREST)
                    buf = io.BytesIO()
                    thumb.save(buf, format="PNG")
                    info["thumb"] = "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode("ascii")
            return info
        except Exception as e:
            return {"error": _friendly(e)}

    def check_key(self, opts: Dict[str, Any]):
        key_path = (opts.get("key") or "").strip()
        image = (opts.get("image") or "").strip()
        try:
            if key_path:
                return {"source": "file", **_key_summary(load_key_info(key_path))}
            if not image or not os.path.exists(image):
                return {"error": _err("pick_key_or_image")}
            with Image.open(image) as im:
                stream = _photo_stream(im)
                if stream is not None and photo_safe.has_embedded_key(stream):
                    _, meta = photo_safe.decode_stream(stream)
                    return {"source": "embedded", **_key_summary({**meta, "key_embedded": True})}
                key_info = None if stream is not None else read_embedded_key(im)
            if key_info is None:
                return {"error": _err("no_embedded_key")}
            return {"source": "embedded", **_key_summary(key_info)}
        except (ValueError, KeyError):
            return {"error": _err("key_invalid")}
        except Exception as e:
            return {"error": _friendly(e)}

    # ------------------------------------------------------------ jobs
    def _start(self, work: Callable[[_Job], Any]) -> int:
        job = _Job()
        self._jobs[job.id] = job

        def run():
            try:
                job.result = work(job)
                job.progress = 100
                job.state = "done"
            except _Cancelled:
                job.log("[!] Cancelled.")
                job.state = "cancelled"
            except Exception as e:
                job.log(f"[!] {e}")
                job.error = _friendly(e)
                job.state = "error"

        job.thread = threading.Thread(target=run, name=f"job-{job.id}")
        job.thread.start()
        return job.id

    def job_status(self, job_id: int, since: int = 0):
        job = self._jobs.get(int(job_id))
        if job is None:
            return {"state": "missing"}
        return {
            "state": job.state,
            "progress": job.progress,
            "logs": job.logs[int(since):],
            "result": job.result if job.state == "done" else None,
            "error": job.error,
        }

    def cancel(self, job_id: int):
        job = self._jobs.get(int(job_id))
        if job is not None:
            job.cancel.set()
        return True

    def photo_usage(self, opts: Dict[str, Any]):
        """How much of a photo-safe image this input would fill."""
        mode = opts.get("mode")
        path = (opts.get("path") or "").strip()
        if mode != "text" and (not path or not os.path.exists(path)):
            return {"used": None, "capacity": photo_safe.CAPACITY}
        try:
            payload, meta = _photo_payload(mode, path, opts.get("text") or "")
            used = photo_safe.body_size(payload, meta)
        except photo_safe.TooBigForPhoto as e:
            used = e.size
        except OSError as e:
            return {"error": _friendly(e)}
        return {"used": used, "capacity": photo_safe.CAPACITY, "fits": used <= photo_safe.CAPACITY}

    def start_encrypt(self, opts: Dict[str, Any]):
        mode = opts.get("mode")
        photo = bool(opts.get("photo_safe"))
        ext = ".expld" if opts.get("format") == "expld" and not photo else ".png"
        text = opts.get("text") or ""
        path = (opts.get("path") or "").strip()

        if mode == "text":
            if not text.strip() and not opts.get("allow_empty"):
                return {"error": _err("text_empty")}
            directory, name = os.path.expanduser("~"), "text_ENC" + ext
        else:
            if not path or not os.path.exists(path):
                return {"error": _err("input_missing")}
            path = os.path.abspath(path)
            base = os.path.basename(os.path.normpath(path))
            if os.path.isfile(path):
                base = os.path.splitext(base)[0]
            directory, name = os.path.dirname(os.path.normpath(path)), base + "_ENC" + ext

        block_size = opts.get("block_size")
        if block_size:
            block_size = int(block_size)
            if not MIN_BLOCK_SIZE <= block_size <= MAX_BLOCK_SIZE:
                return {"error": _err("block_range", min=MIN_BLOCK_SIZE, max=MAX_BLOCK_SIZE)}
        else:
            block_size = None
        embed = bool(opts.get("embed"))
        safe = bool(opts.get("safe"))

        photo_input = None
        if photo:  # check the size before asking where to save
            try:
                photo_input = _photo_payload(mode, path, text)
                used = photo_safe.body_size(*photo_input)
                if used > photo_safe.CAPACITY:
                    raise photo_safe.TooBigForPhoto(used)
            except (photo_safe.TooBigForPhoto, OSError) as e:
                return {"error": _friendly(e)}

        out = self._ask_save(directory, name, OUTPUT_TYPES[ext])
        if not out:
            return {"cancelled": True}
        if not out.lower().endswith((".png", ".expld")):
            out += ext

        def work(job: _Job):
            if photo_input is not None:
                job.log("[+] Photo-safe image (brightness tiles, survives JPEG)")
                job.on_progress(10)
                part = out + ".part"
                try:
                    key_info = photo_safe.encode(*photo_input, part, embed_key=embed)
                    os.replace(part, out)
                except BaseException:
                    if os.path.exists(part):
                        os.remove(part)
                    raise
                job.log(f"[OK] Photo-safe image saved: {out} ({key_info['grid']} x {key_info['grid']} tiles)")
            elif mode == "text":
                key_info = encode_text(
                    text, out, block_size=block_size, embed_key=embed,
                    on_progress=job.on_progress, on_log=job.log,
                )
            else:
                key_info = encode_file(
                    path, out, block_size=block_size, safe_mode=safe, embed_key=embed,
                    on_progress=job.on_progress, on_log=job.log,
                )
            key_path = os.path.splitext(out)[0] + "_key.json"
            try:
                save_key_info(key_info, key_path)
                job.log(f"[OK] Key saved: {key_path}")
            except OSError as e:
                job.log(f"[!] Failed to save key: {e}")
                key_path = None
            return {"output": out, "key_path": key_path, "embedded": bool(key_info.get("key_embedded")),
                    "photo_safe": photo_input is not None}

        return {"job": self._start(work)}

    def start_decrypt(self, opts: Dict[str, Any]):
        image = (opts.get("image") or "").strip()
        key_path = (opts.get("key") or "").strip()
        safe = bool(opts.get("safe"))

        if not image or not os.path.exists(image):
            return {"error": _err("image_missing")}
        key_info = None
        if key_path:
            if not os.path.exists(key_path):
                return {"error": _err("key_missing")}
            try:
                key_info = load_key_info(key_path)
            except Exception:
                return {"error": _err("key_invalid")}

        def work(job: _Job):
            ki = key_info
            with Image.open(image) as im:
                lossy = im.format in LOSSY_FORMATS
                stream = _photo_stream(im) if max(im.size) <= photo_safe.MAX_SIDE_TO_SCAN else None
            if stream is not None:
                job.log("[i] Photo-safe image detected.")
                payload, meta = photo_safe.decode_stream(stream, ki)
                job.on_progress(70)
                return self._deliver(job, image, payload, meta)
            if lossy:
                raise _Compressed()
            if ki is not None and ki.get("mode") == "photo-safe":
                raise ValueError("Wrong key for this image (it belongs to a photo-safe image).")
            if ki is None:
                job.log("[i] No key file selected; reading the key embedded in the image...")
                ki = read_embedded_key(image)
                if ki is None:
                    raise ValueError("No key supplied and no embedded key found in the image.")
                job.log("[OK] Embedded key found.")
            if ki.get("input_is_text"):
                data, _ = decode_to_bytes(image, ki, on_progress=job.on_progress, on_log=job.log)
                return {"text": data.decode("utf-8", errors="replace")}

            name = ki.get("file_name") or ("restored" + (ki.get("file_ext") or ".bin"))
            out = self._ask_save(os.path.dirname(os.path.abspath(image)), name)
            if not out:
                raise _Cancelled()
            decode_image(image, out, ki, safe_mode=safe, on_progress=job.on_progress, on_log=job.log)
            if ki.get("input_is_folder"):
                folder = os.path.splitext(out)[0] + "_" + (ki.get("folder_name") or "restored_folder")
                return {"output": folder, "is_folder": True}
            return {"output": out, "is_folder": False}

        return {"job": self._start(work)}

    def _deliver(self, job: _Job, image: str, payload: bytes, meta: Dict[str, Any]):
        """Return a photo-safe payload: as text, or saved where the user picks."""
        if meta.get("input_is_text"):
            return {"text": payload.decode("utf-8", errors="replace")}
        out = self._ask_save(os.path.dirname(os.path.abspath(image)), meta.get("file_name") or "restored.bin")
        if not out:
            raise _Cancelled()
        if meta.get("input_is_folder"):
            folder = os.path.splitext(out)[0] + "_" + (meta.get("folder_name") or "restored_folder")
            with zipfile.ZipFile(io.BytesIO(payload)) as zf:
                zf.extractall(folder)
            job.log(f"[OK] Folder restored: {folder}")
            return {"output": folder, "is_folder": True}
        _write_atomically(out, payload)
        job.log(f"[OK] File restored: {out}")
        return {"output": out, "is_folder": False}

    # ------------------------------------------------------------ results
    def save_text(self, text: str):
        out = self._ask_save(os.path.expanduser("~"), "text.txt", ("Text (*.txt)", "All files (*.*)"))
        if not out:
            return {"cancelled": True}
        try:
            with open(out, "w", encoding="utf-8", newline="") as f:
                f.write(text)
            return {"saved": out}
        except OSError as e:
            return {"error": _friendly(e)}

    def reveal(self, path: str):
        """Open the folder that contains `path` (or `path` itself if it is one)."""
        target = path if os.path.isdir(path) else os.path.dirname(path)
        if not os.path.isdir(target):
            return {"error": _err("path_missing")}
        try:
            if sys.platform.startswith("win"):
                os.startfile(target)  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", target])
            else:
                subprocess.Popen(["xdg-open", target])
            return {"ok": True}
        except OSError as e:
            return {"error": _friendly(e)}
