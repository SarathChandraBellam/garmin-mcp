---
name: release
description: Decide whether merged changes need a garmin-mcp release, pick the semantic version bump (major X, minor Y, patch Z), and cut the release (version bump, CHANGELOG, tag, GitHub release). Use when asked to "release", "cut a version", "bump the version", "is this releasable?", or after merging a PR to main.
---

# Release garmin-mcp

Versions follow [Semantic Versioning](https://semver.org): **`X.Y.Z`** =
**MAJOR.MINOR.PATCH**. Tags are `vX.Y.Z`. The changelog follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## How releases happen

Releases are automated; the rules live in code in `scripts/release.py` (tested in
`tests/test_release.py`):

| Workflow | When | What it does |
|---|---|---|
| `.github/workflows/pr-title.yml` | Every PR | Fails unless the title is a Conventional Commit (PRs are squash-merged, so the title becomes the commit on `main`) |
| `.github/workflows/release.yml` → `plan` | Every push to `main` | Classifies commits since the current version and picks the bump |
| `release.yml` → `prepare` | Code changes are pending | Opens or updates the **release PR** (`release/next`, titled `chore(release): vX.Y.Z`) with the version bump in all three files and the rolled CHANGELOG, after running the checks |
| `release.yml` → `publish` | The version in `pyproject.toml` has no tag (a release PR just merged) | Builds, tags `vX.Y.Z`, creates the GitHub release with that CHANGELOG section and the wheel/sdist |

So an agent's job is usually: give PRs correct Conventional Commit titles, keep
`## [Unreleased]` in `CHANGELOG.md` accurate, and review the release PR. Use the
manual steps below only if the user asks or the workflow can't run.

To see what the pipeline would do right now:

```bash
git fetch origin main --tags && git checkout origin/main
python3 scripts/release.py plan
```

## 1. Find what changed since the last release (manual)

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

## 4. Prepare the release PR (manual; normally `release.yml` → `prepare`)

Before anything, make sure every user-facing change is listed under
`## [Unreleased]` in `CHANGELOG.md` (`Added` / `Changed` / `Deprecated` / `Removed` /
`Fixed` / `Security`; breaking changes start with **BREAKING:** and say what users
must do). Do this in a normal PR to `main`, never on the `release/next` branch:
the workflow regenerates that branch on every push.

On a branch from `origin/main`:

1. `python3 scripts/release.py prepare X.Y.Z` — sets the version in
   `pyproject.toml` and `src/garmin_mcp/__init__.py`, moves `[Unreleased]` under
   `## [X.Y.Z] - <today>` and updates the compare links. If `[Unreleased]` was
   empty it fills it from the commit titles.
2. `uv lock` — updates the `garmin-mcp` version in `uv.lock`.
3. For a major bump, add upgrade notes to `README.md` if config or client setup changed.
4. Run the `run-checks` skill (black, ruff, mypy, pytest) and confirm
   `grep -rn "X.Y.Z" pyproject.toml src/garmin_mcp/__init__.py uv.lock` shows all three.
5. Commit as `chore(release): vX.Y.Z` and open a PR titled `Release vX.Y.Z`.
   The PR changes only version numbers and the changelog.

## 5. Tag and publish (manual; normally `release.yml` → `publish`)

After the release PR is merged, the workflow does this by itself. By hand:

```bash
git fetch origin main
SHA=$(git rev-parse origin/main)          # the merged release commit
python3 scripts/release.py notes X.Y.Z > notes.md
uv build
gh release create vX.Y.Z dist/* --target "$SHA" --title vX.Y.Z --notes-file notes.md
```

Never move or delete a published tag; fix mistakes with a new patch release.
