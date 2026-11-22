---
name: release
description: Decide whether merged changes need a garmin-mcp release, pick the semantic version bump (major X, minor Y, patch Z), and cut the release (version bump, CHANGELOG, tag, GitHub release). Use when asked to "release", "cut a version", "bump the version", "is this releasable?", or after merging a PR to main.
---

# Release garmin-mcp

Versions follow [Semantic Versioning](https://semver.org): **`X.Y.Z`** =
**MAJOR.MINOR.PATCH**. Tags are `vX.Y.Z`. The changelog follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## 1. Find what changed since the last release

```bash
git fetch origin main --tags
LAST=$(git describe --tags --abbrev=0 origin/main)   # e.g. v0.2.0
git log --oneline "$LAST"..origin/main
git diff --stat "$LAST"..origin/main
```

Also read the `## [Unreleased]` section of `CHANGELOG.md`. If the latest version
in `CHANGELOG.md` / `pyproject.toml` has no matching tag, that version was
never tagged: tag it first (step 5) before deciding on a new one.

## 2. Decide whether a release is needed

A release is needed only when something a **user of the package or server** gets
changes. Classify every changed path:

| Releasable (code) | Not releasable (non-code) |
|---|---|
| `src/garmin_mcp/**` (incl. `web/templates/`) | `*.md` docs: README, CONTRIBUTING, CHANGELOG, SECURITY, PLAN-*, AGENTS/CLAUDE |
| `pyproject.toml` dependencies, `requires-python`, scripts/entry points | `.agents/`, `.claude/` (agent skills, settings, hooks) |
| `uv.lock` **runtime** dependency changes | `tests/**`, `scripts/**` |
| | `.github/**` (CI, templates, Dependabot), `.pre-commit-config.yaml`, `.editorconfig`, `.gitignore` |
| | `uv.lock` / `pyproject.toml` changes to **dev** dependencies only |

**If every change is non-code, do not release.** Say so and stop. Non-code
changes ship with the next code release.

Commit type prefixes ([Conventional Commits](https://www.conventionalcommits.org))
are a hint, but the diff decides: `docs:`, `chore:`, `ci:`, `test:`, `style:`,
`build:` (dev tooling) and `refactor:` with no behaviour change are not releasable.

## 3. Pick the bump

Take the **highest** level any releasable change needs:

| Bump | When | Examples in this project |
|---|---|---|
| **Major** `X` → `X+1.0.0` | A breaking change: an existing client, config or deployment stops working or behaves differently without them changing anything (`feat!:` / `fix!:` / `BREAKING CHANGE:`) | Removing or renaming a tool or a tool parameter; making an optional parameter required; changing a tool's output shape or field names; changing the auth headers, error codes (`missing_garmin_api_key`, `invalid_garmin_api_key`, `https_required`) or status codes; renaming/removing an env var; changing the `/mcp` path or other routes; dropping a Python version; removing the `garmin-mcp` CLI or `garmin_mcp.asgi:app` |
| **Minor** `Y` → `X.Y+1.0` | New backward-compatible functionality (`feat:`) | A new tool; a new optional parameter; a new `query_stats` metric; a new optional env var; new fields added to output; a new route; supporting a new Python version |
| **Patch** `Z` → `X.Y.Z+1` | Backward-compatible fixes with no new features (`fix:`, `perf:`, security fixes, runtime dependency bumps) | Fixing a wrong Garmin path; better error messages; stripping an extra PII field; a runtime dependency security bump; landing-page copy or style fixes |

Rules of thumb:

- When unsure between two levels, choose the higher one and say why.
- A runtime dependency bump is a patch unless it changes behaviour users see
  (then minor), or breaks them (then major). A `fastmcp` upgrade that changes
  the MCP protocol version or transport behaviour is at least minor.
- Removing PII from output is a **patch** (it's a privacy fix), even though the
  output shape changes.
- Major resets minor and patch; minor resets patch: `1.4.2` → `2.0.0` / `1.5.0` / `1.4.3`.

State the decision before changing anything, e.g. *"Releasable: yes. Bump: minor
(new tool `get_respiration`). 0.2.0 → 0.3.0."* and wait for the user to confirm.

## 4. Prepare the release PR

On a branch from `origin/main`:

1. Set the new version in **all three** places:
   - `pyproject.toml` → `[project] version`
   - `src/garmin_mcp/__init__.py` → `__version__`
   - `uv.lock` → run `uv lock` (updates the `garmin-mcp` entry)
2. `CHANGELOG.md`:
   - rename `## [Unreleased]` to `## [X.Y.Z] - YYYY-MM-DD` (today's date) and add a
     fresh empty `## [Unreleased]` above it;
   - make sure every user-facing change is listed under `Added` / `Changed` /
     `Deprecated` / `Removed` / `Fixed` / `Security`; breaking changes start with
     **BREAKING:** and say what users must do;
   - update the link references at the bottom:
     ```
     [Unreleased]: https://github.com/SarathChandraBellam/garmin-mcp/compare/vX.Y.Z...HEAD
     [X.Y.Z]: https://github.com/SarathChandraBellam/garmin-mcp/compare/vPREV...vX.Y.Z
     ```
3. For a major bump, add upgrade notes to `README.md` if config or client setup changed.
4. Run the `run-checks` skill (black, ruff, mypy, pytest) and confirm
   `grep -rn "X.Y.Z" pyproject.toml src/garmin_mcp/__init__.py uv.lock` shows all three.
5. Commit as `chore(release): vX.Y.Z` and open a PR titled `Release vX.Y.Z`.
   The PR changes only version numbers and the changelog.

## 5. Tag and publish (after the release PR is merged)

```bash
git fetch origin main
SHA=$(git rev-parse origin/main)          # the merged release commit
git tag -a vX.Y.Z "$SHA" -m "vX.Y.Z"
git push origin vX.Y.Z
```

Then create a GitHub release for tag `vX.Y.Z` titled `vX.Y.Z`, with that
version's CHANGELOG section as the notes (`gh release create vX.Y.Z --title vX.Y.Z
--notes-file <section>` or the GitHub UI). Mark it as a pre-release while the
version is `0.x` only if the user asks.

Never move or delete a published tag; fix mistakes with a new patch release.
