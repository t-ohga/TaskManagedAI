from __future__ import annotations

import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

ReasonCode = Literal["author_inversion", "timestamp_inversion"]
GitLogRunner = Callable[[Path, Path], Sequence["GitCommit"]]

_GIT_BINARY: Final[Path] = Path("/usr/bin/git")
_UNIT_SEPARATOR: Final[str] = "\x1f"
_RAW_SECRET_VALUE_PATTERNS: Final[tuple[tuple[str, re.Pattern[str]], ...]] = (
    ("openai_api_key", re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b")),
    ("github_pat", re.compile(r"\b(?:ghp|gho|ghu|ghs|ghr)_[A-Za-z0-9_]{16,}\b")),
    ("github_fine_grained_pat", re.compile(r"\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("aws_access_key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
)


@dataclass(frozen=True)
class GitCommit:
    sha: str
    author: str
    committed_at: int
    # F-PR28-R3-006 P2 + R4-002 P2 + R5-004 P2 adopt: ``author`` (%an) is a
    # mutable display name. Including ``author_email`` (%ae) provides a stable
    # contributor identity for author_inversion checks. F-PR28-R4-002 refined
    # the identity rule: when an email is present, the identity is the email
    # **alone**, so that an actor cannot bypass author_inversion by renaming
    # their git ``user.name`` while keeping the same email. F-PR28-R5-004
    # added casing/whitespace normalization (``user@example.com`` and
    # ``User@Example.com`` are the same identity) so that email casing changes
    # cannot bypass the check either.
    author_email: str = ""

    @property
    def author_identity(self) -> str:
        """Stable identity.

        Prefers ``author_email`` (lower-cased, stripped); falls back to
        ``author`` only when no email is recorded.
        """

        normalized_email = self.author_email.strip().lower()
        return normalized_email if normalized_email else self.author.strip()


class AntiGamingViolation(Exception):
    reason_code: ReasonCode
    path: Path
    policy_path: Path
    fixture_commit: GitCommit
    policy_commit: GitCommit

    def __init__(
        self,
        *,
        reason_code: ReasonCode,
        path: Path,
        policy_path: Path,
        fixture_commit: GitCommit,
        policy_commit: GitCommit,
    ) -> None:
        self.reason_code = reason_code
        self.path = path
        self.policy_path = policy_path
        self.fixture_commit = fixture_commit
        self.policy_commit = policy_commit
        super().__init__(self._format_message())

    def _format_message(self) -> str:
        return (
            f"{self.reason_code}: fixture_path={self.path} policy_path={self.policy_path} "
            f"fixture_commit={self.fixture_commit.sha[:12]} "
            f"policy_commit={self.policy_commit.sha[:12]}"
        )


@dataclass(frozen=True)
class AntiGamingReport:
    violations: tuple[AntiGamingViolation, ...]

    def is_clean(self) -> bool:
        return len(self.violations) == 0

    def raise_for_violations(self) -> None:
        if self.violations:
            raise self.violations[0]


def _scan_git_output_for_raw_secret_markers(text: str) -> None:
    for reason_code, pattern in _RAW_SECRET_VALUE_PATTERNS:
        if pattern.search(text):
            raise RuntimeError(f"git output contains raw secret marker (reason_code={reason_code}; raw value redacted)")


def _path_for_git(repo_root: Path, path: Path) -> Path:
    candidate = path if path.is_absolute() else repo_root / path
    try:
        return candidate.resolve().relative_to(repo_root.resolve())
    except ValueError:
        return path


def _default_git_log_runner(repo_root: Path, path: Path) -> Sequence[GitCommit]:
    git_path = _path_for_git(repo_root, path)
    result = subprocess.run(  # noqa: S603
        [
            str(_GIT_BINARY),
            "-C",
            str(repo_root),
            "log",
            # F-PR28-R3-006 P2 adopt: include %ae (author email) for stable
            # contributor identity. ``%an`` alone is a mutable display name.
            "--format=%H%x1f%an%x1f%ae%x1f%ct",
            "--",
            str(git_path),
        ],
        capture_output=True,
        check=False,
        shell=False,
        text=True,
        timeout=30,
    )
    _scan_git_output_for_raw_secret_markers(result.stdout)
    if result.returncode != 0:
        raise RuntimeError(f"git log failed for path {git_path} (returncode={result.returncode})")

    commits: list[GitCommit] = []
    for line in result.stdout.splitlines():
        if not line:
            continue
        parts = line.split(_UNIT_SEPARATOR)
        if len(parts) != 4:
            raise RuntimeError(f"unexpected git log format for path {git_path}")
        sha, author, author_email, committed_at = parts
        try:
            committed_at_int = int(committed_at)
        except ValueError as exc:
            raise RuntimeError(f"unexpected git commit timestamp for path {git_path}") from exc
        commits.append(
            GitCommit(
                sha=sha,
                author=author,
                author_email=author_email,
                committed_at=committed_at_int,
            )
        )
    return commits


def _creation_commit(commits: Sequence[GitCommit]) -> GitCommit | None:
    if not commits:
        return None
    return min(commits, key=lambda commit: commit.committed_at)


def _policy_commits_grouped_by_path(
    repo_root: Path,
    policy_paths: Sequence[Path],
    runner: GitLogRunner,
) -> dict[Path, list[GitCommit]]:
    grouped: dict[Path, list[GitCommit]] = {}
    for policy_path in policy_paths:
        commits = list(runner(repo_root, policy_path))
        if commits:
            grouped[policy_path] = commits
    return grouped


def verify_fixture_commit_separation(
    repo_root: Path,
    *,
    fixture_paths: list[Path],
    policy_paths: list[Path],
    window_seconds: int = 3600,
    git_log_runner: GitLogRunner | None = None,
) -> AntiGamingReport:
    """Detect anti-gaming violations between fixture and policy commits.

    Two attack patterns are flagged:

    1. ``author_inversion``: the fixture commit and the policy/runner/prompt commit
       share an author and were committed within ``window_seconds`` of each other
       (either direction). This catches a single actor authoring both the fixture
       and the policy that the fixture is evaluated against.
    2. ``timestamp_inversion``: the **latest** policy commit was authored
       ``window_seconds`` or less **after** the fixture creation commit. This
       catches the "fixture 作成後に policy を緩めた" pattern — the spec's
       primary concern (PR #28 F-PR28-R1-004 P2 adopt). Older policy commits
       in the same path's history are ignored to avoid false positives on
       newly added fixtures versus long-standing policy code.
    """
    if window_seconds < 0:
        raise ValueError("window_seconds must be non-negative")
    if not fixture_paths:
        return AntiGamingReport(violations=())

    runner = git_log_runner or _default_git_log_runner
    policy_commits_by_path = _policy_commits_grouped_by_path(repo_root, policy_paths, runner)
    if not policy_commits_by_path:
        return AntiGamingReport(violations=())

    violations: list[AntiGamingViolation] = []
    for fixture_path in fixture_paths:
        fixture_commit = _creation_commit(runner(repo_root, fixture_path))
        if fixture_commit is None:
            continue

        for policy_path, policy_commits in policy_commits_by_path.items():
            # author_inversion: scan all policy commits for the same stable
            # author identity (name<email>, F-PR28-R3-006 P2 adopt) within window.
            for policy_commit in policy_commits:
                if (
                    fixture_commit.author_identity == policy_commit.author_identity
                    and abs(fixture_commit.committed_at - policy_commit.committed_at) <= window_seconds
                ):
                    violations.append(
                        AntiGamingViolation(
                            reason_code="author_inversion",
                            path=fixture_path,
                            policy_path=policy_path,
                            fixture_commit=fixture_commit,
                            policy_commit=policy_commit,
                        )
                    )
                    break

            # timestamp_inversion: F-PR28-R6-002 P2 adopt: scan **every** policy
            # commit authored within ``window_seconds`` *after* the fixture
            # creation. Comparing only the latest policy commit lets a
            # subsequent unrelated policy edit move the latest beyond the
            # window, hiding a real suspicious relaxation that occurred within
            # the window. Older policy commits (before fixture creation) are
            # still ignored.
            for policy_commit in policy_commits:
                policy_lag = policy_commit.committed_at - fixture_commit.committed_at
                if 0 < policy_lag <= window_seconds:
                    violations.append(
                        AntiGamingViolation(
                            reason_code="timestamp_inversion",
                            path=fixture_path,
                            policy_path=policy_path,
                            fixture_commit=fixture_commit,
                            policy_commit=policy_commit,
                        )
                    )

    return AntiGamingReport(violations=tuple(violations))


__all__ = [
    "AntiGamingReport",
    "AntiGamingViolation",
    "GitCommit",
    "GitLogRunner",
    "verify_fixture_commit_separation",
]
