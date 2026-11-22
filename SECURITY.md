# Security Policy

## Supported versions

Security fixes are applied to the latest commit on `main`. If you are running
a deployed copy, please upgrade to that revision after a patch is released.

## Reporting a vulnerability

Please **do not** open a public issue for security problems.

Report privately via GitHub's
[private vulnerability reporting](https://github.com/SarathChandraBellam/garmin-mcp/security/advisories/new)
form. Include:

- a description of the issue and its impact
- steps to reproduce, or a proof of concept if you have one
- the affected commit, tag, or deployment URL

You should receive an acknowledgement within 7 days, and a planned fix or
status update within 30 days when the report is valid.

## What this server does (and does not) store

This project is designed so the **server holds no user secrets and no fitness
data**. Each request carries the caller's own Garmin Personal API key in an HTTP
header (or `GARMIN_API_KEY` for local stdio). The key is exchanged for a
short-lived Garmin token that is cached **in memory only**, keyed by a hash of
the key, and is discarded when the process exits.

Please treat any finding that a key, token, or Garmin payload is written to
disk, logs, or a database as a vulnerability.

When reporting, **never** include a real Garmin Personal API key or live
fitness data. Use a revoked/dummy key and synthetic examples.

## Scope notes

- Hosted deployments you run yourself (API keys in client config, HTTPS, log
  retention) are your responsibility; misconfiguration of a third-party host
  is out of scope unless the project itself logs or persists secrets.
- Issues in Garmin's Personal API should be reported to Garmin, not here.
