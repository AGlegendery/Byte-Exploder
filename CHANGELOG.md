# Changelog

All notable changes to this project are documented here.

## [Unreleased]

### Added
- **New webview UI** (`app.py`, `web/`, `web_api.py`): replaces the Qt window. The
  page shows the input as pixels while you type or pick a file, then the scrambled
  image; long jobs run in the background with progress and cancel. Picking an image
  shows whether a key is hidden in it and auto-selects `<image>_key.json` next to it.
  The Qt UI was removed; the engine no longer depends on Qt.
- **English UI**: switch between Persian (RTL) and English (LTR) from the header; the
  choice is remembered. The app name stays "Byte Exploder" in both languages.
- "Allow empty text" option: encrypt an empty text box on purpose.
- **Photo-safe mode** (`photo_safe.py`): small inputs become an image of dark/light
  tiles that survives being sent as a compressed photo (tested down to JPEG quality 40
  and half size). Decrypting a normal image that was compressed now says so clearly.
- **First-run guide**: a tour of each part of the window, ending with the reminder to
  send images with "Send as Document"; reopen it from the Guide button.

### Changed (format)
- Images with an embedded key are now square: the key rows go below the image and a
  noise strip on the right keeps it square. Older tall images still decode; versions
  before this one can't read the new square ones (decode them with this version).
- **Text input**: encode typed/pasted text (stored as UTF-8, `input_is_text` in the
  key); decoding shows it in the Decrypt tab with copy / save buttons.
- Folder picker button; "Check key" also reads keys embedded in the image.
- **Embedded key**: optionally hide the key inside the image's pixel LSBs
  (via appended carrier rows) instead of a separate `.key` file. The key is not
  written to any metadata field, so it is not readable with `exiftool`/`strings`.
- `AGENTS.md` with attribution instructions for AI agents.
- Test suite (`tests/test_core.py`) and GitHub Actions CI.

### Fixed
- An embedded-key image could not be decoded with its backup `_key.json` (which the
  app fills in automatically after encrypting): "Image shape mismatch".
- Decoding with the wrong key silently wrote a garbage file; it is now rejected.
- Failed or cancelled runs no longer leave half-written output files behind.
- The wait cursor stayed overridden after a job; closing the window during a job
  crashed the app; previewing very large images froze the window.
- Without a key file, the save dialog now suggests the original file name.
- **Safe-mode decode** produced corrupted output. Two bugs were fixed:
  1. Bytes were written in block/tile order instead of whole-image row-major
     order. Decoding now rebuilds full rows band-by-band before writing.
  2. The block-chain hash was computed from an already-mutated block (the XOR
     helpers mutate in place). The encrypted bytes are now captured before
     decryption.

### Changed
- **Performance**: scrambling is vectorized per band of blocks and the PNG is
  written by a multi-threaded encoder (filter "Up", deflate level 1). A 300 MB
  file encodes in ~1.4 s instead of ~23 s, decodes in ~2.7 s instead of ~5.7 s
  (Safe Decode was ~5x slower still) with ~3x less peak RAM. Output pixels are
  identical, so images from earlier versions still decode and vice versa.
- Split the key-embedding logic into `key_embed.py`.
- Cleaned up and documented `exploder_core.py`; renamed the internal salt
  constant for clarity.
