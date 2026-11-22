# Contributing

Thanks for wanting to improve garmin-mcp. This document is the short path from
clone to a reviewable pull request.

## Development setup

```bash
git clone https://github.com/SarathChandraBellam/garmin-mcp.git
cd garmin-mcp
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
pre-commit install
```

## Checks (same as CI)

```bash
ruff check .
ruff format --check .
mypy garmin_mcp
pytest
```

`ruff format .` will fix formatting. Unit tests mock Garmin and **do not**
need a Personal API key. Do not commit real keys, tokens, `.env` files, or
live activity/sleep samples — use synthetic fixtures only.

## Optional live end-to-end test

Against a running server and your own key (never commit the key file):

```bash
uvicorn garmin_mcp.asgi:app --port 18790
BASE=http://localhost:18790 GARMIN_KEY_FILE=/path/to/keyfile python scripts/e2e.py
```

Or `RUN_E2E=1 BASE=... GARMIN_KEY_FILE=... pytest -m e2e` once a live test is
collected that way. CI does not run this.

## Pull requests

1. Open an issue first for larger changes (new tools, auth model, data source).
2. Keep PRs focused; include tests for behaviour changes.
3. Follow the existing style (type hints, no secret logging).
4. Update `CHANGELOG.md` under `[Unreleased]` and docs if the public interface
   changes.
5. Fill in the pull request template.

By contributing you agree that your work is licensed under the MIT License
(see `LICENSE`).
