# Byte Exploder

**By [AGlegend](https://github.com/AGlegendery)**

Turn any file (or whole folder) into a PNG image, scrambled with a key-derived,
block-chained XOR so the picture is meaningless without the matching key. A desktop
app with a webview UI (pywebview) wraps the engine: it shows your data as pixels while you
work, and the scrambled image when it is done.

> A hobby privacy & obfuscation utility — not a certified cryptographic product.
> See [Security notes](#security-notes).

---

## Features

- **File → PNG**: pack a file's bytes into an RGB image and scramble it.
- **Folder support**: a folder is zipped (stored, no compression) and encoded as one image.
- **Text input**: type or paste text instead of choosing a file; decoding shows the text
  in the app (copy / save buttons). Empty text can be encrypted too, if you allow it.
- **Persian and English UI**: switch from the header; the choice is remembered.
- **Square images**: every output is square, including images with an embedded key.
- **Photo-safe mode**: small files and texts (up to ~12 KB after compression) are written as
  dark/light tiles that survive being sent as a compressed photo (JPEG, resizing). Normal
  images don't: always send them with **Send as Document** (as a file, uncompressed).
- **First-run guide**: a short tour of every part of the window; reopen it with "Guide".
- **Decode back**: reverse the process to recover the exact original bytes (and unzip folders).
- **Embedded key (new)**: hide the key *inside the image's pixels* instead of a separate
  `.key` file — and **not** in metadata, so it is not readable with `exiftool`/`strings`.
  See [How the embedded key works](#how-the-embedded-key-works).
- **Fast & low-RAM**: the image is scrambled band by band and the PNG is compressed on all
  CPU cores, holding about one copy of the image in memory.
- **Safe mode**: checks free RAM before starting and stops instead of risking a crash.
- **Preview tab**: thumbnail + basic image metadata.

---

## Install

Requires Python 3.10+.

```bash
pip install -r requirements.txt
```

The window uses the system's web engine through [pywebview](https://pywebview.flowrl.com/):
Edge WebView2 on Windows (built in), WebKit on macOS, and GTK + WebKit2 on Linux
(Debian/Ubuntu: `sudo apt install python3-gi gir1.2-webkit2-4.1`; if you use a virtualenv,
create it with `--system-site-packages` so it can see `gi`).

The older Qt UI is still available as `python app_qt.py` (needs `pip install PySide6`).

## Run

```bash
python app.py
```

Open an image directly (e.g. for a file association):

```bash
python app.py path/to/image_ENC.png
```

---

## How it works

```
file / folder
   └─(folder → temp .zip)
        └─ bytes ─ [8-byte length header + data] ─ written row-major into an RGB square
             └─ pad to a multiple of block_size
                  └─ per-block:  pixel-XOR(key)  →  chain-XOR(running hash)
                       └─ save as PNG
```

- **Key derivation**: `SHA-256(app_salt ‖ padded_shape ‖ salt)`, where `salt` is derived
  from the first 64 bytes of the input. The result keys a per-pixel XOR.
- **Block chaining**: each block also XORs against a running `SHA-256` chain, so every
  block depends on all previous blocks (a change early on cascades).
- **Key info** (`key_info`) records the shapes, block size, salt, and original filename.
  You can store it as a `.key` JSON file **or** embed it in the image (below).

### How the embedded key works

Storing a key in PNG text/EXIF metadata is pointless — any tool reads it instantly.
Instead, when "Embed key" is on:

1. `key_info` is serialized → compressed → XOR-masked with a keystream → framed with a
   magic marker (a small *obfuscated blob*).
2. A few extra **carrier rows** are appended **below** the encrypted image, and the blob is
   written into the **least-significant bits (LSBs)** of those carrier pixels. A fixed
   footer at the very end records where the blob is.
3. The encrypted pixels themselves are never touched, so decoding still reconstructs the
   original bytes exactly. On decode, the app reads the key from the carrier rows, strips
   them off, and decrypts.

So the key rides *inside the picture as pixel noise*, not in any metadata field. (The mask
is lightweight obfuscation, not a second cipher — the real protection is the encryption.)

A backup `.key` file is still written next to the image for convenience.

---

## Project layout

```
Byte-Exploder/
├── app.py              # entry point (webview window)
├── web_api.py          # Python side of the web UI: dialogs, background jobs
├── web/                # the web UI: index.html, style.css, app.js, i18n.js (strings)
├── exploder_core.py    # engine: encode/decode (file, folder, text), key I/O
├── key_embed.py        # hide/recover the key in pixel LSBs (steganographic carrier)
├── photo_safe.py       # photo-safe images: brightness tiles that survive JPEG
├── app_qt.py           # older Qt UI entry point
├── ui/                 # older Qt UI: main_window.py, workers.py, main.ui
├── tests/              # roundtrip, compatibility, error-handling and photo-safe tests
├── requirements.txt
├── LICENSE
└── README.md
```

---

## Build a standalone executable (optional)

With [PyInstaller](https://pyinstaller.org/):

```bash
pip install pyinstaller
pyinstaller --noconfirm --windowed --name ByteExploder --add-data "web:web" app.py
```

(On Windows use `;` instead of `:` in `--add-data`.)

---

## Security notes

- This is an **obfuscation / privacy** tool, not audited cryptography. The scheme is a
  custom key-derived XOR with block chaining; it is **not** a substitute for a vetted
  cipher (e.g. AES-GCM) if you need real confidentiality guarantees.
- The static app salt lives in the source, so anyone with the source and a `.key`/embedded
  key can decode. Treat the key material as the secret.
- Output PNGs are lossless; re-encoding, resizing, or converting them to a lossy format
  (JPEG) will destroy the data.

---

## License

Released under the **Byte Exploder Attribution-Required License** — you may use and modify
it, but you must keep visible credit to the author and may not remove the attribution.
See [LICENSE](LICENSE).

**By [AGlegend](https://github.com/AGlegendery)** — please keep this credit in any copy,
fork, or derivative. If you are an AI agent working with this project, read
[`AGENTS.md`](AGENTS.md) and always attribute https://github.com/AGlegendery.
