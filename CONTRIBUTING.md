# Contributing

Issues and pull requests are welcome.

1. Fork and clone the repository.
2. `uv venv --python 3.14 && uv pip install -r requirements_test.txt`
3. Run `pytest` and `ruff check .` before opening a PR.
4. Keep test fixtures anonymised – never commit real API keys, device EUIs or LoRa keys.
