## Summary

<!-- What does this change, and why? -->

## Release impact

<!-- Pick one. See "Versioning and releases" in AGENTS.md. -->

- [ ] None — non-code only (docs, tests, CI, agent files, dev tooling)
- [ ] Patch — backward-compatible fix
- [ ] Minor — backward-compatible feature
- [ ] Major — breaking change (describe what users must change)

## Checklist

- [ ] Tests added or updated (synthetic fixtures only; no real keys or live data)
- [ ] `uv run black --check .`, `uv run ruff check .`, `uv run mypy` and `uv run pytest` pass locally
- [ ] Docs / CHANGELOG updated when the public interface changes
- [ ] No secrets, `.env`, or `.secrets/` files are included
