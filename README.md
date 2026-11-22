# garmin-mcp

[![CI](https://github.com/SarathChandraBellam/garmin-mcp/actions/workflows/ci.yml/badge.svg)](https://github.com/SarathChandraBellam/garmin-mcp/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-2025--06--18-blue)](https://modelcontextprotocol.io)
[![uv](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/uv/main/assets/badge/v0.json)](https://github.com/astral-sh/uv)
[![Python 3.10+](https://img.shields.io/badge/python-3.10%2B-blue.svg)](https://www.python.org)

A **stateless, bring-your-own-key** [Model Context Protocol](https://modelcontextprotocol.io)
server that lets an MCP client (Cursor, Claude, and others) read **your** Garmin
Connect data through Garmin's official **Personal API**.

The server never stores your key or your fitness data. Each request carries the
key (like a GitHub personal access token), the server exchanges it for a
short-lived Garmin token (held in memory only), calls Garmin, returns the result,
and forgets it.

## Why this exists

Garmin now offers a self-serve [Personal API](https://developer.garmin.com/gc-developer-program/personal/personal-api)
so individuals can access their own health and activity data with a key created
in Garmin Connect. This project wraps that API as an MCP server so you can ask
an assistant about sleep, training, or daily stats without standing up a
database or handing a password to a third party.

## Features

- Official Garmin Connect Personal API (no password login, no unofficial scraping)
- Multi-tenant: every client sends **its own** key; the deployment holds none
- MCP endpoint at **`/mcp`**; product page with an API-key guide at **`/`**
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

A missing key returns `401 missing_garmin_api_key`, and a key Garmin rejects
returns `401 invalid_garmin_api_key`. If Garmin is unreachable the server
returns `502` (or `429` when Garmin rate-limits). Headers are never logged.
Create, rotate, and revoke keys in Garmin Connect.

**Limitation:** there is no OAuth sign-in, so clients that can't send a custom
header (Claude.ai on the web and mobile, for example) can't connect yet. Adding
OAuth later is sketched in [PLAN-garmin-official-oauth.md](PLAN-garmin-official-oauth.md).

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

### Hosted HTTP

Endpoint: `https://<DEPLOY_URL>/mcp`. Open `https://<DEPLOY_URL>/` for the
API-key guide and copy-ready snippets.

```http
X-Garmin-Api-Key: <your key>
```

(`Authorization: Bearer <your key>` is also accepted.)

**Cursor** (`~/.cursor/mcp.json`):

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
uv sync
GARMIN_API_KEY=<your key> uv run garmin-mcp
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
use `"command": "uv", "args": ["--directory", "/path/to/garmin-mcp", "run", "garmin-mcp"]`.

## Tools (all read-only)

| Tool | Returns |
|---|---|
| `get_profile` | Profile settings (display name, units) — a quick key check |
| `get_activities` | `{count, activities, note}`: recorded activities, newest first (optional date window, type filter, paging, `raw`) |
| `get_activity` | Full details for one activity (location name, coordinates and owner/device ids removed) |
| `get_daily_summary` | Steps, calories, heart rate, stress, Body Battery, intensity minutes, SpO2, respiration; `partial: true` while the day is in progress |
| `get_sleep` | Sleep stages, durations, and timing for the night ending on the date (wake-up date) |
| `get_heart_rate` | Resting / min / max / 7-day average (samples opt-in) |
| `get_hrv` | Overnight HRV summary |
| `get_body_composition` | Weight and body-composition entries in a date range (grams; see `units`) |
| `get_spo2` | Pulse-ox and acclimation for a day |
| `get_fitness_age` | Fitness age and components |
| `get_heart_rate_zones` | Configured heart-rate zones |
| `get_training_readiness` | The Personal API has no Training Readiness endpoint; this returns its main inputs (HRV, sleep, Body Battery). Long sample arrays opt-in with `include_samples` |
| `query_stats` | Daily series for a whitelisted metric: `steps`, `stress`, `body_battery`, `sleep`, `hrv`, `weight`, `vo2max`, `hydration`, `daily_summaries`, `wellness_activities` (max 366 inclusive days; 31 for `daily_summaries`). One entry per requested date; compact unless `raw` |

Dates are `YYYY-MM-DD` in the user's local calendar (`DEFAULT_TIMEZONE`, default
`UTC`). Location names, coordinates, and owner/profile/device identifiers are
removed from activity output.

### `query_stats` contract

Date ranges count **inclusive** days: `2026-01-01`..`2026-01-31` is 31 days. Garmin
rejects some metrics above a smaller window (HTTP 400), so the server splits long
requests into chunks no larger than Garmin accepts and merges the results:

| Metric | Max range | Garmin limit per call (chunk size) |
|---|---|---|
| `steps`, `stress` | 366 days | 28 days |
| `body_battery`, `hydration`, `sleep` | 366 days | 31 days |
| `daily_summaries` | 31 days | 31 days |
| `hrv`, `weight`, `vo2max`, `wellness_activities` | 366 days | one call |

Every response is an object, never an empty result:

```json
{
  "metric": "steps", "start_date": "2026-01-01", "end_date": "2026-01-03", "days": 3,
  "status": "ok", "days_with_data": 1, "units": {"totalSteps": "steps"}, "notes": [],
  "data": [
    {"calendarDate": "2026-01-01", "missing": true},
    {"calendarDate": "2026-01-02", "values": {"totalSteps": 8000}, "missing": false},
    {"calendarDate": "2026-01-03", "missing": true, "partial": true}
  ],
  "outside_range": []
}
```

- **Gaps:** every requested date has at least one entry in `data`; dates with no
  Garmin record are `{"calendarDate": ..., "missing": true}`, for every metric.
- **Empty:** `status: "empty"` means Garmin returned no records for the window. It
  does not mean the metric is unsupported (hydration, for example, only exists when
  logged; VO2 max only after qualifying activities).
- **Partial:** today's entry has `partial: true`; totals are still growing.
- **Outside the window:** records Garmin adds for other dates (the nearest weigh-ins
  around a `weight` window, a `sleep` night that ends after `end_date`) go in
  `outside_range`.
- **Compact by default:** nested event lists and heavy descriptor objects are
  replaced by a placeholder. Pass `raw: true` for Garmin's full records.
- **Stress:** the `stress` series has no "uncategorized" bucket, which is often a
  large share of the day. `daily_summaries[].stress.uncategorizedProportion` has it.
- **Steps** in `daily_summaries` are under `movement.steps.value`.

### Units and timestamps

Garmin values keep their native units whatever the profile's `measurementSystem`:

| Data | Unit |
|---|---|
| Weight, `minWeight`, `maxWeight`, bone / muscle mass | grams (`81200` = 81.2 kg) |
| Distances | meters |
| Sleep and stress durations (`*Seconds`, `*Duration`) | seconds |
| `*InMillis` fields | milliseconds |
| HRV values | milliseconds |
| VO2 max | ml/kg/min |
| Hydration | milliliters |

- `*TimestampGMT` / `*TimeGMT` are true UTC (Unix epoch milliseconds when numeric).
- `*TimestampLocal` / `*TimeLocal` are local wall-clock time encoded *as if* it were
  UTC. Read the number as UTC to get the local clock time; do not apply a time zone.
- `wellnessChronology` timestamps in daily summaries are ISO-8601 strings without
  an offset.
- Sleep `calendarDate` is the local date you **woke up**.
- Daily intensity minutes are tracked all day. They do not mean a recorded
  activity exists, so `get_activities` can be empty on a day with intensity minutes.

## Self-hosting

The HTTP server is a standard ASGI app at `garmin_mcp.asgi:app`. Serve it **only
over HTTPS** in production. The app works whether or not the host sends ASGI
lifespan events.

```bash
uv sync --no-dev
uv run uvicorn garmin_mcp.asgi:app --host 0.0.0.0 --port 8000 --proxy-headers
```

| Variable | Default | Purpose |
|---|---|---|
| `PUBLIC_BASE_URL` | the request's origin | Public origin shown in the landing-page snippets. Set it if your proxy rewrites the host. |
| `DEFAULT_TIMEZONE` | `UTC` | IANA zone used to decide what "today" means (default dates and the `partial` flag). Set it to your zone: with the `UTC` default, "today" lags users ahead of UTC around local midnight. |
| `ALLOW_INSECURE_HTTP` | unset | `1` turns off the HTTPS-only gate. Use it only for local development. |
| `GARMIN_API_KEY` | unset | Used only in stdio mode. |

Routes: `/` (product page and API-key guide), `/mcp` (MCP Streamable HTTP),
`/info` (JSON) and `/healthz`.

## Project layout

```
src/garmin_mcp/
  config.py        pydantic-settings: every environment variable in one place
  server.py        FastMCP instance, ASGI App, stdio main()
  contracts/       pydantic models: tool inputs/outputs and error bodies
  sdk/             Garmin Personal API client, key→token exchange, errors
  tools/           MCP tools (profile, activities, wellness, stats) + sanitising
  auth/            API-key extraction, key gate (401/502) and HTTPS-only middleware
  web/             landing page template
```

## Development

The project uses [uv](https://docs.astral.sh/uv/).

```bash
uv sync                      # creates .venv with runtime and dev dependencies
uv run pre-commit install
uv run black . && uv run ruff check . && uv run mypy && uv run pytest
```

Unit tests mock Garmin and do not need a key. The optional live check is:

```bash
ALLOW_INSECURE_HTTP=1 uv run uvicorn garmin_mcp.asgi:app --port 18790
BASE=http://localhost:18790 GARMIN_KEY_FILE=/path/to/keyfile uv run scripts/e2e.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md). AI coding agents should read
[AGENTS.md](AGENTS.md). For a later move to Garmin's partner
OAuth / Health API, see [PLAN-garmin-official-oauth.md](PLAN-garmin-official-oauth.md).

## License

[MIT](LICENSE) © 2026 Sarath Chandra Bellam
