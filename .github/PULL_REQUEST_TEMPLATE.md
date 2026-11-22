## Summary

<!-- What does this change, and why? -->

## Release impact

<!-- The PR title's type sets the release (see "Versioning and releases" in AGENTS.md).
     Pick the one that matches your title. -->

- [ ] None — `docs:`, `chore:`, `ci:`, `test:`, `refactor:` (non-code only)
- [ ] Patch — `fix:`, `perf:`, `deps:`
- [ ] Minor — `feat:`
- [ ] Major — `feat!:` / `fix!:` (add `BREAKING CHANGE: <what users must change>` below)

## Checklist

- [ ] Tests added or updated (synthetic fixtures only; no real keys or live data)
- [ ] `uv run black --check .`, `uv run ruff check .`, `uv run mypy` and `uv run pytest` pass locally
- [ ] Docs updated when the public interface changes (CHANGELOG is generated; don't edit it)
- [ ] No secrets, `.env`, or `.secrets/` files are included
