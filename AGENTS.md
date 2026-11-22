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

## Skills

Task playbooks live in **`.agents/skills/<name>/SKILL.md`** (the canonical location;
`.claude/skills` is a symlink to it, and `CLAUDE.md` is a symlink to this file).
Read the matching skill before starting one of these tasks:

| Skill | Use it to |
|---|---|
| [`run-checks`](.agents/skills/run-checks/SKILL.md) | Run and fix the CI checks (black, ruff, mypy, pytest) |
| [`add-mcp-tool`](.agents/skills/add-mcp-tool/SKILL.md) | Add or change a read-only MCP tool: SDK helper, tool, registration, tests, docs |
| [`bump-dependency`](.agents/skills/bump-dependency/SKILL.md) | Add or upgrade a dependency with uv (including the pinned `fastmcp`) |
| [`release`](.agents/skills/release/SKILL.md) | Decide if a release is needed, pick the version bump, cut and tag it |

New skills go in `.agents/skills/<name>/SKILL.md` with `name` and `description`
front matter. Edit `AGENTS.md`, never `CLAUDE.md`; don't replace the symlinks with copies.

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
- Commits/PRs: focused changes, Conventional Commit titles, fill in
  `.github/PULL_REQUEST_TEMPLATE.md` (including **Release impact**), and add user-facing
  `CHANGELOG.md` is generated by release-please — don't edit it.

## Versioning and releases

Semantic versioning, `X.Y.Z` = MAJOR.MINOR.PATCH, tagged `vX.Y.Z`:

- **No release** (`docs:`, `chore:`, `ci:`, `test:`, `style:`, `refactor:`, `build:`):
  non-code changes — docs, tests, scripts, CI, agent files, dev tooling. Changes only
  under `.agents/`, `.claude/`, `.github/`, `tests/` or `scripts/` never release.
- **Major (X)** (`feat!:` / `fix!:`): a breaking change for users — a tool or
  parameter removed or renamed, a tool's output shape changed, auth headers/error
  codes, env vars or routes changed, a Python version dropped.
- **Minor (Y)** (`feat:`): backward-compatible features — a new tool, optional
  parameter, `query_stats` metric, env var or output field.
- **Patch (Z)** (`fix:`, `perf:`, `deps:`, `revert:`): backward-compatible fixes,
  privacy/security fixes, runtime dependency bumps.

**PR titles must be Conventional Commits** (`feat:`, `fix:`, `deps:`, `docs:`,
`chore:`, `ci:`, `test:`, `refactor:`; add `!` for breaking, e.g. `feat!:`). PRs are
squash-merged, so the title is what the release pipeline reads; CI
(`pr-title.yml`) rejects other titles.

Releases are automated by **release-please** (`.github/workflows/release-please.yml`,
`release-please-config.json`): on each push to `main` it opens or updates a
`chore: release X.Y.Z` PR when `feat`/`fix`/`perf`/`deps`/`revert` changes are
pending; merging it tags `vX.Y.Z` and publishes the GitHub release with the
generated changelog. Never bump the version or edit `CHANGELOG.md` by hand. See the
`release` skill for choosing titles and fixing mistakes.

## Roadmap context

`PLAN-garmin-official-oauth.md` describes a possible move to Garmin's partner OAuth /
Health API. `GarminSource` in `sdk/client.py` is the intended swap point. Don't
implement that plan unless asked.
