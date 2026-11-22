---
name: release
description: How garmin-mcp releases work (release-please, semantic versioning X.Y.Z) — pick the right Conventional Commit PR title so the bump is correct, check what the next release will be, review or fix the release PR, force a version, or troubleshoot a missing release. Use when asked to "release", "cut a version", "bump the version", "is this releasable?", or about tags and GitHub releases.
---

# Release garmin-mcp

Versions follow [Semantic Versioning](https://semver.org): **`X.Y.Z`** =
**MAJOR.MINOR.PATCH**, tagged `vX.Y.Z`. Releases are fully automated by
[release-please](https://github.com/googleapis/release-please). Never bump the
version or edit `CHANGELOG.md` by hand.

## How it works

| Piece | Role |
|---|---|
| `.github/workflows/pr-title.yml` | Fails a PR unless its title is a Conventional Commit (`amannn/action-semantic-pull-request`). PRs are squash-merged, so the title becomes the commit release-please reads. |
| `.github/workflows/release-please.yml` | On every push to `main`, opens or updates the release PR (`chore: release X.Y.Z`). When that PR is merged it tags `vX.Y.Z`, creates the GitHub release, and attaches the wheel and sdist. |
| `release-please-config.json` | Python release type; tags without a component (`v0.2.1`); which commit types appear in the changelog; ignored paths; `uv.lock` version update. |
| `.release-please-manifest.json` | The current released version. release-please updates it; don't edit it. |

The release PR bumps the version in `pyproject.toml`,
`src/garmin_mcp/__init__.py` and `uv.lock`, and adds a section to `CHANGELOG.md`.

## Which changes release, and the bump

The **PR title type** decides; the highest bump among merged PRs wins:

| PR title | Bump | Changelog section |
|---|---|---|
| `feat!: …`, `fix!: …`, or a `BREAKING CHANGE:` footer | **Major** `X+1.0.0` | (marked breaking) |
| `feat: …` | **Minor** `X.Y+1.0` | Features |
| `fix: …`, `perf: …`, `deps: …`, `revert: …` | **Patch** `X.Y.Z+1` | Bug Fixes / Performance / Dependencies / Reverts |
| `docs:`, `chore:`, `ci:`, `test:`, `style:`, `refactor:`, `build:` | **No release** | hidden |

A breaking change goes to the next major even while the version is `0.x`
(0.4.2 → 1.0.0).

Commits that only touch `.agents/`, `.claude/`, `.github/`, `tests/` or `scripts/`
are ignored whatever their type (`exclude-paths`). That option only matches
directories, so root files like `README.md` or `AGENTS.md` rely on the title: use
`docs:` for doc-only PRs.

### Choosing the title (what agents must get right)

Classify by what **users of the server or package** see:

- **Breaking (`!`)**: removing or renaming a tool or tool parameter; making an
  optional parameter required; changing a tool's output shape or field names;
  changing auth headers, error codes (`missing_garmin_api_key`,
  `invalid_garmin_api_key`, `https_required`) or status codes; renaming/removing an
  env var; changing `/mcp` or other routes; dropping a Python version; removing the
  `garmin-mcp` CLI or `garmin_mcp.asgi:app`. Explain the migration in the PR body
  after `BREAKING CHANGE:`.
- **`feat`**: a new tool, optional parameter, `query_stats` metric, optional env var,
  output field or route; supporting a new Python version.
- **`fix`**: wrong Garmin path, better error messages, stripping an extra PII field
  (a privacy fix, not breaking), landing-page fixes.
- **`deps`**: runtime dependency bumps (Dependabot uses this). Dev-tool bumps are
  `chore:`; GitHub Actions bumps are `ci:`.
- **`docs` / `test` / `ci` / `chore` / `refactor`**: anything with no user-visible
  change.

When unsure between two levels, choose the higher one and say why. The title's
description becomes the changelog line, so write it for users: `feat: add
get_respiration tool`, not `feat: wellness.py changes`.

## Checking what the next release will be

Open the release PR on GitHub (title `chore: release X.Y.Z`); its body is the
changelog. If there is none, no releasable PR has merged since the last release.
To preview, list merged commit titles since the last tag:

```bash
git fetch origin main --tags
git log --format='%h %s' "$(git describe --tags --abbrev=0 origin/main)"..origin/main
```

## Fixing things

- **A merged PR had the wrong title**: edit that merged PR's description and add
  ```
  BEGIN_COMMIT_OVERRIDE
  feat: add get_respiration tool
  END_COMMIT_OVERRIDE
  ```
  then re-run the Release Please workflow (`workflow_dispatch`). One PR can list
  several commit lines.
- **Force a specific version**: merge a commit (e.g. `chore: release 1.0.0`) whose
  body has a `Release-As: 1.0.0` footer.
- **Wrong changelog wording**: use the commit override above; don't edit the
  release PR branch, release-please regenerates it.
- **No CI on the release PR**: PRs created with the default `GITHUB_TOKEN` don't
  trigger workflows. Add a `RELEASE_TOKEN` secret (fine-grained PAT or GitHub App
  token with contents and pull-requests write) — the workflow uses it when present.
- **Release PR not created at all**: check the workflow run, and that "Allow GitHub
  Actions to create and approve pull requests" is enabled in the repo settings.

Never move or delete a published tag; fix mistakes with a new patch release.
