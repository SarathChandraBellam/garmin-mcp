---
name: bump-dependency
description: Upgrade or add a Python dependency in garmin-mcp with uv, keep uv.lock in sync, and verify nothing broke. Use for Dependabot follow-ups, "upgrade fastmcp", "bump deps", or adding a new package.
---

# Bump or add a dependency

The project is managed with uv; CI installs with `uv sync --locked`, so
`pyproject.toml` and `uv.lock` must always agree.

## Add

```bash
uv add <pkg>            # runtime dependency
uv add --dev <pkg>      # dev tool (goes in [dependency-groups].dev)
```

Prefer the standard library or an existing dependency (httpx, pydantic,
pydantic-settings, starlette via fastmcp) before adding a package.

## Upgrade

- Most packages use `>=` lower bounds: `uv lock --upgrade-package <pkg>`, then
  raise the lower bound in `pyproject.toml` if the code now needs the new version.
- **`fastmcp` is pinned exactly** (`fastmcp==X.Y.Z`) because its server and
  HTTP-app APIs change between releases. To bump it, edit the pin in
  `pyproject.toml`, run `uv lock`, then check the places that use its API:
  `server.py` (`FastMCP(...)`, `http_app(...)`, `custom_route`, `run`),
  `tools/_context.py` (`get_http_headers`, `ToolError`) and
  `tools/__init__.py` (`mcp.tool(annotations=...)`).
- GitHub Actions versions live in `.github/workflows/ci.yml`; the uv-pre-commit
  `rev` in `.pre-commit-config.yaml` should track the uv version.

## Verify

1. `uv sync --locked`
2. Run the `run-checks` skill (black, ruff, mypy, pytest).
3. For an MCP/FastMCP upgrade, also start the HTTP server
   (`ALLOW_INSECURE_HTTP=1 uv run uvicorn garmin_mcp.asgi:app --port 18790`) and
   confirm `GET /healthz` returns `{"ok": true}` and `POST /mcp` without a key
   returns 401.
4. Add a `### Changed` entry under `## [Unreleased]` in `CHANGELOG.md` for runtime
   dependency changes. Commit `pyproject.toml` and `uv.lock` together.
