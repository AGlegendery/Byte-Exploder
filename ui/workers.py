# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
"""
Qt worker threads for the Qt UI (app_qt.py): run the exploder_core engine off
the GUI thread and report progress/log/result through signals.
"""

from threading import Event
from typing import Optional

from PySide6.QtCore import QThread, Signal

from exploder_core import decode_image, decode_to_bytes, encode_file, encode_text, read_embedded_key


class _TaskThread(QThread):
    """Runs `self.task(on_progress, on_log)` off the GUI thread."""

    progress = Signal(int)
    log = Signal(str)
    finished_ok = Signal(object)
    failed = Signal(str)
    cancelled = Signal()

    def __init__(self, cancel_event: Optional[Event] = None, parent=None):
        super().__init__(parent)
        self.cancel_event = cancel_event or Event()

    def request_cancel(self):
        if self.cancel_event:
            self.cancel_event.set()

    def task(self, on_progress, on_log):
        raise NotImplementedError

    def run(self):
        try:
            def on_log(msg: str):
                self.log.emit(str(msg))

            def on_progress(p: int):
                if self.cancel_event.is_set():
                    raise RuntimeError("CANCELLED")
                self.progress.emit(int(p))

            self.finished_ok.emit(self.task(on_progress, on_log))
        except Exception as e:
            if str(e) == "CANCELLED":
                self.cancelled.emit()
            else:
                self.failed.emit(str(e))


class EncryptThread(_TaskThread):
    """Encodes `input_path`, or `text` when it is given. Emits key_info."""

    def __init__(
        self,
        input_path: Optional[str],
        output_image_path: str,
        block_size: Optional[int],
        safe_mode: bool = False,
        embed_key: bool = False,
        cancel_event: Optional[Event] = None,
        parent=None,
        text: Optional[str] = None,
    ):
        super().__init__(cancel_event, parent)
        self.input_path = input_path
        self.output_image_path = output_image_path
        self.block_size = block_size
        self.safe_mode = bool(safe_mode)
        self.embed_key = bool(embed_key)
        self.text = text

    def task(self, on_progress, on_log):
        if self.text is not None:
            return encode_text(
                text=self.text,
                output_image_path=self.output_image_path,
                block_size=self.block_size,
                embed_key=self.embed_key,
                on_progress=on_progress,
                on_log=on_log,
            )
        return encode_file(
            input_path=self.input_path,
            output_image_path=self.output_image_path,
            block_size=self.block_size,
            safe_mode=self.safe_mode,
            embed_key=self.embed_key,
            on_progress=on_progress,
            on_log=on_log,
        )


class DecryptThread(_TaskThread):
    """Decodes to `output_file_path` and emits that path, or, when
    `output_file_path` is None, decodes in memory and emits the bytes."""

    def __init__(
        self,
        image_path: str,
        output_file_path: Optional[str],
        key_info: Optional[dict] = None,
        safe_mode: bool = False,
        cancel_event: Optional[Event] = None,
        parent=None,
    ):
        super().__init__(cancel_event, parent)
        self.image_path = image_path
        self.output_file_path = output_file_path
        self.key_info = key_info
        self.safe_mode = bool(safe_mode)

    def task(self, on_progress, on_log):
        if self.output_file_path is None:
            data, _ = decode_to_bytes(
                image_path=self.image_path,
                key_info=self.key_info,
                on_progress=on_progress,
                on_log=on_log,
            )
            return data
        decode_image(
            image_path=self.image_path,
            output_file_path=self.output_file_path,
            key_info=self.key_info,
            safe_mode=self.safe_mode,
            on_progress=on_progress,
            on_log=on_log,
        )
        return self.output_file_path


class InspectThread(_TaskThread):
    """Reads the key embedded in an image; emits key_info or None."""

    def __init__(self, image_path: str, parent=None):
        super().__init__(None, parent)
        self.image_path = image_path

    def task(self, on_progress, on_log):
        return read_embedded_key(self.image_path)
