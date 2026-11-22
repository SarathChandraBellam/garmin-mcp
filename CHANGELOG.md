# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- `AGENTS.md` with build/test commands, layout and hard rules for AI coding agents.
  `CLAUDE.md` is a symlink to it.
- Agent skills in `.agents/skills/` (`run-checks`, `add-mcp-tool`,
  `bump-dependency`, `release`); `.claude/skills` is a symlink to that directory.
- `.claude/settings.json` pre-approves the uv check commands, blocks reading
  `.env`/`.secrets/`, and installs dependencies at the start of Claude Code on the
  web sessions.
- Release guidance: semantic versioning rules and a release-impact section in the
  pull request template.

## [0.2.0] - 2026-11-22

### Added

- Product landing page at `/` with a guide to getting a Garmin Personal API key
  and client setup snippets. The JSON info that `/` used to return is now at `/info`.
- Settings in one place (`pydantic-settings`), including an optional
  `PUBLIC_BASE_URL` for the landing page.

### Changed

- The project now uses uv (`uv.lock`, dependency groups) and a `src/` layout split
  into `contracts/` (pydantic), `sdk/`, `tools/`, `auth/` and `web/`.
  `requirements.txt` is removed.
- Formatting moved from `ruff format` to black. Ruff is now used for linting only.
  CI and pre-commit run black, ruff, mypy and pytest through `uv run`.

## [0.1.0] - 2026-11-22

### Added

- Stateless MCP server built with FastMCP 2.x (Streamable HTTP,
  `stateless_http=True`, JSON responses, MCP spec 2025-06-18).
- Garmin Connect Personal API as the data source, with a bring-your-own-key
  model (`X-Garmin-Api-Key` or `Authorization: Bearer`, or `GARMIN_API_KEY`
  for stdio). The server stores no keys and no fitness data.
- Read-only tools: `get_profile`, `get_activities`, `get_activity`,
  `get_daily_summary`, `get_sleep`, `get_heart_rate`, `get_hrv`,
  `get_body_composition`, `get_spo2`, `get_fitness_age`,
  `get_heart_rate_zones`, `get_training_readiness`, and `query_stats`.
- Generic ASGI entry point (`garmin_mcp.asgi:app`) for self-hosting, and a
  plan for a later official Garmin OAuth / Health API source
  (`PLAN-garmin-official-oauth.md`).

[Unreleased]: https://github.com/SarathChandraBellam/garmin-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SarathChandraBellam/garmin-mcp/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/SarathChandraBellam/garmin-mcp/releases/tag/v0.1.0
