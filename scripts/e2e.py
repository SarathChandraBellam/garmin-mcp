#!/usr/bin/env python3
"""Live end-to-end check against a running server. Never prints the key.

Usage:
    BASE=https://... GARMIN_KEY_FILE=/path/to/keyfile uv run scripts/e2e.py

This is opt-in and is not run by CI or a default `pytest` invocation.
"""

from __future__ import annotations

import json
import os
import sys

import httpx

BASE = os.environ["BASE"].rstrip("/")
with open(os.environ["GARMIN_KEY_FILE"]) as fh:
    KEY = fh.read().strip()
H = {
    "content-type": "application/json",
    "accept": "application/json, text/event-stream",
    "mcp-protocol-version": "2025-06-18",
}
_rpc_id = 0
fails = 0


def check(ok: bool, msg: str) -> None:
    global fails
    print(("PASS " if ok else "FAIL ") + msg)
    fails += 0 if ok else 1


def rpc(method: str, params=None, headers=None):
    global _rpc_id
    _rpc_id += 1
    return httpx.post(
        f"{BASE}/mcp",
        headers={**H, **(headers or {})},
        json={"jsonrpc": "2.0", "id": _rpc_id, "method": method, "params": params or {}},
        timeout=60,
    )


def main() -> int:
    init = {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "e2e", "version": "1"},
    }
    r = rpc("initialize", init)
    check(
        r.status_code == 401 and r.json()["error"] == "missing_garmin_api_key",
        f"no key -> {r.status_code} {r.json().get('error')}",
    )
    r = rpc("tools/list", headers={"x-garmin-api-key": "not-a-real-key"})
    check(r.status_code == 401, f"bogus key -> {r.status_code} {r.json().get('error')}")
    r = rpc("initialize", init, headers={"x-garmin-api-key": KEY})
    check(
        r.status_code == 200 and "serverInfo" in r.json()["result"],
        f"initialize (X-Garmin-Api-Key) -> {r.status_code}, "
        f"session header: {r.headers.get('mcp-session-id')}",
    )
    r = rpc("tools/list", headers={"authorization": f"Bearer {KEY}"})
    tools = [t["name"] for t in r.json()["result"]["tools"]]
    check(len(tools) > 5, f"tools/list (Bearer, no session) -> {len(tools)}: {', '.join(tools)}")

    def call(name, args=None, auth="x"):
        hdr = {"x-garmin-api-key": KEY} if auth == "x" else {"authorization": f"Bearer {KEY}"}
        res = rpc("tools/call", {"name": name, "arguments": args or {}}, headers=hdr).json()[
            "result"
        ]
        txt = res["content"][0]["text"] if res.get("content") else ""
        return res.get("isError", False), txt

    err, txt = call("get_activities", {"limit": 3})
    acts = json.loads(txt) if not err else []
    newest = "-"
    if acts:
        newest = f"{acts[0].get('type')} on {(acts[0].get('start_local') or '')[:10]}"
    check(
        not err and len(acts) > 0,
        f"get_activities -> {len(acts)} live activities (newest: {newest})",
    )
    for name, args in [
        ("get_profile", {}),
        ("get_daily_summary", {}),
        ("get_sleep", {}),
        ("get_heart_rate", {}),
        ("get_hrv", {}),
        ("get_body_composition", {}),
        ("get_training_readiness", {}),
        ("query_stats", {"metric": "steps", "start_date": "2026-11-01"}),
    ]:
        err, txt = call(name, args, auth="b")
        preview = f"error: {txt[:120]}" if err else f"ok ({len(txt)} chars)"
        check(not err, f"{name} -> {preview}")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
