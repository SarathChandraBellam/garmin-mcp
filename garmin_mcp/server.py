"""FastMCP 2.x server: stateless Streamable HTTP, bring-your-own Garmin Personal API key.

Auth model: each MCP client sends ITS OWN Garmin Personal API key on every request,
    X-Garmin-Api-Key: <key>        (preferred)
    Authorization: Bearer <key>    (alternative)
The server holds no keys. Missing/invalid key -> HTTP 401. In stdio mode the key comes from
the GARMIN_API_KEY env var instead. Headers are never logged.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Annotated, Any, Literal
from zoneinfo import ZoneInfo

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.dependencies import get_http_headers
from pydantic import Field
from starlette.requests import Request
from starlette.responses import JSONResponse

from .garmin import GarminApiError, GarminAuthError, PersonalApi, personal_token

DEFAULT_TZ = os.environ.get("DEFAULT_TIMEZONE", "UTC")
KEY_HEADER = "x-garmin-api-key"

mcp = FastMCP(
    name="garmin-mcp",
    instructions=(
        "Live, read-only access to the caller's own Garmin Connect data via the official Garmin "
        "Personal API. Nothing is cached or stored server-side; each call fetches from Garmin. "
        "Dates are YYYY-MM-DD in the user's local calendar."
    ),
)


# ---------------------------------------------------------------- key plumbing
def extract_key(headers: dict[str, str]) -> str | None:
    h = {k.lower(): v for k, v in headers.items()}
    if h.get(KEY_HEADER, "").strip():
        return h[KEY_HEADER].strip()
    auth = h.get("authorization", "")
    if auth[:7].lower() == "bearer " and auth[7:].strip():
        return auth[7:].strip()
    return None


def _source() -> PersonalApi:
    key = (
        extract_key(get_http_headers(include_all=True))
        or os.environ.get("GARMIN_API_KEY", "").strip()
    )
    if not key:
        raise ToolError(
            "No Garmin Personal API key: send header X-Garmin-Api-Key (HTTP) or set GARMIN_API_KEY (stdio)."
        )
    return PersonalApi(key)


def _call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except GarminAuthError as e:
        raise ToolError(str(e)) from None
    except GarminApiError as e:
        raise ToolError(str(e)) from None


def _today() -> str:
    return dt.datetime.now(ZoneInfo(DEFAULT_TZ)).date().isoformat()


def _shift(d: str, days: int) -> str:
    return (dt.date.fromisoformat(d) + dt.timedelta(days=days)).isoformat()


def _check_range(start: str, end: str, max_days: int = 366) -> None:
    s, e = dt.date.fromisoformat(start), dt.date.fromisoformat(end)
    if s > e:
        raise ToolError("start_date must be <= end_date")
    if (e - s).days > max_days:
        raise ToolError(f"Range too long (max {max_days} days)")


DateStr = Annotated[str, Field(pattern=r"^\d{4}-\d{2}-\d{2}$", description="YYYY-MM-DD")]
OptDate = Annotated[
    str | None,
    Field(
        default=None,
        pattern=r"^\d{4}-\d{2}-\d{2}$",
        description=f"YYYY-MM-DD; default today ({DEFAULT_TZ})",
    ),
]
RO = {"readOnlyHint": True, "openWorldHint": True, "idempotentHint": True}


def _strip_samples(obj: Any, keep: bool) -> Any:
    if keep or not isinstance(obj, dict):
        return obj
    out = {}
    for k, v in obj.items():
        if isinstance(v, list) and len(v) > 50:
            out[k] = f"[{len(v)} samples omitted; pass include_samples=true]"
        else:
            out[k] = v
    return out


_PII = {
    "ownerDisplayName",
    "ownerFullName",
    "ownerId",
    "ownerProfileImageUrlLarge",
    "ownerProfileImageUrlMedium",
    "ownerProfileImageUrlSmall",
    "startLatitude",
    "startLongitude",
    "endLatitude",
    "endLongitude",
    "userProfilePK",
    "userProfilePk",
}


def _round(value: Any, digits: int = 1) -> float | None:
    return round(value, digits) if isinstance(value, (int, float)) else None


def _slim_activity(a: dict) -> dict:
    return {
        "activity_id": a.get("activityId"),
        "name": a.get("activityName"),
        "type": (a.get("activityType") or {}).get("typeKey"),
        "start_local": a.get("startTimeLocal"),
        "start_gmt": a.get("startTimeGMT"),
        "location": a.get("locationName"),
        "distance_km": _round((a.get("distance") or 0) / 1000, 3)
        if a.get("distance") is not None
        else None,
        "duration_min": _round((a.get("duration") or 0) / 60)
        if a.get("duration") is not None
        else None,
        "moving_min": _round((a.get("movingDuration") or 0) / 60)
        if a.get("movingDuration") is not None
        else None,
        "calories": a.get("calories"),
        "avg_hr": a.get("averageHR"),
        "max_hr": a.get("maxHR"),
        "avg_speed_kmh": _round(a["averageSpeed"] * 3.6, 2)
        if isinstance(a.get("averageSpeed"), (int, float))
        else None,
        "elevation_gain_m": a.get("elevationGain"),
        "steps": a.get("steps"),
        "training_effect": a.get("trainingEffectLabel"),
        "body_battery_change": a.get("differenceBodyBattery"),
        "hr_zone_secs": [a.get(f"hrTimeInZone_{i}") for i in range(1, 6)],
    }


def _no_pii(x: Any) -> Any:
    if isinstance(x, dict):
        return {k: _no_pii(v) for k, v in x.items() if k not in _PII}
    if isinstance(x, list):
        return [_no_pii(v) for v in x]
    return x


# ---------------------------------------------------------------- tools
@mcp.tool(annotations=RO)
def get_profile() -> Any:
    """Garmin profile settings (display name, units, locale). Use to check the key works."""
    return _call(_source().profile_settings)


@mcp.tool(annotations=RO)
def get_activities(
    start_date: OptDate = None,
    end_date: OptDate = None,
    activity_type: Annotated[
        str | None,
        Field(
            default=None,
            max_length=40,
            description="e.g. running, cycling, walking, strength_training",
        ),
    ] = None,
    limit: Annotated[int, Field(ge=1, le=100)] = 20,
    offset: Annotated[int, Field(ge=0)] = 0,
    raw: bool = False,
) -> Any:
    """List activities newest first with key metrics; optional date window, type filter and paging."""
    acts = _call(_source().activities, offset, limit, start_date, end_date, activity_type) or []
    return _no_pii(acts) if raw else [_slim_activity(a) for a in acts]


@mcp.tool(annotations=RO)
def get_activity(activity_id: Annotated[int, Field(gt=0)]) -> Any:
    """Full details for one activity."""
    return _no_pii(_call(_source().activity, activity_id))


@mcp.tool(annotations=RO)
def get_daily_summary(date: OptDate = None) -> Any:
    """Daily summary for one day: steps/movement, calories, heart rate, stress, Body Battery, intensity minutes, SpO2, respiration."""
    d = date or _today()
    res = _call(_source().daily_summaries, d, d) or {}
    data = res.get("data") if isinstance(res, dict) else res
    return _no_pii(data[0]) if data else {"note": f"No daily summary for {d}"}


@mcp.tool(annotations=RO)
def get_sleep(date: OptDate = None) -> Any:
    """Sleep for the night ending on `date`: total/deep/light/REM/awake seconds, timings, sleep need."""
    d = date or _today()
    return _no_pii(_call(_source().sleep, d)) or {"note": f"No sleep data for {d}"}


@mcp.tool(annotations=RO)
def get_heart_rate(date: OptDate = None, include_samples: bool = False) -> Any:
    """Heart rate for a day: resting, min, max, 7-day resting average. Per-minute samples omitted unless include_samples."""
    d = date or _today()
    return _no_pii(_strip_samples(_call(_source().heart_rate, d), include_samples)) or {
        "note": f"No heart-rate data for {d}"
    }


@mcp.tool(annotations=RO)
def get_hrv(date: OptDate = None) -> Any:
    """Overnight heart-rate variability summary for a day."""
    d = date or _today()
    return _no_pii(_call(_source().hrv, d)) or {
        "note": f"No HRV data for {d} (device may not record HRV)"
    }


@mcp.tool(annotations=RO)
def get_body_composition(start_date: OptDate = None, end_date: OptDate = None) -> Any:
    """Weight / body-composition measurements in a range (default last 30 days)."""
    e = end_date or _today()
    s = start_date or _shift(e, -30)
    _check_range(s, e)
    return _no_pii(_call(_source().weight_range, s, e))


@mcp.tool(annotations=RO)
def get_spo2(date: OptDate = None) -> Any:
    """Pulse-ox (SpO2) and acclimation for a day."""
    d = date or _today()
    return _strip_samples(_no_pii(_call(_source().spo2, d)), False) or {
        "note": f"No SpO2 data for {d}"
    }


@mcp.tool(annotations=RO)
def get_fitness_age(date: OptDate = None) -> Any:
    """Fitness age and its components."""
    return _no_pii(_call(_source().fitness_age, date or _today()))


@mcp.tool(annotations=RO)
def get_heart_rate_zones() -> Any:
    """Configured heart-rate zones."""
    return _no_pii(_call(_source().hr_zones))


@mcp.tool(annotations=RO)
def get_training_readiness(date: OptDate = None) -> Any:
    """Training readiness. Not exposed by the Garmin Personal API; returns HRV, sleep and Body Battery for the day as proxies."""
    d = date or _today()
    src = _source()
    bb = _call(src.body_battery_range, d, d)
    return {
        "note": "Garmin's Personal API does not expose Training Readiness; showing its main inputs instead.",
        "date": d,
        "hrv": _no_pii(_call(src.hrv, d)),
        "sleep": _no_pii(_call(src.sleep, d)),
        "body_battery": _strip_samples(_no_pii(bb[0]), False)
        if isinstance(bb, list) and bb
        else bb,
    }


Metric = Literal[
    "steps",
    "stress",
    "body_battery",
    "sleep",
    "hrv",
    "weight",
    "vo2max",
    "hydration",
    "daily_summaries",
    "wellness_activities",
]


@mcp.tool(annotations=RO)
def query_stats(metric: Metric, start_date: DateStr, end_date: OptDate = None) -> Any:
    """Daily time series for one whitelisted metric over a date range (max 366 days; daily_summaries max 31) for trends and comparisons."""
    e = end_date or _today()
    _check_range(start_date, e, 31 if metric == "daily_summaries" else 366)
    src = _source()
    fn = {
        "steps": src.steps_range,
        "stress": src.stress_range,
        "body_battery": src.body_battery_range,
        "sleep": src.sleep_summaries,
        "hrv": src.hrv_range,
        "weight": src.weight_range,
        "vo2max": src.vo2max_range,
        "hydration": src.hydration_range,
        "daily_summaries": src.daily_summaries,
        "wellness_activities": src.wellness_activities,
    }[metric]
    res = _no_pii(_call(fn, start_date, e))
    if metric == "body_battery" and isinstance(res, list):
        res = [_strip_samples(x, False) for x in res]
    return res


@mcp.custom_route("/", methods=["GET"])
async def info(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "name": "garmin-mcp",
            "transport": "streamable-http (stateless)",
            "endpoint": "/mcp",
            "auth": "send your own Garmin Personal API key in header X-Garmin-Api-Key (or Authorization: Bearer)",
            "stores_data": False,
        }
    )


@mcp.custom_route("/healthz", methods=["GET"])
async def healthz(_: Request) -> JSONResponse:
    return JSONResponse({"ok": True})


# ---------------------------------------------------------------- ASGI auth gate
class GarminKeyGate:
    """Rejects /mcp requests without a valid Garmin key (401) and plain-HTTP requests (403). Never logs headers."""

    def __init__(self, app, path_prefix: str = "/mcp"):
        self.app, self.prefix = app, path_prefix

    async def __call__(self, scope, receive, send):
        if (
            scope["type"] != "http"
            or not scope["path"].startswith(self.prefix)
            or scope["method"] == "OPTIONS"
        ):
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope["headers"]}
        host = headers.get("host", "").split(":")[0]
        proto = headers.get("x-forwarded-proto", scope.get("scheme", "http"))
        if (
            proto != "https"
            and host not in ("localhost", "127.0.0.1")
            and os.environ.get("ALLOW_INSECURE_HTTP") != "1"
        ):
            return await _json(send, 403, {"error": "https_required"})
        key = extract_key(headers)
        if not key:
            return await _json(
                send,
                401,
                {
                    "error": "missing_garmin_api_key",
                    "error_description": "Send your Garmin Personal API key in the X-Garmin-Api-Key header (or Authorization: Bearer <key>). Create one at https://connect.garmin.com/app/settings/personalApiToken",
                },
            )
        try:
            import anyio

            await anyio.to_thread.run_sync(personal_token, key)  # validates + warms in-memory cache
        except GarminAuthError as e:
            return await _json(
                send, 401, {"error": "invalid_garmin_api_key", "error_description": str(e)}
            )
        except GarminApiError as e:
            return await _json(
                send,
                502 if e.status != 429 else 429,
                {"error": "garmin_unavailable", "error_description": str(e)},
            )
        return await self.app(scope, receive, send)


async def _json(send, status: int, body: dict):
    data = json.dumps(body).encode()
    hdrs = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(data)).encode()),
        (b"cache-control", b"no-store"),
    ]
    if status == 401:
        hdrs.append((b"www-authenticate", b'ApiKey header="X-Garmin-Api-Key"'))
    await send({"type": "http.response.start", "status": status, "headers": hdrs})
    await send({"type": "http.response.body", "body": data})


def build_app():
    return mcp.http_app(path="/mcp", stateless_http=True, json_response=True)


class App:
    """ASGI entry. Uses one shared app when the host runs ASGI lifespan; otherwise (some serverless
    runtimes) builds a throwaway app per request and runs its lifespan around the request."""

    def __init__(self):
        self.shared = build_app()
        self.lifespan_started = False

    async def __call__(self, scope, receive, send):
        if scope["type"] == "lifespan":

            async def rcv():
                msg = await receive()
                if msg["type"] == "lifespan.startup":
                    self.lifespan_started = True
                return msg

            return await self.shared(scope, rcv, send)
        if self.lifespan_started:
            return await GarminKeyGate(self.shared)(scope, receive, send)
        app = build_app()
        async with app.router.lifespan_context(app):
            return await GarminKeyGate(app)(scope, receive, send)


app = App()


def main() -> None:
    """stdio entry point (key from GARMIN_API_KEY)."""
    mcp.run()


if __name__ == "__main__":
    main()
