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
            "--format=%H%x1f%an%x1f%ct",
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
        if len(parts) != 3:
            raise RuntimeError(f"unexpected git log format for path {git_path}")
        sha, author, committed_at = parts
        try:
            committed_at_int = int(committed_at)
        except ValueError as exc:
            raise RuntimeError(f"unexpected git commit timestamp for path {git_path}") from exc
        commits.append(GitCommit(sha=sha, author=author, committed_at=committed_at_int))
    return commits


def _creation_commit(commits: Sequence[GitCommit]) -> GitCommit | None:
    if not commits:
        return None
    return min(commits, key=lambda commit: commit.committed_at)


def _policy_commits(
    repo_root: Path,
    policy_paths: Sequence[Path],
    runner: GitLogRunner,
) -> list[tuple[Path, GitCommit]]:
    commits: list[tuple[Path, GitCommit]] = []
    seen: set[tuple[Path, str]] = set()
    for policy_path in policy_paths:
        for commit in runner(repo_root, policy_path):
            key = (policy_path, commit.sha)
            if key in seen:
                continue
            seen.add(key)
            commits.append((policy_path, commit))
    return commits


def verify_fixture_commit_separation(
    repo_root: Path,
    *,
    fixture_paths: list[Path],
    policy_paths: list[Path],
    window_seconds: int = 3600,
    git_log_runner: GitLogRunner | None = None,
) -> AntiGamingReport:
    if window_seconds < 0:
        raise ValueError("window_seconds must be non-negative")
    if not fixture_paths:
        return AntiGamingReport(violations=())

    runner = git_log_runner or _default_git_log_runner
    policy_commit_pairs = _policy_commits(repo_root, policy_paths, runner)
    if not policy_commit_pairs:
        return AntiGamingReport(violations=())

    violations: list[AntiGamingViolation] = []
    for fixture_path in fixture_paths:
        fixture_commit = _creation_commit(runner(repo_root, fixture_path))
        if fixture_commit is None:
            continue

        for policy_path, policy_commit in policy_commit_pairs:
            if (
                fixture_commit.author == policy_commit.author
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

            if fixture_commit.committed_at > policy_commit.committed_at + window_seconds:
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
