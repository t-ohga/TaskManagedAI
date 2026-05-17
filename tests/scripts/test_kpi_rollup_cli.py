"""Sprint 12 batch 1 (BL-0148 CLI): kpi_rollup_run.py CLI tests.

subprocess base で `scripts/kpi_rollup_run.py` を実行し、exit code +
stdout (text / JSON) を verify する.

実際の `eval/quality/` corpus を使う (repo 内 fixture、CI runner で読み込める).
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
_CLI_PATH = _REPO_ROOT / "scripts" / "kpi_rollup_run.py"


def _run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    """CLI を subprocess で実行 (uv run 経由ではなく python 直接、
    test runner の env を継承)。
    """

    return subprocess.run(  # noqa: S603
        [sys.executable, str(_CLI_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(_REPO_ROOT),
        check=False,
    )


def test_cli_executable_exists() -> None:
    """CLI script は repo 内に存在する."""
    assert _CLI_PATH.exists(), f"CLI script not found at {_CLI_PATH}"


def test_cli_help_returns_zero() -> None:
    """`--help` で usage を出して exit 0。"""
    result = _run_cli("--help")
    assert result.returncode == 0
    assert "KPI Rollup CLI" in result.stdout or "kpi" in result.stdout.lower()


def test_cli_default_text_output_emits_p0_decision() -> None:
    """default (text) output で p0_accept 行 + 5 KPI entries が含まれる。"""
    result = _run_cli()
    # eval/quality fixture corpus が読めれば exit 0 (all-pass) or 1 (some-fail)
    assert result.returncode in (0, 1), (
        f"unexpected exit code {result.returncode}: stderr={result.stderr}"
    )
    assert "KPI Rollup Summary" in result.stdout
    assert "p0_accept:" in result.stdout
    # 5 KPI 全件出力
    for kpi_id in ("AC-KPI-01", "AC-KPI-02", "AC-KPI-03", "AC-KPI-04", "AC-KPI-05"):
        assert kpi_id in result.stdout, f"missing {kpi_id} in CLI output"


def test_cli_json_output_is_valid_with_required_keys() -> None:
    """`--json` で valid JSON + 必須 keys を含む。"""
    result = _run_cli("--json")
    assert result.returncode in (0, 1)
    payload = json.loads(result.stdout)
    assert set(payload.keys()) == {
        "kpi_count",
        "met_count",
        "failed_count",
        "p0_accept",
        "fail_tolerance",
        "entries",
        "corpus_loads",
    }
    assert payload["kpi_count"] == 5
    assert len(payload["entries"]) == 5
    assert len(payload["corpus_loads"]) == 5
    # AC-KPI-01..05 順 invariant
    assert [e["kpi_id"] for e in payload["entries"]] == [
        "AC-KPI-01",
        "AC-KPI-02",
        "AC-KPI-03",
        "AC-KPI-04",
        "AC-KPI-05",
    ]


def test_cli_exit_code_matches_p0_accept() -> None:
    """exit code 0 ⇔ p0_accept=True、exit code 1 ⇔ p0_accept=False。"""
    result = _run_cli("--json")
    payload = json.loads(result.stdout)
    if payload["p0_accept"]:
        assert result.returncode == 0
    else:
        assert result.returncode == 1


def test_cli_eval_quality_root_override_returns_exit_2_on_missing(
    tmp_path: Path,
) -> None:
    """`--eval-quality-root` で存在しない path を渡すと exit 2 (corpus load error)。"""
    missing = tmp_path / "nonexistent-eval-quality"
    result = _run_cli("--eval-quality-root", str(missing))
    assert result.returncode == 2
    assert "ERROR" in result.stderr or "ERROR" in result.stdout


def test_cli_json_entries_have_required_fields() -> None:
    """各 entry に metric_key / metric_value / threshold_met / threshold_reason が含まれる。"""
    result = _run_cli("--json")
    payload = json.loads(result.stdout)
    for entry in payload["entries"]:
        assert "kpi_id" in entry
        assert "metric_key" in entry
        assert "metric_value" in entry
        assert "threshold_met" in entry
        assert isinstance(entry["threshold_met"], bool)
        # threshold_reason は optional だが key 自体は presence (None 可)
        assert "threshold_reason" in entry


def test_cli_no_raw_secret_in_output() -> None:
    """AC-HARD-02 trace: CLI output に raw secret pattern を含まない。"""
    result = _run_cli("--json")
    forbidden_patterns = [
        "sk-",
        "ghp_",
        "ghs_",
        "AGE-SECRET",
        "tskey-",
        "BEGIN RSA",
        "BEGIN OPENSSH",
    ]
    for pat in forbidden_patterns:
        assert pat not in result.stdout, (
            f"raw secret pattern {pat!r} found in CLI stdout"
        )
        assert pat not in result.stderr, (
            f"raw secret pattern {pat!r} found in CLI stderr"
        )
