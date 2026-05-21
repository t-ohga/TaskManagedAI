"""Tests for `scripts.taskhub_kpi_baseline` (SP022-T06).

- build_kpi_baseline_document: pure function、injectable computed_at + host_metadata
- collect_host_metadata: platform/socket info を返す
- write_baseline_to_path: atomic write + permission 0o644
- main(CLI): end-to-end run + valid JSON output
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from scripts.taskhub_kpi_baseline import (
    BASELINE_SCHEMA_VERSION,
    HostMetadata,
    build_kpi_baseline_document,
    collect_host_metadata,
    main,
    write_baseline_to_path,
)

# === Fake KpiRollupSummary / KpiEntry / CorpusLoadResult ===


class _FakeKpiEntry:
    def __init__(self, kpi_id: str, metric_value: float | None, threshold_met: bool, reason: str | None) -> None:
        self.kpi_id = kpi_id
        self.metric_value = metric_value
        self.threshold_met = threshold_met
        self.threshold_reason = reason


class _FakeKpiRollupSummary:
    def __init__(self, entries: list[_FakeKpiEntry], met_count: int, failed_count: int) -> None:
        self.kpi_count = 5
        self.met_count = met_count
        self.failed_count = failed_count
        self.p0_accept = failed_count <= 1
        self.fail_tolerance = 1
        self.entries = tuple(entries)


class _FakeCorpusLoadResult:
    def __init__(self, kpi_id: str, dataset_key: str, version: str, count: int) -> None:
        self.kpi_id = kpi_id
        self.dataset_key = dataset_key
        self.dataset_version = version
        self.fixture_count = count


def _make_summary(met: int = 4, failed: int = 1) -> _FakeKpiRollupSummary:
    entries = [
        _FakeKpiEntry("AC-KPI-01", 0.75, True, "threshold_met"),
        _FakeKpiEntry("AC-KPI-02", 1.0, True, "threshold_met"),
        _FakeKpiEntry("AC-KPI-03", 7200000.0, True, "threshold_met"),
        _FakeKpiEntry("AC-KPI-04", 0.6, False, "below_threshold"),
        _FakeKpiEntry("AC-KPI-05", 0.3, True, "threshold_met"),
    ]
    return _FakeKpiRollupSummary(entries, met, failed)


def _make_corpus_results() -> tuple[_FakeCorpusLoadResult, ...]:
    return (
        _FakeCorpusLoadResult("AC-KPI-01", "acceptance_pass_rate", "v1", 10),
        _FakeCorpusLoadResult("AC-KPI-02", "time_to_merge", "v1", 8),
    )


# === build_kpi_baseline_document tests ===


def test_baseline_document_schema_version_is_1() -> None:
    """schema_version=1 が document に含まれる (forward-compat marker)."""
    doc = build_kpi_baseline_document(
        "t-ohga-mac",
        rollup_summary=_make_summary(),
        corpus_load_results=_make_corpus_results(),
        computed_at=datetime(2026, 5, 22, 12, 0, 0, tzinfo=UTC),
        host_metadata=HostMetadata(
            host_id="t-ohga-mac",
            platform_system="Darwin",
            platform_release="25.5.0",
            python_version="3.12.11",
            machine="arm64",
            uname_node="test.local",
        ),
    )
    assert doc["schema_version"] == "1"
    assert doc["host_id"] == "t-ohga-mac"
    assert doc["computed_at"] == "2026-05-22T12:00:00Z"


def test_baseline_document_includes_kpi_rollup_5_entries() -> None:
    """5 KPI entries が全件 doc に含まれる + p0_accept 判定."""
    doc = build_kpi_baseline_document(
        "t-ohga-mac",
        rollup_summary=_make_summary(),
        corpus_load_results=_make_corpus_results(),
    )
    assert doc["kpi_rollup"]["kpi_count"] == 5
    assert doc["kpi_rollup"]["met_count"] == 4
    assert doc["kpi_rollup"]["failed_count"] == 1
    assert doc["kpi_rollup"]["p0_accept"] is True
    assert len(doc["kpi_rollup"]["entries"]) == 5
    assert doc["kpi_rollup"]["entries"][0]["kpi_id"] == "AC-KPI-01"


def test_baseline_document_includes_corpus_load_results() -> None:
    """corpus_load_results が dataset version + fixture count を持つ."""
    doc = build_kpi_baseline_document(
        "t-ohga-mac",
        rollup_summary=_make_summary(),
        corpus_load_results=_make_corpus_results(),
    )
    results = doc["corpus_load_results"]
    assert len(results) == 2
    assert results[0]["kpi_id"] == "AC-KPI-01"
    assert results[0]["dataset_key"] == "acceptance_pass_rate"
    assert results[0]["dataset_version"] == "v1"
    assert results[0]["fixture_count"] == 10


def test_baseline_document_includes_anti_gaming_disclaimer() -> None:
    """Anti-Gaming: baseline_metadata に sut_results_provided=False と disclaimer."""
    doc = build_kpi_baseline_document(
        "t-ohga-mac",
        rollup_summary=_make_summary(),
        corpus_load_results=_make_corpus_results(),
    )
    meta = doc["baseline_metadata"]
    assert meta["sut_results_provided"] is False
    assert "SUT cross-check" in meta["anti_gaming_disclaimer"]
    assert meta["scope"] == "mac_only"


def test_baseline_document_scope_marker_for_non_mac_host() -> None:
    """Linux/VPS host は scope=other_host (Mac 単独 light mode の区別)."""
    doc = build_kpi_baseline_document(
        "t-ohga-vps",
        rollup_summary=_make_summary(),
        corpus_load_results=_make_corpus_results(),
    )
    assert doc["baseline_metadata"]["scope"] == "other_host"


def test_baseline_document_uses_default_computed_at_when_none(tmp_path: Path) -> None:
    """computed_at=None なら datetime.now(UTC) を使用 (ISO 8601 Z suffix)."""
    _ = tmp_path
    doc = build_kpi_baseline_document(
        "t-ohga-mac",
        rollup_summary=_make_summary(),
        corpus_load_results=_make_corpus_results(),
    )
    # ISO 8601 Z format check
    assert doc["computed_at"].endswith("Z")
    # parse back to verify valid timestamp
    parsed = datetime.fromisoformat(doc["computed_at"].replace("Z", "+00:00"))
    assert parsed.tzinfo == UTC


# === collect_host_metadata tests ===


def test_collect_host_metadata_returns_non_empty_fields() -> None:
    """host info を実 platform module から取得、全 field non-empty."""
    md = collect_host_metadata("t-ohga-mac")
    assert md.host_id == "t-ohga-mac"
    assert md.platform_system  # e.g. "Darwin"
    assert md.python_version  # e.g. "3.12.11"
    assert md.machine  # e.g. "arm64"


# === write_baseline_to_path tests ===


def test_write_baseline_to_path_creates_parent_dir_and_writes_json(tmp_path: Path) -> None:
    """parent dir create + atomic write + permission 0o644."""
    doc = {"schema_version": "1", "host_id": "t-ohga-mac", "test": "data"}
    output = tmp_path / "subdir" / "mac.json"
    write_baseline_to_path(doc, output)
    assert output.exists()
    assert output.parent.exists()
    # permission verify
    assert oct(output.stat().st_mode)[-3:] == "644"
    # JSON content verify
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == doc


def test_write_baseline_to_path_atomic_overwrite(tmp_path: Path) -> None:
    """既存 file を atomic に overwrite (tempfile + rename pattern)."""
    output = tmp_path / "mac.json"
    output.write_text('{"old": true}', encoding="utf-8")
    doc = {"schema_version": "1", "new": True}
    write_baseline_to_path(doc, output)
    loaded = json.loads(output.read_text(encoding="utf-8"))
    assert loaded == doc
    assert not (tmp_path / "mac.json.tmp").exists()  # tempfile cleanup


# === main(CLI) end-to-end tests ===


def test_main_cli_end_to_end_writes_valid_baseline(tmp_path: Path) -> None:
    """`taskhub kpi-baseline --host t-ohga-mac --output <path>` end-to-end run."""
    output = tmp_path / "mac.json"
    exit_code = main(["--host", "t-ohga-mac", "--output", str(output)])
    assert exit_code == 0
    assert output.exists()
    doc = json.loads(output.read_text(encoding="utf-8"))
    assert doc["schema_version"] == BASELINE_SCHEMA_VERSION
    assert doc["host_id"] == "t-ohga-mac"
    # actual KPI rollup must run (no fake)
    assert doc["kpi_rollup"]["kpi_count"] == 5
    assert "entries" in doc["kpi_rollup"]
    assert len(doc["kpi_rollup"]["entries"]) == 5
    # All 5 KPI ids present
    kpi_ids = [e["kpi_id"] for e in doc["kpi_rollup"]["entries"]]
    assert set(kpi_ids) == {
        "AC-KPI-01", "AC-KPI-02", "AC-KPI-03", "AC-KPI-04", "AC-KPI-05"
    }


def test_main_cli_missing_required_args() -> None:
    """--host / --output 必須 (SystemExit 2 from argparse)."""
    with pytest.raises(SystemExit) as exc_info:
        main([])
    assert exc_info.value.code == 2
