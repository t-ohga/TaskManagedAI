"""Phase E adversarial closure trace audit pytest fixtures (SP022-T04).

R1 (13 findings) + R2 (2 HIGH) + R3 (1 CRITICAL) 全件 adopt 反映済の verifier
``scripts.ci._phase_e_trace_verifier`` を直接 subprocess invoke し、positive
(current SP-022 Pack PASS) + negative (tmp_path 内 fake pack で violation 検出)
を verify する。

R1-F-001 adopt: 全 negative fixture は ``--pack-path`` 引数で ``tmp_path`` 内
fake pack を verifier に渡す。実 SP-022 を変更せず regression を担保。
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER = REPO_ROOT / "scripts/ci/_phase_e_trace_verifier.py"
SP022_PACK = REPO_ROOT / "docs/sprints/SP-022_framework_intake_hardening.md"


def _run_verifier(pack_path: Path) -> tuple[int, str]:
    """Invoke the Phase E trace verifier against the supplied pack path."""

    result = subprocess.run(  # noqa: S603 (sys.executable + repo-internal verifier)
        [sys.executable, str(VERIFIER), "--mode=baseline-scan", "--pack-path", str(pack_path)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout + result.stderr


def _build_pack(
    *,
    section_header: str = "## Phase E adversarial closure trace (PE-F-001〜PE-F-016)",
    rows: list[str] | None = None,
    header_row: str | None = None,
    separator_row: str | None = None,
    add_trailing_section: bool = True,
) -> str:
    """Build a synthetic SP-022 Pack with a Phase E trace section.

    ``rows`` is a list of full markdown table rows (including leading/trailing ``|``).
    Defaults reproduce the SP022-T04 baseline 16-row matrix that PASSes the verifier.
    """

    if header_row is None:
        header_row = (
            "| Finding ID | Owning Sprint | trace status "
            "| post-P0.1 contract test PASS gate | symptom |"
        )
    if separator_row is None:
        separator_row = "|---|---|---|---|---|"

    if rows is None:
        owners = {
            "PE-F-001": "SP-013",
            "PE-F-002": "SP-013",
            "PE-F-003": "SP-014",
            "PE-F-004": "SP-014",
            "PE-F-005": "SP-014",
            "PE-F-006": "SP-015",
            "PE-F-007": "SP-015",
            "PE-F-008": "SP-016",
            "PE-F-009": "SP-016",
            "PE-F-010": "SP-022",
            "PE-F-011": "SP-018",
            "PE-F-012": "SP-018",
            "PE-F-013": "SP-018",
            "PE-F-014": "SP-020",
            "PE-F-015": "SP-020",
            "PE-F-016": "SP-020",
        }
        rows = []
        for finding_id, sprint in owners.items():
            if finding_id == "PE-F-010":
                rows.append(
                    f"| {finding_id} | {sprint} | ✅ closed by SP022-T01 (PR #70 merged) "
                    f"| SP022-T01 satisfied; no SP-016 exit gate "
                    f"| Framework intake CI 機械検査: license / external API / persistence / telemetry denylist |"
                )
            else:
                rows.append(
                    f"| {finding_id} | {sprint} | (parking) "
                    f"| {sprint} exit gate "
                    f"| Synthetic symptom long enough to pass the 20-char minimum threshold |"
                )

    parts = [
        "# Synthetic SP-022 Pack for SP022-T04 pytest",
        "",
        "## Some other section above",
        "",
        "Lorem ipsum dolor sit amet.",
        "",
        section_header,
        "",
        header_row,
        separator_row,
        *rows,
    ]
    if add_trailing_section:
        parts.extend(["", "## Trailing section", "more text"])
    return "\n".join(parts) + "\n"


# ----- positive (against real SP-022 Pack) -----
def test_real_sp022_pack_passes_verifier() -> None:
    """The current SP-022 Pack must PASS the verifier after SP022-T04 update."""

    exit_code, output = _run_verifier(SP022_PACK)
    assert exit_code == 0, output
    assert "VIOLATION" not in output


def test_real_sp022_pack_pe_f_010_has_t01_closure_marker() -> None:
    """PE-F-010 row contains SP022-T01 AND closure word AND no negative word."""

    text = SP022_PACK.read_text(encoding="utf-8")
    pe_f_010_lines = [
        ln for ln in text.split("\n") if ln.startswith("| PE-F-010 ")
    ]
    assert len(pe_f_010_lines) == 1, pe_f_010_lines
    row = pe_f_010_lines[0]
    assert "SP022-T01" in row
    assert "closed" in row
    for negative in ("TODO", "予定", "未完了", "pending"):
        assert negative not in row, f"unexpected negative word {negative} in {row}"


def test_real_sp022_pack_pe_f_010_owner_is_sp_022() -> None:
    """R3-F-R3-001 adopt: PE-F-010 owner normalized to SP-022 (not SP-016)."""

    text = SP022_PACK.read_text(encoding="utf-8")
    pe_f_010_lines = [
        ln for ln in text.split("\n") if ln.startswith("| PE-F-010 ")
    ]
    assert len(pe_f_010_lines) == 1
    row = pe_f_010_lines[0]
    cells = [c.strip() for c in row.split("|")[1:-1]]
    # cells[1] = Owning Sprint
    assert cells[1] == "SP-022", cells


def test_real_sp022_pack_all_symptoms_min_20_chars() -> None:
    """R1-F-004 adopt: every PE-F-NNN row has a symptom of length >= 20 chars."""

    text = SP022_PACK.read_text(encoding="utf-8")
    for line in text.split("\n"):
        if not line.startswith("| PE-F-"):
            continue
        cells = [c.strip() for c in line.split("|")[1:-1]]
        assert len(cells) >= 5, line
        assert len(cells[4]) >= 20, line


# ----- negative (tmp_path fake pack) -----
def test_fake_pack_missing_finding_fails(tmp_path: Path) -> None:
    """R1-F-013 adopt: PE-F-001 削除 → finding_missing violation."""

    fake = _build_pack()
    # Strip PE-F-001 row
    fake = "\n".join(
        ln for ln in fake.split("\n") if not ln.startswith("| PE-F-001 ")
    )
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_finding_missing" in output
    assert "PE-F-001" in output


def test_fake_pack_missing_symptom_fails(tmp_path: Path) -> None:
    """R1-F-003/R1-F-004 adopt: 4-column 形式の fake → header_mismatch + symptom_missing."""

    fake = _build_pack(
        header_row="| Finding ID | Owning Sprint | trace status | post-P0.1 contract test PASS gate |",
        separator_row="|---|---|---|---|",
        rows=[
            f"| PE-F-{i:03d} | "
            + ("SP-022" if i == 10 else "SP-013")
            + " | (parking) | SP exit gate |"
            for i in range(1, 17)
        ],
    )
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert (
        "framework_intake_violation_phase_e_trace_header_mismatch" in output
        or "framework_intake_violation_phase_e_trace_symptom_missing" in output
    )


def test_fake_pack_missing_t01_closure_marker_fails(tmp_path: Path) -> None:
    """R1-F-006 adopt: PE-F-010 row に SP022-T01 marker なし fake → t01_closure_marker_missing."""

    owners = {
        "PE-F-001": "SP-013",
        "PE-F-002": "SP-013",
        "PE-F-003": "SP-014",
        "PE-F-004": "SP-014",
        "PE-F-005": "SP-014",
        "PE-F-006": "SP-015",
        "PE-F-007": "SP-015",
        "PE-F-008": "SP-016",
        "PE-F-009": "SP-016",
        "PE-F-010": "SP-022",
        "PE-F-011": "SP-018",
        "PE-F-012": "SP-018",
        "PE-F-013": "SP-018",
        "PE-F-014": "SP-020",
        "PE-F-015": "SP-020",
        "PE-F-016": "SP-020",
    }
    rows = []
    for finding_id, sprint in owners.items():
        # Use a long enough generic symptom row, no SP022-T01 marker on PE-F-010 at all.
        rows.append(
            f"| {finding_id} | {sprint} | (parking) "
            f"| {sprint} exit gate "
            f"| Symptom string long enough to clear twenty character bar |"
        )
    fake = _build_pack(rows=rows)
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_t01_closure_marker_missing" in output


def test_fake_pack_owning_sprint_multi_token_fails(tmp_path: Path) -> None:
    """R2-F-002 adopt: SP-013 / SP-014 等 2 token → owning_sprint_invalid."""

    owners = {
        "PE-F-001": "SP-013 / SP-014",  # multi token
        "PE-F-002": "SP-013",
        "PE-F-003": "SP-014",
        "PE-F-004": "SP-014",
        "PE-F-005": "SP-014",
        "PE-F-006": "SP-015",
        "PE-F-007": "SP-015",
        "PE-F-008": "SP-016",
        "PE-F-009": "SP-016",
        "PE-F-010": "SP-022",
        "PE-F-011": "SP-018",
        "PE-F-012": "SP-018",
        "PE-F-013": "SP-018",
        "PE-F-014": "SP-020",
        "PE-F-015": "SP-020",
        "PE-F-016": "SP-020",
    }
    rows = []
    for finding_id, sprint in owners.items():
        if finding_id == "PE-F-010":
            rows.append(
                f"| {finding_id} | {sprint} | ✅ closed by SP022-T01 (PR #70 merged) "
                f"| SP022-T01 satisfied "
                f"| Framework intake CI 機械検査 long enough symptom |"
            )
        else:
            rows.append(
                f"| {finding_id} | {sprint} | (parking) "
                f"| exit gate parking "
                f"| Symptom long enough to clear twenty character bar |"
            )
    fake = _build_pack(rows=rows)
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_owning_sprint_invalid" in output
    assert "PE-F-001" in output


def test_fake_pack_owning_sprint_drift_token_fails(tmp_path: Path) -> None:
    """R2-F-002 adopt: SP-0139 等 4 桁 → owning_sprint_invalid (word boundary)."""

    owners = {
        "PE-F-001": "SP-0139",  # 4-digit drift
        "PE-F-002": "SP-013",
        "PE-F-003": "SP-014",
        "PE-F-004": "SP-014",
        "PE-F-005": "SP-014",
        "PE-F-006": "SP-015",
        "PE-F-007": "SP-015",
        "PE-F-008": "SP-016",
        "PE-F-009": "SP-016",
        "PE-F-010": "SP-022",
        "PE-F-011": "SP-018",
        "PE-F-012": "SP-018",
        "PE-F-013": "SP-018",
        "PE-F-014": "SP-020",
        "PE-F-015": "SP-020",
        "PE-F-016": "SP-020",
    }
    rows = []
    for finding_id, sprint in owners.items():
        if finding_id == "PE-F-010":
            rows.append(
                f"| {finding_id} | {sprint} | ✅ closed by SP022-T01 (PR #70 merged) "
                f"| SP022-T01 satisfied "
                f"| Framework intake CI 機械検査 long enough symptom |"
            )
        else:
            rows.append(
                f"| {finding_id} | {sprint} | (parking) "
                f"| exit gate parking "
                f"| Symptom long enough to clear twenty character bar |"
            )
    fake = _build_pack(rows=rows)
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_owning_sprint_invalid" in output
    assert "PE-F-001" in output


def test_fake_pack_section_header_with_suffix_passes(tmp_path: Path) -> None:
    """R2-F-001 adopt: custom suffix 付き heading でも section detection 成功 (positive regression)."""

    fake = _build_pack(
        section_header="## Phase E adversarial closure trace (custom suffix variation v3)",
    )
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 0, output
    assert "VIOLATION" not in output


def test_fake_pack_extra_finding_pe_f_017_fails(tmp_path: Path) -> None:
    """R1-F-013 adopt: PE-F-017 等 想定外 ID → finding_unexpected violation."""

    owners = {
        "PE-F-001": "SP-013",
        "PE-F-002": "SP-013",
        "PE-F-003": "SP-014",
        "PE-F-004": "SP-014",
        "PE-F-005": "SP-014",
        "PE-F-006": "SP-015",
        "PE-F-007": "SP-015",
        "PE-F-008": "SP-016",
        "PE-F-009": "SP-016",
        "PE-F-010": "SP-022",
        "PE-F-011": "SP-018",
        "PE-F-012": "SP-018",
        "PE-F-013": "SP-018",
        "PE-F-014": "SP-020",
        "PE-F-015": "SP-020",
        "PE-F-016": "SP-020",
        "PE-F-017": "SP-099",  # extra
    }
    rows = []
    for finding_id, sprint in owners.items():
        if finding_id == "PE-F-010":
            rows.append(
                f"| {finding_id} | {sprint} | ✅ closed by SP022-T01 (PR #70 merged) "
                f"| SP022-T01 satisfied "
                f"| Framework intake CI 機械検査 long enough symptom |"
            )
        else:
            rows.append(
                f"| {finding_id} | {sprint} | (parking) "
                f"| exit gate parking "
                f"| Symptom long enough to clear twenty character bar |"
            )
    fake = _build_pack(rows=rows)
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_finding_unexpected" in output
    assert "PE-F-017" in output


def test_fake_pack_missing_section_fails(tmp_path: Path) -> None:
    """section header 自体が無い fake → section_missing violation."""

    fake = (
        "# Synthetic SP-022 Pack\n"
        "\n"
        "## Some other section\n"
        "no phase e section here\n"
    )
    target = tmp_path / "fake_sp022.md"
    target.write_text(fake, encoding="utf-8")
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_section_missing" in output


def test_pack_path_missing_file_fails(tmp_path: Path) -> None:
    """--pack-path で存在しない file を指定 → pack_missing violation (R1-F-009 adopt)."""

    target = tmp_path / "does_not_exist.md"
    exit_code, output = _run_verifier(target)
    assert exit_code == 1
    assert "framework_intake_violation_phase_e_trace_pack_missing" in output
