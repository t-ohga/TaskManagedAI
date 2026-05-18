"""Sprint 12 batch 6 (BL-0149 CLI): p0_acceptance_report_run.py skeleton tests."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "p0_acceptance_report_run.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )


def test_cli_script_exists() -> None:
    assert _CLI_PATH.exists(), f"CLI script not found at {_CLI_PATH}"


def test_cli_help_returns_zero() -> None:
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "P0 Acceptance Report CLI" in result.stdout
    assert "BL-0149" in result.stdout


def test_cli_skeleton_mode_returns_zero() -> None:
    """--input なしで skeleton mode、info message + exit 0."""
    result = _run_cli()
    assert result.returncode == 0
    assert "batch 6 — CLI skeleton" in result.stdout
    assert "run_p0_acceptance_report" in result.stdout


def test_cli_missing_input_returns_exit_2(tmp_path: Path) -> None:
    """存在しない --input path → exit 2 (CLI usage error)."""
    missing = tmp_path / "nonexistent-p0-input.json"
    result = _run_cli("--input", str(missing))
    assert result.returncode == 2
    assert "input JSON not found" in result.stderr


def test_cli_input_present_but_batch6_1_returns_exit_2() -> None:
    """input path が存在しても batch 6 では実 deserialization 未実装で exit 2."""
    import tempfile

    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as f:
        f.write('{"placeholder": "batch 6.1+ implementation"}')
        tmp_path = f.name

    try:
        result = _run_cli("--input", tmp_path)
        assert result.returncode == 2
        assert "batch 6.1+" in result.stderr
    finally:
        import os

        os.unlink(tmp_path)


def test_cli_skeleton_mode_with_json_returns_valid_json() -> None:
    """Codex F-PR62-002 P2 adopt: --json 指定時の skeleton mode は valid JSON 出力。

    旧設計 (--json でも prose output) は CLI automation が parse 失敗 → 物理削除.
    """
    import json

    result = _run_cli("--json")
    assert result.returncode == 0
    payload = json.loads(result.stdout)  # parse error なく decode できる
    assert payload["status"] == "skeleton"
    assert payload["batch"] == "sp012-batch6"
    assert payload["exit_code"] == 0
    assert "next_batch" in payload


def test_cli_no_raw_secret_in_output() -> None:
    """AC-HARD-02 trace: CLI output に raw secret pattern を含まない。"""
    result = _run_cli()
    forbidden = ["sk-", "ghp_", "ghs_", "AGE-SECRET", "tskey-", "BEGIN RSA"]
    for pat in forbidden:
        assert pat not in result.stdout, f"raw secret {pat!r} found in stdout"
        assert pat not in result.stderr, f"raw secret {pat!r} found in stderr"
