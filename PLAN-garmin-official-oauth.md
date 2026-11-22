# Plan: moving to Garmin's official OAuth (Garmin Connect Developer Program)

## Where we are now

* **Source:** Garmin Connect **Personal API** – official, self-serve, single-user. Each caller
  sends their own Personal API key (`X-Garmin-Api-Key`); the server exchanges it for a ~24 h
  bearer token, held in memory only. Stateless, multi-tenant, nothing stored.
* **Limits:** keys expire (≤ 1 year) and must be re-created by each user; some metrics
  (Training Readiness / Training Status) are not exposed; pull-only (no push).
* Swap point: `src/garmin_mcp/sdk/client.py` (`GarminSource` protocol / `PersonalApi`). Tools in
  `src/garmin_mcp/tools/` only call the source's typed helpers, so a new source is a drop-in class.

## Target: Garmin Connect Developer Program (Health API + Activity API)

Requires a business application and approval at <https://developer.garmin.com/gc-developer-program/>
(review typically takes weeks). On approval we receive a **consumer (client) key + secret**
and access to the evaluation environment.

### Flow (still stateless on our side)

1. **OAuth 2.0 Authorization Code + PKCE** (Garmin's current OAuth2 flow; OAuth 1.0a is legacy).
   * `GET https://connect.garmin.com/oauth2Confirm?response_type=code&client_id=…&code_challenge=…&code_challenge_method=S256&redirect_uri=…&state=…`
   * `POST https://diauth.garmin.com/di-oauth2-service/oauth/token` (code → access + refresh token).
   * Exact URLs/params to be confirmed from the partner docs we get on approval.
2. **Pass-through token model (no server-side storage):** the MCP server acts as an OAuth
   *proxy* only. The MCP client performs the Garmin consent, and on every MCP request sends
   `Authorization: Bearer <garmin access token>`; the server forwards it to Garmin and returns the
   result. Refresh happens client-side (MCP clients already refresh tokens per the MCP auth spec).
   * Implementation: FastMCP `OAuthProxy` (or `RemoteAuthProvider`) configured with Garmin's
     authorize/token endpoints and our client id/secret (encrypted env vars or a secret
     manager on the host – the only server-held secret, and it is *ours*, not a user's). `/.well-known/oauth-protected-resource`
     and authorization-server metadata are served by FastMCP; DCR is handled by the proxy.
   * To keep the proxy stateless on a typical serverless host, configure its
     client/transaction storage with a signed-JWT/encrypted-cookie backend instead of a DB
     (FastMCP's storage is pluggable), or use a pre-registered client id for each MCP client.
   * Token validation: call a cheap Garmin endpoint (or cache a positive check in memory for a few
     minutes keyed by token hash). Scopes exposed to MCP clients: `garmin:read`.
3. **Data delivery:** the Health/Activity APIs are primarily **push / ping** (Garmin POSTs to our
   webhook, or pings us and we pull a callback URL within a time window), plus backfill
   endpoints. A stateless MCP wants on-demand reads, so:
   * Use **pull** endpoints (`/wellness-api/rest/dailies`, `/sleeps`, `/hrv`, `/activities`, … with
     `uploadStartTimeInSeconds`/`uploadEndTimeInSeconds`, max 24 h windows) at request time.
   * If Garmin only supports ping/push for a data type, the minimal compliant design is a webhook
     that acknowledges pings (HTTP 200) and does **not** persist anything; the MCP fetches the
     callback URL on demand. If Garmin requires durable ingestion, that would need storage — a
     product decision to revisit then (would break "store nothing").
4. **New source class** `GarminHealthApi(GarminSource)` mapping each helper
   (`daily_summaries`, `sleep`, `hrv`, `activities`, `weight_range`, …) to Health/Activity API
   calls and normalising field names to what the tools already return.
5. **Selection:** `GARMIN_SOURCE=personal|health` env var; header decides per request
   (`X-Garmin-Api-Key` → Personal API, `Authorization: Bearer <oauth token>` → Health API).

### Later: OAuth for the MCP endpoint itself (without Garmin partner access)

Today the server is API-key only (like a GitHub PAT). That rules out clients that can't send a
custom header, such as Claude.ai web and mobile. If we need them, add a self-issued OAuth 2.1
layer with FastMCP's `OAuthProvider` in `src/garmin_mcp/auth/`: client ids from Dynamic Client
Registration, authorization codes and tokens; PKCE S256; scope `garmin:read`. The consent page
would ask for the user's Garmin Personal API key, and the key would be sealed (AES-GCM, server
secret) inside the issued tokens so the server still stores nothing. Keep the header key path
alongside it and make OAuth opt-in (for example `ENABLE_OAUTH=1` plus `GARMIN_MCP_SECRET`).
A working version of this was prototyped in commit a0ed009.
