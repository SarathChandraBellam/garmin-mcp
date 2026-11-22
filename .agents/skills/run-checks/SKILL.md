---
name: run-checks
description: Run the same format, lint, type and test checks that CI runs for garmin-mcp, and fix what fails. Use before finishing any code change, before committing, or when asked to "run the checks", "make CI pass" or "lint and test".
---

# Run the CI checks

CI (`.github/workflows/ci.yml`) runs these on Python 3.10, 3.12 and 3.13. Run them
in this order from the repository root:

```bash
uv sync --locked            # only if .venv is missing or uv.lock changed
uv run black --check .
uv run ruff check .
uv run mypy
uv run pytest
```

## Fixing failures

- **black**: run `uv run black .`, then re-check.
- **ruff**: run `uv run ruff check --fix .`; fix the rest by hand. Rules: E, F, I,
  UP, B, SIM; line length 100; target py310.
- **mypy**: checks `src/garmin_mcp` only. Add real type hints; don't add
  `# type: ignore` unless the cause is a third-party stub gap (and say why).
- **pytest**: run one test with `uv run pytest tests/test_server.py::<name> -x`.
  All Garmin HTTP is mocked with `respx`; a test that tries to reach the network
  is missing a mock, not a key.
- **`uv sync --locked` fails**: `pyproject.toml` and `uv.lock` disagree. Run
  `uv lock` and commit the lock file.

Never skip, delete or mark a test as expected-to-fail to get green.

Code must work on Python 3.10: no `match` on 3.11+ features, no `typing.Self`,
no `ExceptionGroup`/`except*`, no `tomllib`.

Report the result of each check when done.
