# Contributing

Thanks for your interest in Byte Exploder (by [AGlegend](https://github.com/AGlegendery)).

## Getting started

```bash
pip install -r requirements.txt
pip install pytest
QT_QPA_PLATFORM=offscreen pytest -q
```

## Guidelines

- Keep encode/decode **exactly reversible** — the roundtrip tests must stay green.
- Match the existing code style (standard library + numpy/PIL/PySide6).
- Add or update tests in `tests/` for any behavior change.
- Keep the author attribution intact (see [`LICENSE`](LICENSE) and [`AGENTS.md`](AGENTS.md)).

## Reporting bugs

Open an issue using the bug report template and include the Verbose log from the app.
