"""Release rules in scripts/release.py (pure functions; no git needed)."""

from __future__ import annotations

import pytest

from scripts.release import (
    Commit,
    changelog_section,
    commit_bump,
    next_version,
    overall_bump,
    parse_title,
    roll_changelog,
)


def c(subject: str, files: list[str], body: str = "") -> Commit:
    return Commit("0" * 40, subject, body, files)


SRC = ["src/garmin_mcp/tools/wellness.py"]


@pytest.mark.parametrize(
    ("title", "expected"),
    [
        ("feat: add get_respiration", ("feat", False)),
        ("fix(sdk): retry once on 401 (#14)", ("fix", False)),
        ("feat!: rename query_stats metric", ("feat", True)),
        ("chore(deps-dev): bump ruff", ("chore", False)),
        ("Upgrade fastmcp", None),
        ("feature: nope", None),
        ("feat:missing space", None),
    ],
)
def test_parse_title(title, expected):
    assert parse_title(title) == expected


@pytest.mark.parametrize(
    ("commit", "bump"),
    [
        (c("feat: new tool", SRC), "minor"),
        (c("fix: wrong path", SRC), "patch"),
        (c("fix(deps): bump httpx", ["uv.lock"]), "patch"),
        (c("feat!: drop get_hrv", SRC), "major"),
        (c("feat: x", SRC, body="BREAKING CHANGE: removed y"), "major"),
        (c("refactor: tidy", SRC), "none"),
        (c("chore(deps-dev): bump ruff", ["pyproject.toml", "uv.lock"]), "none"),
        (c("Upgrade fastmcp", ["pyproject.toml", "uv.lock"]), "patch"),
        # Non-code only never releases, whatever the type says.
        (c("feat: document a tool", ["README.md", "AGENTS.md"]), "none"),
        (c("fix!: CI", [".github/workflows/ci.yml", "tests/test_server.py"]), "none"),
        (c("Improve docs", [".agents/skills/release/SKILL.md"]), "none"),
    ],
)
def test_commit_bump(commit, bump):
    assert commit_bump(commit) == bump


def test_overall_bump_takes_highest():
    assert overall_bump([]) == "none"
    assert overall_bump([c("docs: a", ["README.md"]), c("fix: b", SRC)]) == "patch"
    assert overall_bump([c("fix: b", SRC), c("feat: a", SRC)]) == "minor"
    assert overall_bump([c("feat!: a", SRC), c("feat: b", SRC)]) == "major"


@pytest.mark.parametrize(
    ("bump", "expected"),
    [("none", "1.4.2"), ("patch", "1.4.3"), ("minor", "1.5.0"), ("major", "2.0.0")],
)
def test_next_version(bump, expected):
    assert next_version("1.4.2", bump) == expected


CHANGELOG = """# Changelog

## [Unreleased]

### Added

- New tool.

## [0.2.0] - 2026-01-01

### Added

- Landing page.

[Unreleased]: https://github.com/SarathChandraBellam/garmin-mcp/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/SarathChandraBellam/garmin-mcp/compare/v0.1.0...v0.2.0
"""


def test_roll_changelog_moves_unreleased_and_links():
    out = roll_changelog(CHANGELOG, "0.3.0", "0.2.0", "2026-02-01", fallback="unused")
    assert "## [Unreleased]\n\n## [0.3.0] - 2026-02-01\n\n### Added\n\n- New tool.\n" in out
    assert "compare/v0.3.0...HEAD" in out
    assert (
        "[0.3.0]: https://github.com/SarathChandraBellam/garmin-mcp/compare/v0.2.0...v0.3.0" in out
    )
    assert "[0.2.0]: " in out
    assert changelog_section(out, "0.3.0") == "### Added\n\n- New tool."
    assert changelog_section(out, "0.2.0") == "### Added\n\n- Landing page."


def test_roll_changelog_uses_fallback_when_unreleased_is_empty():
    empty = CHANGELOG.replace("### Added\n\n- New tool.\n\n", "", 1)
    out = roll_changelog(empty, "0.2.1", "0.2.0", "2026-02-01", fallback="### Fixed\n\n- x")
    assert changelog_section(out, "0.2.1") == "### Fixed\n\n- x"
