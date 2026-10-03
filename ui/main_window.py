# Byte Exploder — By AGlegend (https://github.com/AGlegendery)
import os
from threading import Event

from PySide6.QtWidgets import (
    QMainWindow,
    QFileDialog,
    QMessageBox,
    QApplication,
    QTableWidgetItem,
    QCheckBox,
)
from PySide6.QtUiTools import QUiLoader
from PySide6.QtCore import QFile, Qt

from ui.workers import EncryptThread, DecryptThread, InspectThread
from exploder_core import save_key_info, load_key_info

# Decoding a PNG for the preview runs on the GUI thread; bigger images would
# freeze the window for seconds, so they only get the metadata table.
MAX_PREVIEW_SIZE = 150 * 1024 * 1024


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # ---------- Load UI ----------
        ui_path = os.path.join(os.path.dirname(__file__), "main.ui")
        loader = QUiLoader()
        f = QFile(ui_path)
        if not f.open(QFile.ReadOnly):
            raise RuntimeError(f"Cannot open UI file: {ui_path}")
        loaded = loader.load(f)
        f.close()
        if loaded is None:
            raise RuntimeError(f"Failed to load UI file: {ui_path}")

        self.setCentralWidget(loaded.centralWidget())
        self.setWindowTitle(
            (loaded.windowTitle() or "Byte Exploder") + "  —  By AGlegend"
        )
        self.resize(loaded.size())
        self.setMinimumSize(900, 650)

        # ---------- State ----------
        self.cancel_event = Event()
        self.worker = None
        self._busy_cursor = False
        self.cw = self.centralWidget()

        def get(name: str):
            w = self.cw.findChild(object, name)
            if w is None:
                raise RuntimeError(
                    f"Widget not found in UI: '{name}'. "
                    f"Set objectName exactly to: {name}"
                )
            return w

        # Header
        self.btn_cancel = get("btn_cancel")

        # Progress + logs
        self.progressBar = get("progressBar")
        self.te_verbose = get("te_verbose")

        # Encrypt tab
        self.rb_input_file = get("rb_input_file")
        self.rb_input_text = get("rb_input_text")
        self.le_input_file = get("le_input_file")
        self.btn_browse_file = get("btn_browse_file")
        self.btn_browse_folder = get("btn_browse_folder")
        self.te_input_text = get("te_input_text")
        self.btn_encrypt_file = get("btn_encrypt_file")
        self.cb_block_mode = get("cb_block_mode")
        self.sb_block_size = get("sb_block_size")
        self.cb_safe_encode = get("cb_safe_encode")
        self.btn_safe_encode_help = get("btn_safe_encode_help")
        self.cb_output_format = get("cb_output_format")

        # Decrypt tab
        self.le_image_file = get("le_image_file")
        self.btn_browse_image = get("btn_browse_image")
        self.le_key = get("le_key")
        self.btn_load_key = get("btn_load_key")
        self.btn_copy_key = get("btn_copy_key")
        self.btn_check_key = get("btn_check_key")
        self.btn_decrypt_image = get("btn_decrypt_image")
        self.cb_safe_decode = get("cb_safe_decode")
        self.btn_safe_decode_help = get("btn_safe_decode_help")
        self.gb_output_text = get("gb_output_text")
        self.te_output_text = get("te_output_text")
        self.btn_copy_text = get("btn_copy_text")
        self.btn_save_text = get("btn_save_text")

        # Preview tab
        self.lbl_preview = get("lbl_preview")
        self.table_metadata = get("table_metadata")

        # ---------- Add "Embed key in image" checkbox (programmatically) ----------
        self.cb_embed_key = QCheckBox("Embed key inside the image (hidden in pixels)")
        self.cb_embed_key.setToolTip(
            "Hide the key inside the image's pixels instead of a separate .key file.\n"
            "It is NOT stored in metadata, so it is not readable with exiftool/strings.\n"
            "A backup .key file is still saved next to the image."
        )
        try:
            # Insert the checkbox just above the Encrypt button.
            layout = self.btn_encrypt_file.parentWidget().layout()
            idx = layout.indexOf(self.btn_encrypt_file)
            layout.insertWidget(max(0, idx), self.cb_embed_key)
        except Exception:
            # If layout insertion fails, the checkbox simply won't show; encrypt
            # still works (defaults to not embedding).
            pass

        # ---------- Init UI ----------
        self.progressBar.setValue(0)
        self.btn_cancel.setEnabled(False)
        self.sb_block_size.setEnabled(False)
        self.gb_output_text.hide()

        # ---------- Connect signals ----------
        self.rb_input_text.toggled.connect(self.on_input_mode_changed)
        self.on_input_mode_changed()
        self.btn_browse_file.clicked.connect(self.pick_input_file)
        self.btn_browse_folder.clicked.connect(self.pick_input_folder)
        self.btn_encrypt_file.clicked.connect(self.start_encrypt)

        self.btn_browse_image.clicked.connect(self.pick_image_file)
        self.btn_load_key.clicked.connect(self.pick_key_file)
        self.btn_copy_key.clicked.connect(self.copy_key_path)
        self.btn_check_key.clicked.connect(self.check_key_file)
        self.btn_decrypt_image.clicked.connect(self.start_decrypt)
        self.btn_copy_text.clicked.connect(self.copy_output_text)
        self.btn_save_text.clicked.connect(self.save_output_text)

        self.btn_cancel.clicked.connect(self.cancel_current)

        self.btn_safe_encode_help.clicked.connect(self.show_safe_encode_help)
        self.btn_safe_decode_help.clicked.connect(self.show_safe_decode_help)

        self.cb_block_mode.currentTextChanged.connect(self.on_block_mode_changed)
        self.on_block_mode_changed(self.cb_block_mode.currentText())

        self.te_verbose.setStyleSheet(
            "QTextEdit { background-color:#111; color:#0f0; "
            "font-family:Consolas, monospace; font-size:11pt; }"
        )
        self.te_verbose.setReadOnly(True)

        # Startup credit banner (required attribution).
        self.log("Byte Exploder — By AGlegend (https://github.com/AGlegendery)")

    # -------------------- UI helpers --------------------
    def log(self, text: str):
        self.te_verbose.append(str(text))

    def clear_log(self):
        self.te_verbose.clear()

    def set_progress(self, p: int):
        self.progressBar.setValue(max(0, min(100, int(p))))

    def set_busy(self, busy: bool):
        for w in (
            self.btn_encrypt_file, self.btn_decrypt_image, self.btn_browse_file,
            self.btn_browse_folder, self.rb_input_file, self.rb_input_text,
            self.te_input_text, self.btn_browse_image, self.btn_load_key,
            self.btn_check_key, self.btn_copy_key, self.cb_block_mode,
            self.cb_safe_encode, self.cb_output_format, self.cb_safe_decode,
            self.btn_safe_encode_help, self.btn_safe_decode_help, self.cb_embed_key,
        ):
            w.setEnabled(not busy)
        self.sb_block_size.setEnabled(
            (not busy) and (self.cb_block_mode.currentText().lower() == "manual")
        )
        self.btn_cancel.setEnabled(busy)
        # The override cursor is a stack: push once, pop once.
        if busy and not self._busy_cursor:
            QApplication.setOverrideCursor(Qt.WaitCursor)
            self._busy_cursor = True
        elif not busy and self._busy_cursor:
            QApplication.restoreOverrideCursor()
            self._busy_cursor = False

    def start_worker(self, th, on_done):
        self.set_progress(0)
        self.cancel_event.clear()
        self.set_busy(True)
        self.worker = th
        th.log.connect(self.log)
        th.progress.connect(self.set_progress)
        th.finished_ok.connect(on_done)
        th.failed.connect(self.worker_failed)
        th.cancelled.connect(self.worker_cancelled)
        th.start()

    # -------------------- Input mode --------------------
    def on_input_mode_changed(self, *_):
        text_mode = self.rb_input_text.isChecked()
        for w in (self.le_input_file, self.btn_browse_file, self.btn_browse_folder):
            w.setVisible(not text_mode)
        self.te_input_text.setVisible(text_mode)

    # -------------------- Block mode --------------------
    def on_block_mode_changed(self, text: str):
        self.sb_block_size.setEnabled(str(text).lower() == "manual")

    def get_selected_block_size(self):
        if self.cb_block_mode.currentText().lower() == "manual":
            return int(self.sb_block_size.value())
        return None

    # -------------------- File pickers --------------------
    def pick_input_file(self):
        path, _ = QFileDialog.getOpenFileName(self, "Select a file")
        if path:
            self.le_input_file.setText(path)

    def pick_input_folder(self):
        path = QFileDialog.getExistingDirectory(self, "Select a folder")
        if path:
            self.le_input_file.setText(path)

    def pick_image_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select image",
            filter="PNG (*.png);;EXPLD (*.expld);;All (*.*)"
        )
        if path:
            self.le_image_file.setText(path)
            self.show_preview(path)

    def pick_key_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select key file", filter="JSON (*.json);;All (*.*)"
        )
        if path:
            self.le_key.setText(path)

    # -------------------- Safe mode help --------------------
    def show_safe_encode_help(self):
        QMessageBox.information(
            self, "Safe Encode",
            "Encoding always streams the input and scrambles the image one band "
            "at a time, so it holds about one copy of the output image in RAM.\n\n"
            "- Safe mode additionally checks free RAM first: if the image alone "
            "needs more than 1/4 of free RAM, it stops instead of risking a "
            "crash.\n\n"
            "Note: very large files also produce very large PNGs."
        )

    def show_safe_decode_help(self):
        QMessageBox.information(
            self, "Safe Decode",
            "Decoding always processes the image one band at a time.\n\n"
            "- Safe mode additionally checks free RAM first: if the decoded "
            "image needs more than 1/4 of free RAM, it stops."
        )

    # -------------------- Cancel / close --------------------
    def cancel_current(self):
        if self.worker and self.worker.isRunning():
            self.cancel_event.set()
            if hasattr(self.worker, "request_cancel"):
                self.worker.request_cancel()
            self.log("[!] Cancel requested...")

    def closeEvent(self, event):
        # Destroying a QThread that is still running crashes the app.
        if self.worker is not None and self.worker.isRunning():
            answer = QMessageBox.question(
                self, "Exit", "An operation is still running. Cancel it and exit?"
            )
            if answer != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.blockSignals(True)
            self.cancel_current()
            self.worker.wait()
        event.accept()

    # -------------------- Preview + metadata --------------------
    def show_preview(self, img_path: str):
        from PySide6.QtGui import QImageReader, QPixmap
        from PySide6.QtCore import QSize

        try:
            file_size = os.path.getsize(img_path)
        except Exception:
            self.lbl_preview.setText("Image preview")
            return

        if file_size > MAX_PREVIEW_SIZE:
            self.lbl_preview.setText(
                f"Preview skipped for large images ({file_size / 1024 / 1024:,.0f} MB)"
            )
            self.lbl_preview.setAlignment(Qt.AlignCenter)
        else:
            reader = QImageReader(img_path)
            reader.setScaledSize(QSize(420, 420))
            image = reader.read()

            if image.isNull():
                try:
                    from PIL import Image
                    from PIL.ImageQt import ImageQt
                    im = Image.open(img_path)
                    im.draft("RGBA", (420, 420))
                    im.thumbnail((420, 420))
                    pix = QPixmap.fromImage(ImageQt(im.convert("RGBA")))
                except Exception:
                    self.lbl_preview.setText("Image preview")
                    return
            else:
                pix = QPixmap.fromImage(image)

            self.lbl_preview.setPixmap(
                pix.scaled(420, 420, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )

        try:
            from PIL import Image
            with Image.open(img_path) as img:
                info = [
                    ("File name", os.path.basename(img_path)),
                    ("Format", img.format),
                    ("Dimensions", f"{img.width} x {img.height}"),
                    ("Mode", img.mode),
                    ("Size", f"{file_size:,} bytes"),
                ]
            self.table_metadata.setRowCount(len(info))
            self.table_metadata.setColumnCount(2)
            for r, (k, v) in enumerate(info):
                it1 = QTableWidgetItem(str(k))
                it2 = QTableWidgetItem(str(v))
                it1.setFlags(it1.flags() & ~Qt.ItemIsEditable)
                it2.setFlags(it2.flags() & ~Qt.ItemIsEditable)
                self.table_metadata.setItem(r, 0, it1)
                self.table_metadata.setItem(r, 1, it2)
            self.table_metadata.resizeColumnsToContents()
        except Exception:
            pass

    # -------------------- Key actions --------------------
    def copy_key_path(self):
        kp = self.le_key.text().strip()
        if not kp:
            QMessageBox.information(self, "Info", "Key path is empty.")
            return
        QApplication.clipboard().setText(kp)
        self.log("[OK] Key path copied.")

    def check_key_file(self):
        kp = self.le_key.text().strip()
        if kp and os.path.exists(kp):
            try:
                key_info = load_key_info(kp)
            except Exception:
                QMessageBox.critical(self, "Error", "Key is invalid.")
                return
            self.show_key_info(key_info, "Key file")
            return

        # No key file: look for a key embedded in the selected image.
        img_path = self.le_image_file.text().strip()
        if not img_path or not os.path.exists(img_path):
            QMessageBox.warning(
                self, "Warning",
                "Key file is not valid. Select a key file, or an image with an embedded key."
            )
            return
        self.log("[i] Reading the key embedded in the image...")
        self.start_worker(InspectThread(img_path, parent=self), self.embedded_key_checked)

    def embedded_key_checked(self, key_info):
        self.set_busy(False)
        if key_info is None:
            QMessageBox.warning(self, "Warning", "This image has no embedded key.")
            return
        self.show_key_info(key_info, "Embedded in image")

    def show_key_info(self, key_info: dict, source: str):
        if key_info.get("input_is_text"):
            content = "Text"
        elif key_info.get("input_is_folder"):
            content = f"Folder ({key_info.get('folder_name')})"
        else:
            content = "File"
        file_size = key_info.get("file_size", None)
        size_str = f"{file_size:,} bytes" if isinstance(file_size, int) else "Unknown"
        QMessageBox.information(
            self, "Key info",
            "Key is valid.\n\n"
            f"Source: {source}\n"
            f"Content: {content}\n"
            f"File name: {key_info.get('file_name', 'Unknown')}\n"
            f"File size: {size_str}\n"
            f"Block size: {key_info.get('block_size', 'Unknown')}\n"
            f"Version: {key_info.get('version', 'Unknown')}"
        )

    # -------------------- Encrypt flow --------------------
    def start_encrypt(self):
        text = None
        in_path = None
        if self.rb_input_text.isChecked():
            text = self.te_input_text.toPlainText()
            if not text:
                QMessageBox.critical(self, "Error", "Text is empty.")
                return
        else:
            in_path = self.le_input_file.text().strip()
            if not in_path or not os.path.exists(in_path):
                QMessageBox.critical(self, "Error", "Input file is not valid.")
                return

        fmt = str(self.cb_output_format.currentText() or "PNG").lower()
        default_ext = ".expld" if "expld" in fmt else ".png"
        if text is not None:
            default_name = os.path.join(os.path.expanduser("~"), "text_ENC" + default_ext)
        else:
            default_name = os.path.splitext(in_path)[0] + "_ENC" + default_ext

        out_path, _ = QFileDialog.getSaveFileName(
            self, "Save output", default_name, "PNG (*.png);;EXPLD (*.expld)"
        )
        if not out_path:
            return
        if not out_path.lower().endswith((".png", ".expld")):
            out_path += default_ext

        self.clear_log()
        th = EncryptThread(
            input_path=in_path,
            output_image_path=out_path,
            block_size=self.get_selected_block_size(),
            safe_mode=bool(self.cb_safe_encode.isChecked()),
            embed_key=bool(self.cb_embed_key.isChecked()),
            cancel_event=self.cancel_event,
            parent=self,
            text=text,
        )
        self.start_worker(th, lambda key_info: self.encrypt_done(key_info, out_path))

    def encrypt_done(self, key_info: dict, out_img_path: str):
        self.set_busy(False)
        self.set_progress(100)

        key_path = os.path.splitext(out_img_path)[0] + "_key.json"
        try:
            save_key_info(key_info, key_path)
            self.le_key.setText(key_path)
            self.log(f"[OK] Key saved: {key_path}")
        except Exception as e:
            self.log(f"[!] Failed to save key: {e}")

        self.show_preview(out_img_path)

        if key_info.get("key_embedded"):
            QMessageBox.information(
                self, "Done",
                "Encryption done.\n\n"
                "The key is embedded inside the image (hidden in pixels), so you "
                "can decrypt it without the .key file.\n"
                "A backup .key file was also saved next to the image."
            )
        else:
            QMessageBox.information(self, "Done", "Encryption done.")

    # -------------------- Decrypt flow --------------------
    def start_decrypt(self):
        img_path = self.le_image_file.text().strip()
        key_path = self.le_key.text().strip()

        if not img_path or not os.path.exists(img_path):
            QMessageBox.critical(self, "Error", "Image is not valid.")
            return

        self.clear_log()
        if key_path and os.path.exists(key_path):
            try:
                key_info = load_key_info(key_path)
            except Exception:
                QMessageBox.critical(self, "Error", "Key is invalid.")
                return
            self.decrypt_with_key(img_path, key_info)
            return

        # No key file: read the key embedded in the image first, so we know the
        # original file name (or that it is text) before asking where to save.
        self.log("[i] No key file selected; reading the key embedded in the image...")
        self.start_worker(
            InspectThread(img_path, parent=self),
            lambda key_info: self.embedded_key_ready(img_path, key_info),
        )

    def embedded_key_ready(self, img_path: str, key_info):
        self.set_busy(False)
        if key_info is None:
            QMessageBox.critical(
                self, "Error",
                "No key file was selected and the image has no embedded key."
            )
            return
        self.log("[OK] Embedded key found.")
        self.decrypt_with_key(img_path, key_info)

    def decrypt_with_key(self, img_path: str, key_info: dict):
        if key_info.get("input_is_text"):
            out_path = None  # decode in memory and show the text
        else:
            original_name = key_info.get("file_name")
            if not original_name:
                original_name = "restored" + (key_info.get("file_ext") or ".bin")
            out_path, _ = QFileDialog.getSaveFileName(
                self, "Save output",
                os.path.join(os.path.dirname(img_path), original_name), "All (*.*)"
            )
            if not out_path:
                return

        th = DecryptThread(
            image_path=img_path,
            output_file_path=out_path,
            key_info=key_info,
            safe_mode=bool(self.cb_safe_decode.isChecked()),
            cancel_event=self.cancel_event,
            parent=self,
        )
        self.start_worker(th, self.decrypt_done)

    def decrypt_done(self, result):
        self.set_busy(False)
        self.set_progress(100)
        if isinstance(result, (bytes, bytearray)):
            text = bytes(result).decode("utf-8", errors="replace")
            self.te_output_text.setPlainText(text)
            self.gb_output_text.show()
            self.log(f"[OK] Text decoded ({len(text):,} characters).")
            return
        QMessageBox.information(self, "Done", f"Decryption done.\n\n{result}")

    # -------------------- Decoded text --------------------
    def copy_output_text(self):
        QApplication.clipboard().setText(self.te_output_text.toPlainText())
        self.log("[OK] Text copied.")

    def save_output_text(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save text", "text.txt", "Text (*.txt);;All (*.*)"
        )
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(self.te_output_text.toPlainText())
            self.log(f"[OK] Text saved: {path}")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Could not save the text:\n{e}")

    # -------------------- Worker common --------------------
    def worker_failed(self, msg: str):
        self.set_busy(False)
        QMessageBox.critical(self, "Error", str(msg))

    def worker_cancelled(self):
        self.set_busy(False)
        QMessageBox.information(self, "Cancelled", "Operation cancelled.")
