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
(per-day health data), `stats.py` (date-range series), `analytics.py` (tools that
summarise a window), `app_data.py` (tools only an MCP App calls). Follow this shape:

```python
def get_respiration(date: OptDate = None) -> Any:
    """Breathing rate for a day: waking/sleep averages, min and max."""
    d = date or today(timezone)
    return _or_note(no_pii(call(source().respiration, d)), f"No respiration data for {d}")
```
(with `timezone: OptTimezone = None` as a parameter).

Rules:

- Get the client with `source()` and wrap every Garmin call in `call(...)`.
- Dates: `DateStr` / `OptDate` from `..contracts`. "Today" is the caller's: take
  `timezone: OptTimezone = None` and use `today(timezone)` from `._context`.
- Date ranges: accept `start_date` / `end_date` **and** `period: OptPeriod = None`, and
  resolve them with `resolve_window(period, start_date, end_date, timezone, default=...)`
  from `._window` (explicit dates win, then `period`, then the default). Include the
  `Window` in the response (`window` field) so the model knows which dates it got.
- Several Garmin calls: never loop serially. Use `fetch_series` from `._fetch` for
  daily series (chunked to Garmin's caps, at most 4 in flight) or `parallel([...])`
  from `._context`. In an `async` tool, run blocking Garmin I/O with
  `await anyio.to_thread.run_sync(...)`.
- Constrain other inputs with `Annotated[..., Field(...)]` (bounds, max_length).
  A fixed set of choices is a `Literal` in `contracts/common.py`.
- Always pass output through `no_pii(...)`. Collapse large per-sample arrays with
  `strip_samples(...)` and offer an `include_samples: bool = False` flag.
- Return a `Note(note=...).model_dump()` when Garmin has nothing, not `None`.
- If Garmin returns fields that identify the owner or a location, add them to
  `PII_FIELDS` in `tools/_sanitize.py`.
- The tool must be read-only. Never add one that writes to Garmin.

**Analytics tools** (answers, not payloads): put the maths in `src/garmin_mcp/analytics/`
as pure functions with unit tests (no network), give the tool a typed output model in
`contracts/analytics.py` with a `summary: str` and `notes: list[str]`, return
`result(model)` (structured content plus a text summary), take
`detail: Detail = "summary"`, and add the model to `OUTPUT_MODELS` so clients get an
output schema. Daily metrics for `get_trends` / `compare_periods` are one `MetricDef`
in `analytics/extract.py`.

**Asking the user** (`tools/_elicit.py`): only when it helps, never for secrets, and
every call must still work with no answer. Create `el = Elicitor(ctx, "<tool>", args)`,
then `ans = await el.ask(key, message, schema)`; if `ans` is an `InputRequiredResult`
return it unchanged, otherwise use `ans.value` or fall back to a default and add a
note. `args` end up in `request_state`: tool arguments only, never a key or Garmin data.

**MCP Apps:** an app is `src/garmin_mcp/apps/templates/<name>.html` plus an `AppSpec`
in `apps/__init__.py` naming the tool that opens it and the app-only tools it calls.
Insert data with `textContent` only, load nothing from outside, and extend the browser
smoke test in `tests/test_apps.py`.

For a new `query_stats` metric instead of a new tool: add the name to `Metric` in
`contracts/common.py` and to the dispatch dict in `tools/stats.py`.

## 3. Register it (`src/garmin_mcp/tools/__init__.py`)

Add the function to `ALL_TOOLS` (wellness tools go in `wellness.TOOLS`, analytics tools
in `analytics.TOOLS`; app-only tools go in an `AppSpec` instead).
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
- Title the PR `feat: add <tool name> tool` (or `fix:` / `feat!:` for changes; see the
  `release` skill). Don't edit `CHANGELOG.md`; release-please generates it from the title.

## 6. Verify

Run the `run-checks` skill (black, ruff, mypy, pytest) and report the results.
