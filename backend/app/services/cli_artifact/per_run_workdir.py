"""Sprint 6 BL-0065 batch 2 (R3-003 完全対策): server-owned per-run artifact workdir.

Codex SP6B1 R3 F-SP6B1-R3-003 で「caller supplied output_file / stream_file の
TOCTOU を完全に塞ぐには server-owned per-run directory + fd-based open が必要」
と指摘された対策の本実装。

設計 (ADR-00003 §A boundary CliArtifactAdapter):

- workdir は ``<base>/<tenant_id>/<run_id>/<launch_id>/`` で構成 (uuid4 で
  uniq)。base は registry の cwd_allowlist 先頭 + ``.cli_artifacts/`` を想定。
- workdir を ``os.makedirs(..., mode=0o700)`` で **owner-only** に作成。
- ``Path.lstat()`` で uid == os.getuid()、mode & 0o777 == 0o700 を確認。
- prompt_file は launcher 側で書き込み (caller supply の Markdown / JSON
  content)。output_file / stream_file は subprocess が書き込む。
- ``os.open(O_CREAT|O_EXCL|O_NOFOLLOW|O_WRONLY, mode=0o600)`` で事前に空 file
  を作成し、CLI が path を再 open する race を狭める。

server-owned-boundary §1 不変条件:

- ``allocate_workdir(run_id, base_dir)`` は run_id + base_dir のみ受け、path
  は server 側で構築。caller supplied path を path として受け取らない。
- 戻り値の ``PerRunWorkdir`` は frozen dataclass で immutable。
"""

from __future__ import annotations

import os
import stat
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True, slots=True)
class PerRunWorkdir:
    """Server-owned per-run artifact workdir paths."""

    workdir: str  # absolute path, mode=0o700, owner=getuid()
    prompt_file: str  # workdir/prompt.txt
    output_file: str  # workdir/output.txt
    stream_file: str  # workdir/stream.jsonl
    launch_id: str  # uuid4 hex for log correlation


def allocate_workdir(
    *,
    run_id: str,
    base_dir: str,
) -> PerRunWorkdir:
    """Allocate a per-run, owner-only workdir under ``base_dir``.

    The function:
    1. ``Path(base_dir).resolve()`` to canonicalise.
    2. Refuses to operate inside a base that is a symlink at any component.
    3. Creates ``base/<run_id>/<launch_id>/`` with mode=0o700.
    4. Validates ``lstat`` of the workdir itself afterwards (no race-able
       parent swap that would invalidate the invariant).
    5. Pre-creates ``output.txt`` / ``stream.jsonl`` with
       ``O_CREAT|O_EXCL|O_NOFOLLOW`` and mode=0o600. ``prompt.txt`` is left
       for the caller to write because its content must come from the
       validated CLI artifact body.
    """

    if not run_id or "/" in run_id or ".." in run_id:
        raise ValueError(
            f"run_id must be a non-empty identifier without path separators "
            f"or parent refs (got {run_id!r})"
        )
    candidate = Path(base_dir)
    if not candidate.is_absolute():
        raise ValueError(
            f"base_dir must be an absolute path (got {base_dir!r})"
        )

    # Walk-up symlink reject on the INPUT path BEFORE resolve() (resolve()
    # canonicalises symlinks away). Codex SP6B2 test caught the dead-code
    # check post-resolve.
    probe: Path | None = candidate
    while probe is not None and str(probe) not in ("/", ""):
        if probe.is_symlink():
            raise ValueError(
                f"base_dir parent component is a symlink ({probe!s}), "
                "refusing to allocate"
            )
        parent = probe.parent
        if parent == probe:
            break
        probe = parent

    base = candidate.resolve(strict=False)

    # Codex SP6B2 R1 F-005 (MEDIUM) adopt: base_dir 自体の ownership と mode
    # を確認。group/world writable な base は別ユーザーが parent swap で
    # workdir を hijack できる経路となるため deny。
    if base.exists():
        base_info = base.lstat()
        if base_info.st_uid != os.getuid():
            raise PermissionError(
                f"base_dir {base!s} uid {base_info.st_uid} != getuid "
                f"{os.getuid()}; refusing to allocate inside non-owned dir"
            )
        # group / world writable bit が立っていれば deny (sticky-bit /tmp は
        # 別途許可するため除外)
        mode_lo = stat.S_IMODE(base_info.st_mode)
        has_sticky = bool(base_info.st_mode & stat.S_ISVTX)
        if (mode_lo & 0o022) and not has_sticky:
            raise PermissionError(
                f"base_dir {base!s} mode {oct(mode_lo)} is group/world "
                "writable without sticky-bit; refusing to allocate"
            )

    launch_id = uuid.uuid4().hex
    run_dir = base / run_id / launch_id
    # mode=0o700 enforced via os.makedirs (umask-aware) + post-check via chmod.
    os.makedirs(run_dir, mode=0o700, exist_ok=False)
    os.chmod(run_dir, 0o700)

    workdir = run_dir.resolve(strict=True)
    info = workdir.lstat()
    if info.st_uid != os.getuid():
        raise PermissionError(
            f"workdir {workdir!s} uid {info.st_uid} != getuid {os.getuid()}"
        )
    if stat.S_IMODE(info.st_mode) != 0o700:
        raise PermissionError(
            f"workdir {workdir!s} mode {oct(stat.S_IMODE(info.st_mode))} != 0o700"
        )

    prompt_file = workdir / "prompt.txt"
    output_file = workdir / "output.txt"
    stream_file = workdir / "stream.jsonl"

    # Pre-create output / stream with O_CREAT|O_EXCL|O_NOFOLLOW so a malicious
    # parent-swap attacker cannot pre-place a symlink under our resolved path.
    _precreate_empty(output_file)
    _precreate_empty(stream_file)

    return PerRunWorkdir(
        workdir=str(workdir),
        prompt_file=str(prompt_file),
        output_file=str(output_file),
        stream_file=str(stream_file),
        launch_id=launch_id,
    )


def _precreate_empty(path: Path) -> None:
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    fd = os.open(str(path), flags, mode=0o600)
    try:
        os.fchmod(fd, 0o600)
    finally:
        os.close(fd)


def write_prompt_atomically(
    workdir: PerRunWorkdir,
    content: bytes,
) -> None:
    """Write the prompt body to ``workdir.prompt_file`` atomically.

    Uses ``O_CREAT|O_EXCL|O_NOFOLLOW`` so a race attacker cannot redirect the
    write through a symlink. The caller is responsible for canonicalising the
    content (e.g. CliArtifactPayload.body) before calling.
    """

    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    if nofollow:
        flags |= nofollow
    fd = os.open(workdir.prompt_file, flags, mode=0o600)
    try:
        os.fchmod(fd, 0o600)
        # binary write
        view = memoryview(content)
        written = 0
        while written < len(view):
            written += os.write(fd, view[written:])
    finally:
        os.close(fd)


__all__ = [
    "PerRunWorkdir",
    "allocate_workdir",
    "write_prompt_atomically",
]
