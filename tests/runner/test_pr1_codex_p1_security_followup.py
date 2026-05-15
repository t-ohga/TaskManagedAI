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



class TestWorkspaceRootSymlinkReject:
    """F-PR8-001 P1 adopt (PR #8 R2): workspace root 自身が symlink に置換
    されていても host file を artifact 化しない (Codex 検証: 現状 code
    は `_collect_files_sync('/etc')` で `/etc/passwd` を collect する)."""

    def test_workspace_root_as_symlink_to_host_dir_returns_empty(
        self, tmp_path: Path
    ) -> None:
        """workspace root が `/etc` への symlink になっていれば return ()."""
        # 別 dir を作ってその下に target を置く (`/etc` 直接使わず in-test 安全)
        host_like = tmp_path.parent / "fake_host_etc"
        host_like.mkdir(exist_ok=True)
        (host_like / "passwd").write_text("root:x:0:0::/root:/bin/sh")

        # workspace path が symlink で host-like dir を指す
        ws_path = tmp_path / "ws_link"
        ws_path.symlink_to(host_like)

        results = _collect_files_sync(str(ws_path))
        assert results == (), (
            f"workspace root as symlink must return (), got: {results}"
        )

        try:
            (host_like / "passwd").unlink()
            host_like.rmdir()
        except OSError:
            pass

    def test_regular_workspace_root_still_works(self, tmp_path: Path) -> None:
        """workspace root が通常 dir なら通常動作 (regression check)."""
        (tmp_path / "out.txt").write_text("hello")
        results = _collect_files_sync(str(tmp_path))
        names = {Path(p).name for p in results}
        assert "out.txt" in names


class TestPrOpenRefGitShaValidation:
    """F-PR8-002 P2 adopt (PR #8 R2): commit_sha / repo_state_commit_sha を
    git SHA hex format (40 or 64 char) として validate し、`:` 等 separator
    含む value で resource_ref が ambiguity を生まないようにする."""

    def test_commit_sha_with_colon_rejected(self) -> None:
        from backend.app.services.secrets.broker import (
            BrokerIssueDenied,
            _operation_target_to_ref,
        )

        target = {
            "repo_full_name": "owner/repo",
            "base_branch": "main",
            "head_branch": "feature-1",
            "draft": True,
            "commit_sha": "a:state:b",  # `:` 含む invalid value
            "repo_state_commit_sha": "c" * 40,
        }
        with pytest.raises(BrokerIssueDenied):
            _operation_target_to_ref(target, "repo.pr_open")

    def test_short_commit_sha_rejected(self) -> None:
        from backend.app.services.secrets.broker import (
            BrokerIssueDenied,
            _operation_target_to_ref,
        )

        target = {
            "repo_full_name": "owner/repo",
            "base_branch": "main",
            "head_branch": "feature-1",
            "draft": True,
            "commit_sha": "abc123",  # 6 char、SHA hex として短い
            "repo_state_commit_sha": "c" * 40,
        }
        with pytest.raises(BrokerIssueDenied):
            _operation_target_to_ref(target, "repo.pr_open")

    def test_sha256_64char_accepted(self) -> None:
        """SHA-256 hex (64 char) も accept される."""
        from backend.app.services.secrets.broker import _operation_target_to_ref

        target = {
            "repo_full_name": "owner/repo",
            "base_branch": "main",
            "head_branch": "feature-1",
            "draft": True,
            "commit_sha": "a" * 64,
            "repo_state_commit_sha": "b" * 64,
        }
        ref = _operation_target_to_ref(target, "repo.pr_open")
        assert "a" * 64 in ref
        assert "b" * 64 in ref


class TestShellScriptOperandStopsScanning:
    """F-PR8-003 P2 adopt (PR #8 R2): shell の script operand に到達したら
    以降の引数を inline exec として scan しない (誤検出回避)."""

    @pytest.mark.parametrize(
        "argv",
        [
            # script file + 引数 (誤検出されてはならない)
            ("bash", "scripts/build.sh", "-config", "local"),
            ("sh", "deploy.sh", "-clean"),
            ("zsh", "lib/setup.zsh", "-c-style-arg"),
            # `--` で option parsing 終了
            ("bash", "--", "-c", "danger"),
            ("sh", "--", "command-with-c"),
        ],
    )
    def test_shell_script_operand_not_inline_exec(
        self, argv: tuple[str, ...]
    ) -> None:
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        # INLINE_EXEC として誤検出されないこと (他 deny reason はあっても OK)
        if violation is not None:
            assert violation.reason != DangerousCommandDenyReason.INLINE_EXEC, (
                f"shell script operand must not trigger INLINE_EXEC, got: {violation}"
            )

    @pytest.mark.parametrize(
        "argv",
        [
            # 既存 detect は維持 (regression check)
            ("bash", "-c", "rm -rf /"),
            ("bash", "-lc", "rm -rf /"),
            ("bash", "--norc", "-c", "rm -rf /"),
        ],
    )
    def test_shell_inline_exec_still_detected(self, argv: tuple[str, ...]) -> None:
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        assert violation is not None
        assert violation.reason == DangerousCommandDenyReason.INLINE_EXEC



class TestShellOptionWithArgumentNotMistakenAsScript:
    """F-PR8-004 P1 adopt (PR #8 R2): option-with-argument 型 option
    (`-o option` / `-O shopt` / `--rcfile file` / `--init-file file`) の
    argument を script operand と誤認して inline -c 検出を bypass しない。
    GNU Bash docs (Invoking-Bash) 準拠で 2-token consume。"""

    @pytest.mark.parametrize(
        "argv",
        [
            # bash -o option -c cmd
            ("bash", "-o", "pipefail", "-c", "rm -rf /"),
            ("bash", "-o", "errexit", "-c", "rm -rf /"),
            # bash -O shopt -c cmd
            ("bash", "-O", "extglob", "-c", "rm -rf /"),
            ("bash", "-O", "nullglob", "-c", "rm -rf /"),
            # bash --rcfile file -c cmd
            ("bash", "--rcfile", "/dev/null", "-c", "rm -rf /"),
            ("bash", "--init-file", "./fake-init", "-c", "rm -rf /"),  # noqa: S108
            # combined: multiple option-with-argument before -c
            ("bash", "-o", "pipefail", "-O", "extglob", "-c", "rm -rf /"),
            # `--rcfile=val` (= 結合) でも detect される (= 単一 token)
            ("bash", "--rcfile=/dev/null", "-c", "rm -rf /"),
            # sh / zsh も同じ
            ("sh", "-o", "errexit", "-c", "rm -rf /"),
            ("zsh", "-o", "errexit", "-c", "rm -rf /"),
        ],
    )
    def test_inline_exec_after_option_with_argument(
        self, argv: tuple[str, ...]
    ) -> None:
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        assert violation is not None, f"must detect inline exec: {argv}"
        assert violation.reason == DangerousCommandDenyReason.INLINE_EXEC, (
            f"must be INLINE_EXEC: {argv}, got {violation.reason}"
        )

    @pytest.mark.parametrize(
        "argv",
        [
            # script.sh + -config (option-with-argument の argument ではない)
            ("bash", "scripts/build.sh", "-config", "local"),
            # `--` 以降は引数、`-c` も無視 (POSIX 準拠)
            ("bash", "-o", "errexit", "--", "-c", "harmless"),
            # -o option script.sh -- 以降は scan しない
            ("bash", "-o", "pipefail", "script.sh", "-config", "local"),
        ],
    )
    def test_no_false_positive_after_consumption(
        self, argv: tuple[str, ...]
    ) -> None:
        """option-with-argument を正しく consume した後の script operand は
        誤検出されない (regression check)."""
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        if violation is not None:
            assert violation.reason != DangerousCommandDenyReason.INLINE_EXEC, (
                f"must NOT be INLINE_EXEC: {argv}, got {violation.reason}"
            )



class TestShellPlusOAndEmulateAndCaseSensitive:
    """F-PR8-005 / F-PR8-006 / F-PR8-007 P1+P2 adopt (PR #8 R3):
    - `+o` / `+O` (bash shell option disable) も option-with-argument
    - 大文字 `-C` (bash restricted file mode) は inline-exec ではない
    - zsh `--emulate <mode>` も option-with-argument
    """

    @pytest.mark.parametrize(
        "argv",
        [
            # bash +o option -c cmd (F-PR8-005 P1)
            ("bash", "+o", "errexit", "-c", "rm -rf /"),
            ("bash", "+O", "nullglob", "-c", "rm -rf /"),
            # bash -o + +o 混在
            ("bash", "-o", "pipefail", "+o", "errexit", "-c", "rm -rf /"),
            # zsh --emulate <mode> -c cmd (F-PR8-007 P1)
            ("zsh", "--emulate", "sh", "-c", "rm -rf /"),
            ("zsh", "--emulate", "ksh", "-c", "rm -rf /"),
            # bash --rcfile + --emulate (combine)
            ("zsh", "--emulate", "sh", "--rcfile", "/dev/null", "-c", "rm -rf /"),
        ],
    )
    def test_plus_o_and_emulate_still_detect_inline(
        self, argv: tuple[str, ...]
    ) -> None:
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        assert violation is not None, f"must detect inline_exec: {argv}"
        assert violation.reason == DangerousCommandDenyReason.INLINE_EXEC, (
            f"must be INLINE_EXEC: {argv}, got {violation.reason}"
        )

    @pytest.mark.parametrize(
        "argv",
        [
            # bash -C (uppercase, restricted file mode) は inline_exec ではない (F-PR8-006 P2)
            ("bash", "-C", "script.sh"),
            ("bash", "-eC", "script.sh"),
            ("bash", "-EC", "script.sh", "arg"),
            # mixed grouped opts: -e/-E は OK (`c` 含まない)、`-C` 大文字も OK
            ("bash", "-EC", "deploy.sh"),
        ],
    )
    def test_uppercase_C_not_detected_as_inline(self, argv: tuple[str, ...]) -> None:
        """`bash -eC script.sh` 等の大文字 C 含む grouped option を inline_exec
        と誤検出しない (canonicalize で lower 化されるため、raw rest を使い
        case-sensitive に判定)."""
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        if violation is not None:
            assert violation.reason != DangerousCommandDenyReason.INLINE_EXEC, (
                f"must NOT be INLINE_EXEC for uppercase C: {argv}, got {violation.reason}"
            )



class TestFishInitCommandInline:
    """F-PR8-008 P1 adopt (PR #8 R4): fish の `-C` / `--init-command=<cmd>` も
    inline command 評価 (fish docs)、bypass を防ぐ。"""

    @pytest.mark.parametrize(
        "argv",
        [
            ("fish", "-C", "rm -rf /"),
            ("fish", "-c", "rm -rf /"),
            ("fish", "--init-command=rm -rf /"),
            ("fish", "--init-command", "rm -rf /"),
            ("fish", "-i", "-C", "rm -rf /"),
        ],
    )
    def test_fish_inline_detected(self, argv: tuple[str, ...]) -> None:
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        assert violation is not None, f"fish inline must be detected: {argv}"
        assert violation.reason == DangerousCommandDenyReason.INLINE_EXEC

    @pytest.mark.parametrize(
        "argv",
        [
            ("fish", "script.fish"),
            ("fish", "-i"),
            ("fish", "--no-config"),
        ],
    )
    def test_fish_non_inline_not_detected(self, argv: tuple[str, ...]) -> None:
        from backend.app.services.runner.dangerous_command import (
            DangerousCommandDenyReason,
            detect_dangerous_command,
        )

        violation = detect_dangerous_command(argv)
        if violation is not None:
            assert violation.reason != DangerousCommandDenyReason.INLINE_EXEC, (
                f"fish non-inline must NOT be INLINE_EXEC: {argv}"
            )
