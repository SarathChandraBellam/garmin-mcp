# Contributing

Thanks for wanting to improve garmin-mcp. This document is the short path from
clone to a reviewable pull request.

## Development setup

```bash
git clone https://github.com/SarathChandraBellam/garmin-mcp.git
cd garmin-mcp
uv sync
uv run pre-commit install
```

## Checks (same as CI)

```bash
uv run black --check .
uv run ruff check .
uv run mypy
uv run pytest
```

`uv run black .` fixes formatting and `uv run ruff check --fix .` fixes the lint
issues that ruff can fix by itself. Add dependencies with `uv add <pkg>` (or
`uv add --dev <pkg>`) so `uv.lock` stays in sync. Unit tests mock Garmin and **do not**
need a Personal API key. Do not commit real keys, tokens, `.env` files, or
live activity/sleep samples — use synthetic fixtures only.

## Optional live end-to-end test

Against a running server and your own key (never commit the key file):

```bash
ALLOW_INSECURE_HTTP=1 uv run uvicorn garmin_mcp.asgi:app --port 18790
BASE=http://localhost:18790 GARMIN_KEY_FILE=/path/to/keyfile uv run scripts/e2e.py
```

Or `RUN_E2E=1 BASE=... GARMIN_KEY_FILE=... pytest -m e2e` once a live test is
collected that way. CI does not run this.

## Pull requests

1. Open an issue first for larger changes (new tools, auth model, data source).
2. Keep PRs focused; include tests for behaviour changes.
3. Follow the existing style (type hints, no secret logging).
4. Update `CHANGELOG.md` under `[Unreleased]` and docs if the public interface
   changes.
5. Use a [Conventional Commits](https://www.conventionalcommits.org) title
   (`feat:`, `fix:`, `docs:`, … with `!` for breaking changes) and fill in the pull
   request template, including **Release impact**. Don't bump the version in a
   feature PR; see "Versioning and releases" in [AGENTS.md](AGENTS.md).

By contributing you agree that your work is licensed under the MIT License
(see `LICENSE`).
