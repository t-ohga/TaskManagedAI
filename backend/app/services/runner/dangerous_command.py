"""Sprint 7 BL-0073: dangerous command parser + denylist (AC-HARD-06 boundary).

ADR-00008 §dangerous command denylist 15 種を canonical form で検出。
Sprint 6 batch 1 launcher の ``shell=False`` 強制 + argv allowlist と組み合わせ、
runner sandbox 内で実行する command を fail-closed reject。

設計:

- ``detect_dangerous_command(argv)`` は argv ``Sequence[str]`` を入力に取り、
  ``DangerousCommandViolation | None`` を返す。
- shell metachar (`;`, `&&`, `||`, `|`, `` ` ``, `$(...)`) を含む argv は **元の
  argv に分解する責任は caller 側** で、本 module は argv elements を
  canonical form (lowercase / decoded) に正規化して denylist と比較する。
- base64 decode pattern (`base64 -d | sh` 等) は argv pair を check。
- shell=False 強制は launcher / runner 側で行う前提、本 module は string-level
  detection を最小実装する。
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum

from backend.app.services.runner.forbidden_path import canonicalize_path


class DangerousCommandDenyReason(StrEnum):
    RM_RF = "rm_rf"
    FIND_DELETE = "find_delete"
    CURL_PIPE_SH = "curl_pipe_sh"
    CHMOD_777 = "chmod_777"
    CHOWN_RECURSIVE = "chown_recursive"
    DD_OVERWRITE = "dd_overwrite"
    MKFS = "mkfs"
    DOCKER_PRIVILEGED = "docker_privileged"
    DOCKER_EXEC = "docker_exec"
    DOCKER_SOCKET_MOUNT = "docker_socket_mount"  # Codex SP7 R1 F-004
    DOCKER_HOST_NETWORK = "docker_host_network"  # Codex SP7 R1 F-004
    MOUNT_UMOUNT = "mount_umount"
    FORK_BOMB = "fork_bomb"
    BASE64_DECODE_EXEC = "base64_decode_exec"
    DOCKER_SOCKET_CURL = "docker_socket_curl"
    SUDO_SU = "sudo_su"
    IPTABLES_UFW = "iptables_ufw"
    KILL_INIT = "kill_init"
    INLINE_EXEC = "inline_exec"  # Codex SP7 R2 F-001
    EMPTY_ARGV = "empty_argv"


@dataclass(frozen=True, slots=True)
class DangerousCommandViolation:
    argv: tuple[str, ...]
    canonical_argv: tuple[str, ...]
    reason: DangerousCommandDenyReason


_FORK_BOMB_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r":\(\)\s*\{\s*:\|:\&\s*\}\s*;\s*:"),
    re.compile(r"\.\(\)\s*\{\s*\.\|\.\&\s*\}\s*;\s*\."),
)

_BASE64_PIPE_PATTERN = re.compile(
    r"base64\s+(?:-d|--decode)", re.IGNORECASE
)
_CURL_PIPE_PATTERN = re.compile(
    r"(curl|wget)\s+.*\|\s*(sh|bash|zsh|sh\s+-)", re.IGNORECASE
)


def canonicalize_command(argv: Sequence[str]) -> tuple[str, ...]:
    """argv elements を canonical form に正規化する。

    各 element に対し:
    1. Unicode Cc/Cf strip + NFC normalize (forbidden_path.canonicalize_path
       と同じ前処理)
    2. lowercase (case-insensitive 比較のため)
    3. **Codex SP7 R1 F-005 adopt**: 1 要素目 (command name) が absolute path
       なら basename を採用 (`/bin/rm` -> `rm`)、wrapper (`env` / `nohup` /
       `command`) は次の argument を unwrap。``sh -c "rm -rf /"`` のような
       shell unwrap は P0 では複雑なので **`sh|bash|zsh -c` 自体を別 reason
       で deny する** ことで対応 (本 module の deny set に shell_inline_exec
       を追加する代わり、command name basename pattern で対応)。
    """

    if not argv:
        return ()
    cleaned = [canonicalize_path(arg).lower() for arg in argv if arg]
    if not cleaned:
        return ()

    def _basename(value: str) -> str:
        if " " in value or "\t" in value:
            return value
        if value.startswith("/") or "/" in value:
            return value.rsplit("/", 1)[-1]
        return value

    name = _basename(cleaned[0])
    rest = cleaned[1:]
    wrapper_set = {"env", "nohup", "command", "builtin", "exec", "time"}
    for _ in range(5):
        if name not in wrapper_set or not rest:
            break
        if name == "env":
            # Codex SP7 R4 F-001 adopt: env option consumer を robust 化。
            # 既知の env option / assignment を skip、`--` 出現で operand
            # section に移行、未知 option は fail-closed (skip しない、
            # wrapper unwrap loop を抜けて inline_exec / regular checker に
            # 落とす)。
            # `-S` / `--split-string` は dangerous なので、env unwrap 経由
            # ではなく直接 INLINE_EXEC sentinel として `env -S ...` を残す。
            sentinel_inline = False
            consumed_terminator = False
            while rest:
                arg = rest[0]
                if arg == "--":
                    rest = rest[1:]
                    consumed_terminator = True
                    break
                if arg in {"-i", "--ignore-environment", "--null", "-0"}:
                    rest = rest[1:]
                elif arg in {"-u"} and len(rest) >= 2:
                    rest = rest[2:]
                elif arg.startswith("--unset="):
                    rest = rest[1:]
                elif arg in {"-c", "-C"} and len(rest) >= 2:
                    rest = rest[2:]
                elif arg.startswith("--chdir="):
                    rest = rest[1:]
                elif arg in {"-a"} and len(rest) >= 2:
                    rest = rest[2:]
                elif arg.startswith("--argv0="):
                    rest = rest[1:]
                elif arg in {"-s", "--split-string"} or arg.startswith("--split-string="):
                    sentinel_inline = True
                    rest = rest[0:]
                    break
                elif "=" in arg and not arg.startswith("-"):
                    rest = rest[1:]
                elif arg.startswith("-"):
                    # 未知の env option は fail-closed: env unwrap を止め、
                    # 残る argv を inline_exec / regular checker に流す。
                    break
                else:
                    break
            if sentinel_inline:
                # env -S は INLINE_EXEC として扱うため、canonical_argv の
                # 先頭を仮想 "env-split-string" として残す (matcher が
                # `_matches_inline_exec` で識別)。
                return ("env-split-string", *rest)
            if not rest or (consumed_terminator and not rest):
                break
        name = _basename(rest[0])
        rest = rest[1:]
    return (name, *rest)


def _matches_rm_rf(canonical_argv: tuple[str, ...]) -> bool:
    if not canonical_argv or canonical_argv[0] != "rm":
        return False
    # rm -rf / rm -fr / rm -r -f / rm --recursive --force
    has_recursive = any(
        a in {"-r", "-rf", "-fr", "--recursive"} or "r" in a.lstrip("-")
        for a in canonical_argv[1:]
        if a.startswith("-")
    )
    has_force = any(
        a in {"-f", "--force"} or "f" in a.lstrip("-")
        for a in canonical_argv[1:]
        if a.startswith("-")
    )
    return has_recursive and has_force


def _matches_find_delete(canonical_argv: tuple[str, ...]) -> bool:
    return (
        len(canonical_argv) >= 2
        and canonical_argv[0] == "find"
        and any(a == "-delete" for a in canonical_argv[1:])
    )


def _matches_chmod_777(canonical_argv: tuple[str, ...]) -> bool:
    if not canonical_argv or canonical_argv[0] != "chmod":
        return False
    return any(a == "777" or a.endswith("777") for a in canonical_argv[1:])


def _matches_chown_recursive(canonical_argv: tuple[str, ...]) -> bool:
    if not canonical_argv or canonical_argv[0] != "chown":
        return False
    return any(
        a in {"-r", "-rh", "-hr", "--recursive"} or "r" in a.lstrip("-")
        for a in canonical_argv[1:]
        if a.startswith("-")
    )


def _matches_dd_overwrite(canonical_argv: tuple[str, ...]) -> bool:
    if not canonical_argv or canonical_argv[0] != "dd":
        return False
    return any(a.startswith("of=") for a in canonical_argv[1:])


def _matches_mkfs(canonical_argv: tuple[str, ...]) -> bool:
    return bool(canonical_argv) and canonical_argv[0].startswith("mkfs")


def _is_docker_invocation(canonical_argv: tuple[str, ...]) -> bool:
    """`docker ...` / `docker compose ...` のどちらかを認識。"""

    return bool(canonical_argv) and canonical_argv[0] == "docker"


def _matches_docker_privileged(canonical_argv: tuple[str, ...]) -> bool:
    """Codex SP7 audit F-SP7-006 adopt: `--privileged` だけでなく `--privileged=true` /
    `--privileged=yes` / `--privileged=1` を全て検出する。Docker CLI は flag=value form
    も受け付けるため、joined string match で robust 化。"""

    if not _is_docker_invocation(canonical_argv):
        return False
    # 単独 flag
    if any(a == "--privileged" for a in canonical_argv[1:]):
        return True
    # `--privileged=<value>` form (true / yes / 1 / on は実質有効)
    return any(
        a.startswith("--privileged=") and a.split("=", 1)[1].lower() in {"true", "yes", "1", "on"}
        for a in canonical_argv[1:]
    )


def _matches_docker_exec(canonical_argv: tuple[str, ...]) -> bool:
    if not _is_docker_invocation(canonical_argv):
        return False
    # docker exec / docker container exec / docker compose exec
    rest = canonical_argv[1:]
    return any(
        a == "exec" for a in rest[:3]
    )


def _matches_docker_socket_mount(canonical_argv: tuple[str, ...]) -> bool:
    """Codex SP7 R1 F-004 + SP7 audit F-SP7-006 adopt: docker run/exec で host
    docker socket を bind mount。

    Detect patterns (case-insensitive after canonicalize):
    - ``-v /var/run/docker.sock:...`` (short volume)
    - ``--volume /var/run/docker.sock:...`` / ``--volume=docker.sock:...``
    - ``--mount type=bind,src=/var/run/docker.sock,...`` (Codex F-SP7-006)
    - ``--mount type=bind,source=...docker.sock,...`` (alias `source=`)
    - ``--mount=type=bind,src=...docker.sock`` (`=` separator)
    """

    if not _is_docker_invocation(canonical_argv):
        return False
    joined = " ".join(canonical_argv)
    # -v / --volume / --mount with src= or source= referring to docker.sock
    patterns = (
        r"(?:-v\s+|--volume[\s=])[^ ]*docker\.sock",
        r"--mount[\s=][^ ]*(?:src|source)=[^ ,]*docker\.sock",
    )
    return any(re.search(p, joined) for p in patterns)


def _matches_docker_host_network(canonical_argv: tuple[str, ...]) -> bool:
    """Codex SP7 R1 F-004: docker run --network host / --net=host。"""

    if not _is_docker_invocation(canonical_argv):
        return False
    joined = " ".join(canonical_argv)
    return bool(
        re.search(r"(?:--network[\s=]host|--net[\s=]host)\b", joined)
    )


def _matches_mount_umount(canonical_argv: tuple[str, ...]) -> bool:
    return bool(canonical_argv) and canonical_argv[0] in {"mount", "umount"}


def _matches_sudo_su(canonical_argv: tuple[str, ...]) -> bool:
    return bool(canonical_argv) and canonical_argv[0] in {"sudo", "su"}


def _matches_iptables_ufw(canonical_argv: tuple[str, ...]) -> bool:
    return bool(canonical_argv) and canonical_argv[0] in {"iptables", "ufw"}


def _matches_inline_exec(canonical_argv: tuple[str, ...]) -> bool:
    """Codex SP7 R2 F-001 adopt: shell/interpreter inline exec を deny。

    inline-exec pattern (e.g. `sh -c 'rm -rf /'`, `python -c "import os; ..."`)
    は内部 payload が canonical command parser に**再投入**されないため、
    任意 dangerous command を bypass できる。本 checker で wholesale deny し、
    workspace 内に作成した script file を経由する形を強制する (ADR-00008
    準拠)。
    """

    if not canonical_argv:
        return False
    name = canonical_argv[0]
    rest = canonical_argv[1:]
    # shell inline (-c)
    if name in {"sh", "bash", "zsh", "dash", "ash", "ksh", "fish"}:
        return any(a == "-c" for a in rest)
    # python inline (-c)
    if name in {"python", "python2", "python3"}:
        return any(a == "-c" for a in rest)
    # node / ruby / perl / lua / php inline
    if name in {"node", "nodejs", "deno", "bun"}:
        return any(a in {"-e", "--eval"} for a in rest)
    if name in {"ruby"}:
        return any(a == "-e" for a in rest)
    if name in {"perl"}:
        return any(a == "-e" for a in rest)
    if name in {"lua", "luajit"}:
        return any(a == "-e" for a in rest)
    if name in {"php"}:
        return any(a == "-r" for a in rest)
    # Codex SP7 R3 F-002 adopt: 追加 interpreter coverage
    # awk: system("...") pattern を allow しない (free-form pattern)
    if name in {"awk", "gawk", "mawk", "nawk"}:
        # awk 'BEGIN { system("rm -rf /") }' → BEGIN script に system call
        # awk script の中身を parse できないため、awk 呼出し自体を deny
        # (`-f script.awk` で外部 script 経由なら別 path validation で扱う)
        return True
    # expect / tclsh inline
    if name in {"expect", "tclsh", "wish"}:
        return any(a in {"-c", "-e"} for a in rest)
    # R / Rscript inline (-e)
    if name in {"r", "rscript"}:
        return any(a == "-e" for a in rest)
    # osascript inline (-e、AppleScript Mac)
    if name in {"osascript"}:
        return any(a == "-e" for a in rest)
    # eval / source / `.` builtin
    if name in {"eval", "source", "."}:
        return True
    # Codex SP7 R4 F-001 adopt: env -S split-string sentinel
    if name == "env-split-string":
        return True
    # Codex SP7 R5 F-001 adopt: find -exec / -execdir は任意 command 実行
    # に delegate するため fail-closed deny。
    if name == "find" and any(a in {"-exec", "-execdir"} for a in rest):
        return True
    # 他の delegated execution patterns (carpet-bomb)
    # - xargs: -I {} command
    # - parallel: -j N command
    # - watch: command を反復実行
    # - timeout: command 実行
    # - nice: command 実行
    # - chrt: command 実行
    if name in {"xargs", "parallel", "watch", "timeout", "nice", "chrt"}:
        return True
    # Codex SP7 R6 F-001 adopt: SSH / SCP / TMUX / interactive editor 系
    # の delegated / interactive runtimes も wholesale deny (Sprint 8 で
    # strict allowlist に移行するまでの暫定策)。
    # - ssh / sftp / scp / mosh: remote command execution
    # - tmux / screen / dtach: pty multiplexer (send-keys 経由で command)
    # - vim / vi / nvim / view / emacs / mg: editor + shell escape
    # - less / more / most: pager + shell escape (`!cmd`)
    # - man / info / pinfo: shell escape via PAGER
    # - mail / mutt: shell escape via `~!cmd`
    # - gdb / lldb / strace / ltrace: debugger + shell command
    if name in {
        "ssh", "sftp", "scp", "mosh",
        "tmux", "screen", "dtach",
        "vim", "vi", "nvim", "view", "emacs", "mg", "ed",
        "less", "more", "most", "w3m",
        "man", "info", "pinfo",
        "mail", "mutt", "neomutt",
        "gdb", "lldb", "strace", "ltrace", "dtrace",
        "ftp", "telnet", "nc", "ncat", "socat",
        "byobu",
    }:
        return True
    # Codex SP7 R4 F-002 adopt: **carpet-bomb** fallback。
    # 列挙されていない command でも inline-eval 系 flag (`-e` / `--eval` /
    # `-c` / `--command` / `-Command` / `-r`) が rest に出現すれば
    # fail-closed deny。groovy / scala / ghci / swift / julia / clojure /
    # kotlin / pwsh / powershell / 等の追加 runtime を網羅。
    _SAFE_KNOWN_COMMANDS: frozenset[str] = frozenset(
        {
            # ファイル操作 / 基本 utility (本 fallback で false positive を
            # 避けるため除外。これらは別 dangerous matcher で扱う)
            "echo", "ls", "cat", "cp", "mv", "mkdir", "touch", "pwd", "true",
            "false", "test", "sleep", "head", "tail", "wc", "sort", "uniq",
            "grep", "rg", "find", "tar", "gzip", "gunzip", "zip", "unzip",
            "git", "pytest", "uv", "npm", "yarn", "pnpm", "make", "cmake",
            # 既に上で扱った dangerous interpreter (重複防止)
            "sh", "bash", "zsh", "dash", "ash", "ksh", "fish",
            "python", "python2", "python3",
            "node", "nodejs", "deno", "bun",
            "ruby", "perl", "lua", "luajit", "php",
            "awk", "gawk", "mawk", "nawk",
            "expect", "tclsh", "wish",
            "r", "rscript", "osascript",
        }
    )
    _INLINE_EVAL_FLAGS: frozenset[str] = frozenset(
        {"-e", "--eval", "-c", "--command", "-command", "-r"}
    )
    if name not in _SAFE_KNOWN_COMMANDS and any(
        a in _INLINE_EVAL_FLAGS for a in rest
    ):
        return True
    return False


def _matches_kill_init(canonical_argv: tuple[str, ...]) -> bool:
    if not canonical_argv:
        return False
    name = canonical_argv[0]
    # kill -9 1 / kill -KILL 1 / killall -9 init / killall init
    if name == "kill":
        return any(a == "1" for a in canonical_argv[1:])
    if name == "killall":
        return any(a in {"1", "init"} for a in canonical_argv[1:])
    return False


def _matches_fork_bomb(joined: str) -> bool:
    return any(p.search(joined) for p in _FORK_BOMB_PATTERNS)


def _matches_base64_decode_exec(joined: str) -> bool:
    return bool(
        _BASE64_PIPE_PATTERN.search(joined)
        and re.search(r"\|\s*(sh|bash|zsh|eval)", joined, re.IGNORECASE)
    )


def _matches_curl_pipe_sh(joined: str) -> bool:
    return bool(_CURL_PIPE_PATTERN.search(joined))


def _matches_docker_socket_curl(canonical_argv: tuple[str, ...]) -> bool:
    if not canonical_argv or canonical_argv[0] not in {"curl", "wget"}:
        return False
    return any(
        "docker.sock" in a or "var/run/docker" in a
        for a in canonical_argv[1:]
    )


_CHECKERS: tuple[
    tuple[DangerousCommandDenyReason, Callable[[tuple[str, ...]], bool]],
    ...,
] = (
    (DangerousCommandDenyReason.RM_RF, _matches_rm_rf),
    (DangerousCommandDenyReason.FIND_DELETE, _matches_find_delete),
    (DangerousCommandDenyReason.CHMOD_777, _matches_chmod_777),
    (DangerousCommandDenyReason.CHOWN_RECURSIVE, _matches_chown_recursive),
    (DangerousCommandDenyReason.DD_OVERWRITE, _matches_dd_overwrite),
    (DangerousCommandDenyReason.MKFS, _matches_mkfs),
    (DangerousCommandDenyReason.DOCKER_PRIVILEGED, _matches_docker_privileged),
    (DangerousCommandDenyReason.DOCKER_HOST_NETWORK, _matches_docker_host_network),
    (DangerousCommandDenyReason.DOCKER_SOCKET_MOUNT, _matches_docker_socket_mount),
    (DangerousCommandDenyReason.DOCKER_EXEC, _matches_docker_exec),
    (DangerousCommandDenyReason.MOUNT_UMOUNT, _matches_mount_umount),
    (DangerousCommandDenyReason.SUDO_SU, _matches_sudo_su),
    (DangerousCommandDenyReason.IPTABLES_UFW, _matches_iptables_ufw),
    (DangerousCommandDenyReason.KILL_INIT, _matches_kill_init),
    (DangerousCommandDenyReason.INLINE_EXEC, _matches_inline_exec),
    (DangerousCommandDenyReason.DOCKER_SOCKET_CURL, _matches_docker_socket_curl),
)


def detect_dangerous_command(argv: Sequence[str]) -> DangerousCommandViolation | None:
    """argv を dangerous command denylist 15 種と比較。

    Args:
        argv: command argv (``shell=False`` 前提)。1 要素目が command name、
            残りが arguments。

    Returns:
        ``DangerousCommandViolation`` (matched) or ``None`` (allowed)。
    """

    if not argv:
        return DangerousCommandViolation(
            argv=tuple(argv),
            canonical_argv=(),
            reason=DangerousCommandDenyReason.EMPTY_ARGV,
        )
    canonical_argv = canonicalize_command(argv)
    joined = " ".join(canonical_argv)

    # argv-element-based checkers (高速、precise)
    for reason, checker in _CHECKERS:
        if checker(canonical_argv):
            return DangerousCommandViolation(
                argv=tuple(argv),
                canonical_argv=canonical_argv,
                reason=reason,
            )

    # joined-string checkers (shell metachar / pipe chain detection)
    if _matches_fork_bomb(joined):
        return DangerousCommandViolation(
            argv=tuple(argv),
            canonical_argv=canonical_argv,
            reason=DangerousCommandDenyReason.FORK_BOMB,
        )
    if _matches_base64_decode_exec(joined):
        return DangerousCommandViolation(
            argv=tuple(argv),
            canonical_argv=canonical_argv,
            reason=DangerousCommandDenyReason.BASE64_DECODE_EXEC,
        )
    if _matches_curl_pipe_sh(joined):
        return DangerousCommandViolation(
            argv=tuple(argv),
            canonical_argv=canonical_argv,
            reason=DangerousCommandDenyReason.CURL_PIPE_SH,
        )

    return None


__all__ = [
    "DangerousCommandDenyReason",
    "DangerousCommandViolation",
    "canonicalize_command",
    "detect_dangerous_command",
]
