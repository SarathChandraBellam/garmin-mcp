---
name: add-mcp-tool
description: Add a new read-only MCP tool (or change an existing one) to garmin-mcp, wired to a Garmin Personal API endpoint, with tests and docs. Use when asked to expose more Garmin data, add a tool, or change a tool's inputs or output.
---

# Add or change an MCP tool

Tools are plain functions; FastMCP builds the schema from the type hints and
uses the **docstring as the tool description** clients see.

## 1. SDK helper (`src/garmin_mcp/sdk/client.py`)

If the tool needs a new Garmin endpoint, add a typed helper to `PersonalApi`
next to the others (the path below is illustrative; confirm the real one
against Garmin's Personal API). It only builds the path and params and calls `self.get(...)`:

```python
def respiration(self, d: str) -> Any:
    return self.get(f"/wellness-service/wellness/daily/respiration/{d}")
```

`get` already handles the token exchange, one retry on 401, `None` on 204/404,
and maps errors to `GarminAuthError` / `GarminApiError`. Tools never import
`httpx`.

## 2. The tool (`src/garmin_mcp/tools/<module>.py`)

Pick the module by topic: `profile.py`, `activities.py`, `wellness.py`
(per-day health data), `stats.py` (date-range series). Follow this shape:

```python
def get_respiration(date: OptDate = None) -> Any:
    """Breathing rate for a day: waking/sleep averages, min and max."""
    d = date or today()
    return _or_note(no_pii(call(source().respiration, d)), f"No respiration data for {d}")
```

Rules:

- Get the client with `source()` and wrap every Garmin call in `call(...)`.
- Dates: `DateStr` / `OptDate` from `..contracts`; defaults and ranges with
  `today()`, `shift()`, `check_range(start, end, max_days)` from `._context`.
- Constrain other inputs with `Annotated[..., Field(...)]` (bounds, max_length).
  A fixed set of choices is a `Literal` in `contracts/common.py`.
- Always pass output through `no_pii(...)`. Collapse large per-sample arrays with
  `strip_samples(...)` and offer an `include_samples: bool = False` flag.
- Return a `Note(note=...).model_dump()` when Garmin has nothing, not `None`.
- If Garmin returns fields that identify the owner or a location, add them to
  `PII_FIELDS` in `tools/_sanitize.py`.
- The tool must be read-only. Never add one that writes to Garmin.

For a new `query_stats` metric instead of a new tool: add the name to `Metric` in
`contracts/common.py` and to the dispatch dict in `tools/stats.py`.

## 3. Register it (`src/garmin_mcp/tools/__init__.py`)

Add the function to `ALL_TOOLS` (wellness tools go in `wellness.TOOLS`).
Registration applies the `READ_ONLY` annotations and the landing page's tool
table picks it up automatically.

## 4. Test it (`tests/`)

- Add a synthetic payload to `tests/fixtures.py`: made-up values only, never a
  real export. Include a PII field if the tool should strip one.
- In `tests/test_server.py`, mock the token exchange and the endpoint with
  `respx`, then call through MCP with the `_call` helper:

```python
@respx.mock
def test_get_respiration(client: TestClient):
    respx.post(PERSONAL_BASE + TOKEN_PATH).mock(return_value=httpx.Response(200, text=fake_jwt()))
    respx.get(f"{PERSONAL_BASE}/wellness-service/wellness/daily/respiration/2026-01-15").mock(
        return_value=httpx.Response(200, json=RESPIRATION)
    )
    err, text = _call(client, "get_respiration", {"date": "2026-01-15"})
    assert not err
```

Also cover the empty case (204 → note) when the tool has one.

## 5. Docs

- Add a row to the **Tools** table in `README.md`.
- Add an entry under `## [Unreleased]` → `### Added` (or `### Changed`) in `CHANGELOG.md`.

## 6. Verify

Run the `run-checks` skill (black, ruff, mypy, pytest) and report the results.
