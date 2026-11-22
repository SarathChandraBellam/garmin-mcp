# AGENTS.md

Guidance for AI coding agents (Claude Code, Codex, Cursor, Copilot, and others)
working in this repository. Humans should start with [README.md](README.md) and
[CONTRIBUTING.md](CONTRIBUTING.md); this file is the condensed, agent-oriented version.

## What this is

`garmin-mcp` is a **stateless, bring-your-own-key MCP server** (Python, FastMCP 4.x)
that exposes **read-only** tools over a caller's Garmin Connect data via Garmin's
official **Personal API**. Each HTTP request carries the caller's own key; the server
exchanges it for a short-lived bearer token (in-memory cache only), calls Garmin,
returns the result, and stores nothing.

## Setup and commands

The project uses [uv](https://docs.astral.sh/uv/) with a `src/` layout. Python 3.10+.

```bash
uv sync                    # install runtime + dev deps into .venv
uv run black --check .     # format check   (fix: uv run black .)
uv run ruff check .        # lint           (fix: uv run ruff check --fix .)
uv run mypy                # type check (src/garmin_mcp only)
uv run pytest              # unit tests; all Garmin HTTP is mocked
```

**Before you finish any change, run all four checks** — they are exactly what CI
runs (`.github/workflows/ci.yml`, Python 3.10 / 3.12 / 3.13). Run a single test with
`uv run pytest tests/test_server.py::test_name`.

Run the server locally:

```bash
GARMIN_API_KEY=<key> uv run garmin-mcp                                   # stdio
ALLOW_INSECURE_HTTP=1 uv run uvicorn garmin_mcp.asgi:app --port 18790   # HTTP
```

You almost never need a real key. Do not try to obtain one; `scripts/e2e.py` is an
opt-in live check for humans and is not part of CI.

## Layout

```
src/garmin_mcp/
  server.py      FastMCP instance, INSTRUCTIONS, ASGI `App` (lifespan-aware), stdio main()
  asgi.py        `garmin_mcp.asgi:app` entry point
  config.py      pydantic-settings; every env var lives here
  auth/          key extraction (keys.py), 401/502 key gate + HTTPS-only middleware
  sdk/           Garmin Personal API client (client.py), key→token exchange (token.py), errors
  contracts/     pydantic models: tool input types, output models, error bodies
  tools/         MCP tools; _context.py = per-call key/source/errors/dates, _sanitize.py = PII stripping
  web/           landing page (`/`), `/info`, `/healthz`; tool table rendered from ALL_TOOLS
tests/           pytest + respx; fixtures.py holds synthetic Garmin payloads
scripts/e2e.py   opt-in live end-to-end check (needs a real key; never in CI)
```

## Adding or changing a tool

1. Add a typed helper to `PersonalApi` in `src/garmin_mcp/sdk/client.py` if a new
   Garmin endpoint is needed. Tools must not call `httpx` directly.
2. Write the tool as a plain function in the right `src/garmin_mcp/tools/*.py` module:
   - get the client with `source()` and wrap Garmin calls in `call(...)` (maps SDK
     errors to `ToolError`);
   - use `DateStr` / `OptDate` from `contracts` for dates and `today()` / `shift()` /
     `check_range()` from `_context`;
   - pass output through `no_pii(...)` (and `strip_samples(...)` for large sample arrays);
   - return a `Note(...).model_dump()` when Garmin has no data rather than `None`;
   - the **docstring is the tool description** shown to MCP clients — keep it one
     clear line about what it returns.
3. Register it in `ALL_TOOLS` in `src/garmin_mcp/tools/__init__.py` (or the module's
   `TOOLS` tuple). Every tool is registered with the `READ_ONLY` annotations.
4. Add a test in `tests/` using `respx` to mock the Garmin endpoint and synthetic data
   from `tests/fixtures.py`.
5. Update the tools table in `README.md` and add an entry under `[Unreleased]` in
   `CHANGELOG.md`. The landing page picks the tool up automatically.

New environment variables go in `config.py` (`Settings`) and the README's
self-hosting table.

## Hard rules

- **Read-only.** No tool may write to Garmin. Keep the `READ_ONLY` annotations.
- **Stateless.** Do not add databases, files, or any durable storage of keys, tokens,
  or user data. The only cache is the in-memory token cache in `sdk/token.py`, keyed
  by a SHA-256 fingerprint of the key.
- **Never log or echo secrets.** No logging of headers, API keys, or tokens; error
  messages must not include them. `scripts/e2e.py` must never print the key.
- **Privacy.** Activity output must stay free of coordinates and owner profile fields
  (`PII_FIELDS` in `tools/_sanitize.py`). Extend that set rather than bypass it.
- **Auth semantics are contract.** Missing key → `401 missing_garmin_api_key`;
  rejected key → `401 invalid_garmin_api_key`; Garmin down → `502` (`429` on rate
  limit); non-HTTPS non-local host → `403 https_required`. Tests assert these.
- **No real data in the repo.** Tests and fixtures use synthetic payloads only. Never
  commit `.env`, `.secrets/`, key files, or live activity/sleep samples (gitleaks runs
  in pre-commit).
- **Dependencies** via `uv add <pkg>` / `uv add --dev <pkg>` so `uv.lock` stays in sync;
  CI installs with `uv sync --locked`. `fastmcp` is pinned exactly — bump it deliberately.

## Style

- black + ruff, line length 100, target py310. Use `from __future__ import annotations`
  and full type hints; `src/` must pass mypy.
- Keep modules small and focused; follow the existing patterns rather than adding
  abstraction layers.
- Commits/PRs: focused changes, fill in `.github/PULL_REQUEST_TEMPLATE.md`, update
  `CHANGELOG.md` when the public interface changes.

## Roadmap context

`PLAN-garmin-official-oauth.md` describes a possible move to Garmin's partner OAuth /
Health API. `GarminSource` in `sdk/client.py` is the intended swap point. Don't
implement that plan unless asked.
