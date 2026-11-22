#!/usr/bin/env python3
"""Release automation: decide whether main needs a release and prepare it.

Standard library only, so CI can run it before (or without) ``uv sync``.

Rules (see "Versioning and releases" in AGENTS.md):

* Only commits that touch code paths can trigger a release. Docs, tests, scripts,
  CI, agent files and dev tooling never do.
* Conventional Commit type decides the bump: ``feat`` -> minor; ``fix``, ``perf``,
  ``deps`` -> patch; ``!`` or ``BREAKING CHANGE:`` -> major; ``docs``, ``chore``,
  ``ci``, ``test``, ``style``, ``refactor``, ``build`` -> no release.
* A commit without a Conventional Commit title that touches code counts as patch.

Commands:
    release.py check-title "<pr title>"   exit 1 unless the title is a Conventional Commit
    release.py plan                       print the plan; also writes $GITHUB_OUTPUT
    release.py prepare X.Y.Z              set the version and roll the CHANGELOG
    release.py notes X.Y.Z                print that version's CHANGELOG section
"""

from __future__ import annotations

import datetime as dt
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
INIT = ROOT / "src" / "garmin_mcp" / "__init__.py"
CHANGELOG = ROOT / "CHANGELOG.md"
REPO_URL = "https://github.com/SarathChandraBellam/garmin-mcp"

# Paths that change what users get. Everything else is non-code.
CODE_PATHS = ("src/", "pyproject.toml", "uv.lock")

TYPES = (
    "feat",
    "fix",
    "perf",
    "deps",
    "revert",
    "docs",
    "chore",
    "ci",
    "test",
    "style",
    "refactor",
    "build",
)
RELEASE_TYPES = {
    "feat": "minor",
    "fix": "patch",
    "perf": "patch",
    "deps": "patch",
    "revert": "patch",
}
TITLE_RE = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[\w./-]+)\))?(?P<bang>!)?: (?P<desc>\S.*)$")
LEVELS = {"none": 0, "patch": 1, "minor": 2, "major": 3}
SEMVER_RE = re.compile(r"^(\d+)\.(\d+)\.(\d+)$")


@dataclass
class Commit:
    sha: str
    subject: str
    body: str
    files: list[str]


def parse_title(title: str) -> tuple[str, bool] | None:
    """(type, breaking) for a Conventional Commit title, else None."""
    m = TITLE_RE.match(title.strip())
    if not m or m["type"] not in TYPES:
        return None
    return m["type"], bool(m["bang"])


def touches_code(files: list[str]) -> bool:
    return any(f == p or f.startswith(p) for f in files for p in CODE_PATHS)


def commit_bump(c: Commit) -> str:
    if not touches_code(c.files):
        return "none"
    parsed = parse_title(c.subject)
    if parsed is None:
        return "patch"
    ctype, bang = parsed
    if bang or re.search(r"^BREAKING[ -]CHANGE:", c.body, re.M):
        return "major"
    return RELEASE_TYPES.get(ctype, "none")


def overall_bump(commits: list[Commit]) -> str:
    return max((commit_bump(c) for c in commits), key=LEVELS.__getitem__, default="none")


def next_version(version: str, bump: str) -> str:
    m = SEMVER_RE.match(version)
    if not m:
        raise ValueError(f"not X.Y.Z: {version}")
    x, y, z = map(int, m.groups())
    if bump == "major":
        return f"{x + 1}.0.0"
    if bump == "minor":
        return f"{x}.{y + 1}.0"
    if bump == "patch":
        return f"{x}.{y}.{z + 1}"
    return version


# ---- files ----


def read_version() -> str:
    m = re.search(r'^version = "([^"]+)"', PYPROJECT.read_text(), re.M)
    if not m:
        raise SystemExit("no version in pyproject.toml")
    return m.group(1)


def set_version(version: str) -> None:
    for path, pattern, repl in (
        (PYPROJECT, r'^version = "[^"]+"', f'version = "{version}"'),
        (INIT, r'^__version__ = "[^"]+"', f'__version__ = "{version}"'),
    ):
        text, n = re.subn(pattern, repl, path.read_text(), count=1, flags=re.M)
        if n != 1:
            raise SystemExit(f"version line not found in {path.name}")
        path.write_text(text)


SECTION_FOR = {"feat": "Added", "fix": "Fixed", "perf": "Changed", "deps": "Changed"}


def fallback_entries(commits: list[Commit]) -> str:
    """CHANGELOG bullets from commit titles, for when [Unreleased] was left empty."""
    groups: dict[str, list[str]] = {}
    for c in commits:
        bump = commit_bump(c)
        if bump == "none":
            continue
        parsed = parse_title(c.subject)
        section = SECTION_FOR.get(parsed[0], "Changed") if parsed else "Changed"
        desc = TITLE_RE.sub(lambda m: m["desc"], c.subject) if parsed else c.subject
        if bump == "major":
            desc = "**BREAKING:** " + desc
        groups.setdefault(section, []).append(f"- {desc}")
    order = ["Added", "Changed", "Fixed"]
    return "\n\n".join(f"### {s}\n\n" + "\n".join(groups[s]) for s in order if s in groups)


def roll_changelog(text: str, version: str, previous: str, date: str, fallback: str) -> str:
    """Move [Unreleased] under a new version heading and update the compare links."""
    head = "## [Unreleased]\n"
    if head not in text:
        raise SystemExit("CHANGELOG.md has no '## [Unreleased]' heading")
    before, rest = text.split(head, 1)
    nxt = re.search(r"^## \[", rest, re.M)
    body, after = (rest[: nxt.start()], rest[nxt.start() :]) if nxt else (rest, "")
    body = body.strip() or fallback.strip()
    section = f"## [{version}] - {date}\n\n" + (body + "\n\n" if body else "")
    text = before + head + "\n" + section + after
    link_re = re.compile(r"^\[Unreleased\]: .*$", re.M)
    links = (
        f"[Unreleased]: {REPO_URL}/compare/v{version}...HEAD\n"
        f"[{version}]: {REPO_URL}/compare/v{previous}...v{version}"
    )
    if link_re.search(text):
        return link_re.sub(links, text, count=1)
    return text.rstrip("\n") + "\n\n" + links + "\n"


def changelog_section(text: str, version: str) -> str:
    m = re.search(
        rf"^## \[{re.escape(version)}\][^\n]*\n(.*?)(?=^## \[|^\[[^\]]+\]: |\Z)", text, re.M | re.S
    )
    if not m:
        raise SystemExit(f"CHANGELOG.md has no section for {version}")
    return m.group(1).strip()


# ---- git ----


def git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=ROOT, check=True, capture_output=True, text=True
    ).stdout.strip()


def tag_exists(tag: str) -> bool:
    return (
        subprocess.run(
            ["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"],
            cwd=ROOT,
            capture_output=True,
        ).returncode
        == 0
    )


def version_commit() -> str:
    """The commit that last changed the version line in pyproject.toml."""
    return git("log", "-1", "--format=%H", "-G", r'^version = "', "--", "pyproject.toml")


def commits_since(base: str) -> list[Commit]:
    out: list[Commit] = []
    for sha in git("rev-list", "--reverse", f"{base}..HEAD").split():
        subject = git("log", "-1", "--format=%s", sha)
        body = git("log", "-1", "--format=%b", sha)
        files = git("diff-tree", "--no-commit-id", "--name-only", "-r", "-m", sha).split()
        out.append(Commit(sha, subject, body, files))
    return out


# ---- commands ----


def cmd_plan() -> None:
    current = read_version()
    vsha = version_commit()
    publish = not tag_exists(f"v{current}")
    # Everything after the commit that set the current version is pending.
    commits = commits_since(vsha)
    bump = overall_bump(commits)
    nxt = next_version(current, bump)
    outputs = {
        "current": current,
        "publish": str(publish).lower(),
        "publish_sha": vsha,
        "bump": bump,
        "releasable": str(bump != "none").lower(),
        "next": nxt,
    }
    for c in commits:
        print(f"  {commit_bump(c):6} {c.sha[:7]} {c.subject}")
    print(f"current v{current} ({'untagged: will publish' if publish else 'tagged'})")
    print(f"pending bump: {bump}" + (f" -> v{nxt}" if bump != "none" else " (no release)"))
    if gh_out := os.environ.get("GITHUB_OUTPUT"):
        with open(gh_out, "a") as fh:
            fh.writelines(f"{k}={v}\n" for k, v in outputs.items())


def cmd_prepare(version: str) -> None:
    if not SEMVER_RE.match(version):
        raise SystemExit(f"not X.Y.Z: {version}")
    previous = read_version()
    commits = commits_since(version_commit())
    set_version(version)
    today = dt.date.today().isoformat()
    CHANGELOG.write_text(
        roll_changelog(CHANGELOG.read_text(), version, previous, today, fallback_entries(commits))
    )
    print(f"v{previous} -> v{version}; run `uv lock` to update uv.lock")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "check-title":
        if parse_title(argv[1]) is None:
            print(
                f"PR title is not a Conventional Commit: {argv[1]!r}\n"
                f"Use '<type>[(scope)][!]: <description>' with type one of: {', '.join(TYPES)}.\n"
                "Examples: 'feat: add get_respiration tool', 'fix(sdk): retry on 502', "
                "'docs: clarify setup', 'feat!: rename query_stats metric'."
            )
            return 1
        print("ok")
        return 0
    if argv == ["plan"]:
        cmd_plan()
        return 0
    if len(argv) == 2 and argv[0] == "prepare":
        cmd_prepare(argv[1])
        return 0
    if len(argv) == 2 and argv[0] == "notes":
        print(changelog_section(CHANGELOG.read_text(), argv[1]))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
