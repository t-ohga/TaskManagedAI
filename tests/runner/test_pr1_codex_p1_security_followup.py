"""Codex PR #1 R1 F-PR1-002 / F-PR1-005 P1 follow-up verify tests.

Sprint 7 / Sprint 8 R1 で見落とされた P1 finding の fix を verify する。
"""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

import pytest

from backend.app.services.runner.runner_adapter import _collect_files_sync


class TestSymlinkArtifactReject:
    """F-PR1-005 P1 adopt: artifact 収集時に symlink reject + workspace
    containment check (host file exfiltration 防止)."""

    def test_regular_files_are_collected(self, tmp_path: Path) -> None:
        """workspace 内通常 file は変わらず収集される (regression check)."""
        (tmp_path / "a.txt").write_text("hello")
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "b.log").write_text("log")

        results = _collect_files_sync(str(tmp_path))
        names = {Path(p).name for p in results}
        assert names == {"a.txt", "b.log"}

    def test_symlink_to_host_file_is_rejected(self, tmp_path: Path) -> None:
        """workspace 内 symlink を /etc/passwd 等 host file に向けて作成しても
        artifact として収集されない (P1 fix verify)."""
        (tmp_path / "regular.txt").write_text("ok")
        host_target = "/etc/passwd"
        if not Path(host_target).exists():
            pytest.skip("host /etc/passwd not present on this OS")
        (tmp_path / "passwd_link").symlink_to(host_target)

        results = _collect_files_sync(str(tmp_path))
        names = {Path(p).name for p in results}
        assert "passwd_link" not in names, "symlink to host file must be rejected"
        assert "regular.txt" in names

    def test_symlink_within_workspace_is_rejected_too(
        self, tmp_path: Path
    ) -> None:
        """workspace 内 file への symlink でも、symlink 自体は reject
        (paranoid 防御、symlink 経由の duplicate / loop attack 防止)."""
        target = tmp_path / "real.txt"
        target.write_text("real content")
        (tmp_path / "alias.txt").symlink_to(target)

        results = _collect_files_sync(str(tmp_path))
        names = {Path(p).name for p in results}
        assert "real.txt" in names
        assert "alias.txt" not in names, "symlink itself must be rejected"

    def test_directory_traversal_via_symlink_blocked(self, tmp_path: Path) -> None:
        """workspace 外 dir への symlink 経由で外部 file を artifact 化できない."""
        outside = tmp_path.parent / "outside_workdir"
        outside.mkdir()
        (outside / "secret.txt").write_text("SECRET")
        (tmp_path / "escape").symlink_to(outside)

        results = _collect_files_sync(str(tmp_path))
        paths = [Path(p) for p in results]
        for p in paths:
            # 全 collected path が workspace 配下 (resolve 後) であること
            resolved = p.resolve()
            assert tmp_path.resolve() in resolved.parents or resolved == tmp_path.resolve(), (
                f"collected path escaped workspace: {resolved}"
            )

        try:
            (outside / "secret.txt").unlink()
            outside.rmdir()
        except OSError:
            pass


class TestPrOpenApprovalRefBindsCommitSha:
    """F-PR1-002 P1 adopt: repo.pr_open の resource_ref に commit_sha /
    repo_state_commit_sha を含め、approval が stale repo state を再利用できない."""

    def _make_target(
        self,
        *,
        commit_sha: str = "a" * 40,
        repo_state_commit_sha: str = "b" * 40,
    ) -> Mapping[str, object]:
        return {
            "repo_full_name": "owner/repo",
            "base_branch": "main",
            "head_branch": "feature-1",
            "draft": True,
            "commit_sha": commit_sha,
            "repo_state_commit_sha": repo_state_commit_sha,
        }

    def test_ref_includes_commit_sha_and_repo_state_commit_sha(self) -> None:
        """生成される resource_ref に commit / state が含まれること."""
        from backend.app.services.secrets.broker import _operation_target_to_ref

        ref = _operation_target_to_ref(self._make_target(), "repo.pr_open")
        assert ":commit:" in ref
        assert "a" * 40 in ref
        assert ":state:" in ref
        assert "b" * 40 in ref

    def test_ref_differs_when_commit_sha_changes(self) -> None:
        """同 PR (base/head/repo) でも commit_sha が違えば ref が違う = approval 再利用不可."""
        from backend.app.services.secrets.broker import _operation_target_to_ref

        ref_old = _operation_target_to_ref(
            self._make_target(commit_sha="a" * 40), "repo.pr_open"
        )
        ref_new = _operation_target_to_ref(
            self._make_target(commit_sha="c" * 40), "repo.pr_open"
        )
        assert ref_old != ref_new, "stale commit_sha must produce different approval ref"

    def test_ref_differs_when_repo_state_commit_sha_changes(self) -> None:
        """repo_state_commit_sha だけ違っても ref が違う = stale repo state 再利用不可."""
        from backend.app.services.secrets.broker import _operation_target_to_ref

        ref_old = _operation_target_to_ref(
            self._make_target(repo_state_commit_sha="b" * 40), "repo.pr_open"
        )
        ref_new = _operation_target_to_ref(
            self._make_target(repo_state_commit_sha="d" * 40), "repo.pr_open"
        )
        assert ref_old != ref_new, (
            "stale repo_state_commit_sha must produce different approval ref"
        )

    def test_missing_commit_sha_raises_denied(self) -> None:
        """commit_sha 欠落で BrokerIssueDenied('approval_target_mismatch')."""
        from backend.app.services.secrets.broker import (
            BrokerIssueDenied,
            _operation_target_to_ref,
        )

        target = dict(self._make_target())
        target.pop("commit_sha")
        with pytest.raises(BrokerIssueDenied):
            _operation_target_to_ref(target, "repo.pr_open")
