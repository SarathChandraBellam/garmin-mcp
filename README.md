# garmin-mcp

[![CI](https://github.com/SarathChandraBellam/garmin-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/SarathChandraBellam/garmin-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-2025--06--18-blue)](https://modelcontextprotocol.io)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)

A **stateless, bring-your-own-key** [Model Context Protocol](https://modelcontextprotocol.io)
server that lets an MCP client (Cursor, Claude, and others) read **your** Garmin
Connect data through Garmin's official **Personal API**.

The server never stores your key or your fitness data. Each request carries the
key, the server exchanges it for a short-lived Garmin token (held in memory only),
calls Garmin, returns the result, and forgets it.

## Why this exists

Garmin now offers a self-serve [Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api)
so individuals can access their own health and activity data with a key created
in Garmin Connect. This project wraps that API as an MCP server so you can ask
an assistant about sleep, training, or daily stats without standing up a
database or handing a password to a third party.

## Features

- Official Garmin Connect Personal API (no password login, no unofficial scraping)
- Multi-tenant: every client sends **its own** key; the deployment holds none
- Stateless Streamable HTTP (`stateless_http=True`, JSON responses, MCP 2025-06-18)
- Also runs locally over **stdio**
- Read-only tools for activities, daily summaries, sleep, heart rate, HRV, body
  composition, SpO2, and daily stat series
- HTTPS required in production; missing or invalid keys return **401**
- Coordinates and owner profile fields are stripped from activity output

## Security model

| The server stores | The client sends |
|---|---|
| Nothing durable. A Garmin bearer token may sit in memory on a warm instance, keyed by SHA-256 of the API key, and dies with the process. | Your Personal API key on every HTTP request (`X-Garmin-Api-Key` or `Authorization: Bearer`), or `GARMIN_API_KEY` for local stdio. |

Headers are never logged. Create, rotate, and revoke keys in Garmin Connect.

## Disclaimer

**This project is not affiliated with, endorsed by, or sponsored by Garmin Ltd.
or its subsidiaries.** "Garmin" and "Garmin Connect" are trademarks of Garmin.
The software talks to Garmin's [Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api)
on your behalf. By using it you agree to [Garmin's terms](https://www.garmin.com/legal/)
and the Personal API terms shown when you create a key. Use it only with a key
you are authorised to use (typically your own).

## Get a Garmin Personal API key

1. Sign in at [Personal API Key settings](https://connect.garmin.com/app/settings/personalApiToken) → **Create Key**.
2. Choose an expiry (30 / 90 / 180 / 365 days) and copy the key (it is shown once). Treat it like a password.
3. Revoke it on the same page at any time; tokens derived from it stop working.

## Quick start

### Hosted HTTP (any MCP client that supports a URL + headers)

Endpoint: `https://<DEPLOY_URL>/mcp`

```http
X-Garmin-Api-Key: <your key>
```

(`Authorization: Bearer <your key>` is also accepted.)

**Cursor** (`~/.cursor/mcp.json` or project `.cursor/mcp.json`):

```json
{
  "mcpServers": {
    "garmin": {
      "url": "https://<DEPLOY_URL>/mcp",
      "headers": { "X-Garmin-Api-Key": "${env:GARMIN_API_KEY}" }
    }
  }
}
```

**Claude Code:**

```bash
claude mcp add --transport http garmin https://<DEPLOY_URL>/mcp \
  --header "X-Garmin-Api-Key: $GARMIN_API_KEY"
```

**Claude Desktop** (`claude_desktop_config.json`, via `mcp-remote`):

```json
{
  "mcpServers": {
    "garmin": {
      "command": "npx",
      "args": [
        "-y", "mcp-remote", "https://<DEPLOY_URL>/mcp",
        "--header", "X-Garmin-Api-Key:${GARMIN_API_KEY}"
      ],
      "env": { "GARMIN_API_KEY": "<your key>" }
    }
  }
}
```

### Local stdio (no hosted server)

From a checkout:

```bash
pip install -e .
GARMIN_API_KEY=<your key> garmin-mcp
# or: GARMIN_API_KEY=<your key> fastmcp run garmin_mcp/server.py:mcp
```

**Cursor / Claude Desktop:**

```json
{
  "mcpServers": {
    "garmin": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/SarathChandraBellam/garmin-mcp", "garmin-mcp"],
      "env": { "GARMIN_API_KEY": "<your key>" }
    }
  }
}
```

`uvx --from git+…` needs git access to the repository (public, or an SSH/HTTPS
credential if it is still private). Otherwise install from a local clone and
point `command` at that environment's `garmin-mcp`.

## Tools (all read-only)

| Tool | Returns |
|---|---|
| `get_profile` | Profile settings (display name, units) — a quick key check |
| `get_activities` | Activities, newest first (optional date window, type filter, paging, `raw`) |
| `get_activity` | Full details for one activity |
| `get_daily_summary` | Steps, calories, heart rate, stress, Body Battery, intensity minutes, SpO2, respiration |
| `get_sleep` | Sleep stages, durations, and timing for a night |
| `get_heart_rate` | Resting / min / max / 7-day average (samples opt-in) |
| `get_hrv` | Overnight HRV summary |
| `get_body_composition` | Weight and body-composition entries in a date range |
| `get_spo2` | Pulse-ox and acclimation for a day |
| `get_fitness_age` | Fitness age and components |
| `get_heart_rate_zones` | Configured heart-rate zones |
| `get_training_readiness` | The Personal API has no Training Readiness endpoint; this returns its main inputs (HRV, sleep, Body Battery) |
| `query_stats` | Daily series for a whitelisted metric: `steps`, `stress`, `body_battery`, `sleep`, `hrv`, `weight`, `vo2max`, `hydration`, `daily_summaries`, `wellness_activities` (max 366 days; 31 for `daily_summaries`) |

Dates are `YYYY-MM-DD` in the user's local calendar (`DEFAULT_TIMEZONE`, default
`UTC`). Location coordinates and owner name/profile fields are removed
from activity output.

## Self-hosting

The HTTP server is a standard ASGI app at `garmin_mcp.asgi:app`. It needs no
environment variables (optional: `DEFAULT_TIMEZONE`, an IANA name; default
`UTC`). Serve it **only over HTTPS** in production. The app works
whether or not the host sends ASGI lifespan events.

```bash
pip install -e .
uvicorn garmin_mcp.asgi:app --host 0.0.0.0 --port 8000
```

Point MCP clients at `https://<your-host>/mcp` and send `X-Garmin-Api-Key`.
Any ASGI host that can run that module works (uvicorn, gunicorn with
Uvicorn workers, and so on). Docker is optional; a typical image just
installs the package and uses the same `uvicorn` command as the process.

## Development

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pre-commit install
ruff check . && ruff format --check . && mypy garmin_mcp && pytest
```

Unit tests mock Garmin and do not need a key. The optional live check is:

```bash
uvicorn garmin_mcp.asgi:app --port 18790
BASE=http://localhost:18790 GARMIN_KEY_FILE=/path/to/keyfile python scripts/e2e.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md). For a later move to Garmin's partner
OAuth / Health API, see [PLAN-garmin-official-oauth.md](PLAN-garmin-official-oauth.md).

## License

[MIT](LICENSE) © 2026 Sarath Chandra Bellam
