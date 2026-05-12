"""Sprint 6 Batch 2: per_run_workdir の server-owned 境界テスト。"""

from __future__ import annotations

import os
import stat
import uuid
from pathlib import Path

import pytest

from backend.app.services.cli_artifact import per_run_workdir
from backend.app.services.cli_artifact.per_run_workdir import (
    PerRunWorkdir,
    allocate_workdir,
    write_prompt_atomically,
)


@pytest.fixture(autouse=True)
def _skip_windows() -> None:
    """POSIX file mode と symlink 前提のため Windows では実行しない。"""

    if os.name == "nt":
        pytest.skip("per_run_workdir tests require POSIX file mode semantics")


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _allocate(tmp_path: Path, *, run_id: str = "run-aaaaaaaa") -> PerRunWorkdir:
    return allocate_workdir(run_id=run_id, base_dir=str(tmp_path))


def test_allocate_workdir_creates_owner_only_dir(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    info = Path(workdir.workdir).stat()
    assert _mode(Path(workdir.workdir)) == 0o700
    assert info.st_uid == os.getuid()


def test_allocate_workdir_creates_output_and_stream_files(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    output = Path(workdir.output_file)
    stream = Path(workdir.stream_file)
    assert output.is_file()
    assert stream.is_file()
    assert _mode(output) == 0o600
    assert _mode(stream) == 0o600


def test_allocate_workdir_prompt_file_not_pre_created(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    assert Path(workdir.prompt_file).exists() is False


def test_allocate_workdir_uses_uuid_launch_id(tmp_path: Path) -> None:
    first = _allocate(tmp_path, run_id="run-bbbbbbbb")
    second = _allocate(tmp_path, run_id="run-bbbbbbbb")

    assert first.launch_id != second.launch_id
    assert Path(first.workdir) != Path(second.workdir)
    assert Path(first.workdir).parent == Path(second.workdir).parent
    assert uuid.UUID(first.launch_id).hex == first.launch_id
    assert uuid.UUID(second.launch_id).hex == second.launch_id


def test_allocate_workdir_rejects_empty_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        allocate_workdir(run_id="", base_dir=str(tmp_path))


def test_allocate_workdir_rejects_path_separator_in_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        allocate_workdir(run_id="run/aaaaaaaa", base_dir=str(tmp_path))


def test_allocate_workdir_rejects_parent_ref_in_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_id"):
        allocate_workdir(run_id="run..aaaaaaaa", base_dir=str(tmp_path))


def test_allocate_workdir_rejects_relative_base_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="base_dir"):
        allocate_workdir(run_id="run-aaaaaaaa", base_dir="relative-base")


def test_allocate_workdir_rejects_symlink_base_dir(tmp_path: Path) -> None:
    real_base = tmp_path / "real-base"
    real_base.mkdir()
    symlink_base = tmp_path / "base-link"
    os.symlink(real_base, symlink_base)

    with pytest.raises(ValueError, match="symlink"):
        allocate_workdir(run_id="run-aaaaaaaa", base_dir=str(symlink_base))


def test_allocate_workdir_existing_dir_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    fixed_uuid = uuid.UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa")
    monkeypatch.setattr(per_run_workdir.uuid, "uuid4", lambda: fixed_uuid)
    existing = tmp_path / "run-aaaaaaaa" / fixed_uuid.hex
    existing.mkdir(parents=True)

    with pytest.raises(FileExistsError):
        allocate_workdir(run_id="run-aaaaaaaa", base_dir=str(tmp_path))


def test_write_prompt_atomically_writes_content_with_mode_0600(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)
    content = b"validated prompt body\n"

    write_prompt_atomically(workdir, content)

    prompt = Path(workdir.prompt_file)
    assert prompt.read_bytes() == content
    assert _mode(prompt) == 0o600


def test_write_prompt_atomically_refuses_to_overwrite(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)
    prompt = Path(workdir.prompt_file)
    prompt.write_bytes(b"original")

    with pytest.raises(FileExistsError):
        write_prompt_atomically(workdir, b"replacement")

    assert prompt.read_bytes() == b"original"


def test_write_prompt_atomically_refuses_symlink(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)
    target = tmp_path / "target.txt"
    target.write_bytes(b"target")
    os.symlink(target, workdir.prompt_file)

    with pytest.raises(OSError):
        write_prompt_atomically(workdir, b"must not follow")

    assert target.read_bytes() == b"target"


def test_per_run_workdir_dataclass_is_frozen(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    with pytest.raises(AttributeError):
        workdir.launch_id = "mutated"


def test_workdir_resolved_path_contains_run_id_and_launch_id(tmp_path: Path) -> None:
    run_id = "run-cccccccc"
    workdir = _allocate(tmp_path, run_id=run_id)
    parts = Path(workdir.workdir).parts

    assert run_id in parts
    assert workdir.launch_id in parts


def test_pre_created_output_has_size_zero(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    assert Path(workdir.output_file).stat().st_size == 0


def test_pre_created_stream_has_size_zero(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    assert Path(workdir.stream_file).stat().st_size == 0


def test_allocate_workdir_chmod_700_enforced_even_with_umask(tmp_path: Path) -> None:
    old_umask = os.umask(0o077)
    try:
        workdir = _allocate(tmp_path)
    finally:
        os.umask(old_umask)

    assert _mode(Path(workdir.workdir)) == 0o700


def test_workdir_is_inside_resolved_base(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    base = tmp_path.resolve(strict=True)
    resolved_workdir = Path(workdir.workdir).resolve(strict=True)
    assert resolved_workdir.is_relative_to(base)


def test_allocate_workdir_returns_absolute_paths(tmp_path: Path) -> None:
    workdir = _allocate(tmp_path)

    assert Path(workdir.workdir).is_absolute()
    assert Path(workdir.prompt_file).is_absolute()
    assert Path(workdir.output_file).is_absolute()
    assert Path(workdir.stream_file).is_absolute()

