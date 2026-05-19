"""Phase E adversarial closure trace audit (SP022-T04, ADR-00020 audit-only gate).

Verifies SP-022 framework_intake_hardening Pack contains a valid Phase E trace
matrix at the `## Phase E adversarial closure trace` section (suffix tolerant):

- All 16 findings (PE-F-001〜PE-F-016) present, no extra (PE-F-017+).
- 5-column table header exactly matching expected name/order.
- 5-column separator row.
- Each row's symptom column non-empty and >= 20 chars.
- PE-F-010 row marked as closed by SP022-T01 (closure word AND, negative word NONE).
- Each row's owning sprint cell contains exactly one ``SP-NNN`` token equal to
  the per-finding mapping in ``EXPECTED_OWNING_SPRINT_BY_FINDING``.

The verifier emits one or more ``VIOLATION reason_code=...`` lines on stdout
and exits 1 if any violation is found. Exit 0 means PASS.

R1-F-001 adopt: ``--pack-path`` is exposed so pytest can run the verifier against
a temporary file copy without touching the real SP-022 Pack.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

DEFAULT_PACK = Path("docs/sprints/SP-022_framework_intake_hardening.md")

# R2-F-001 adopt: suffix-tolerant section header match.
# Current SP-022 heading is
# `## Phase E adversarial closure trace (PE-F-001〜PE-F-016、F-R2-003 adopt: ...)`.
SECTION_HEADER_PREFIX = "## Phase E adversarial closure trace"

# Row regex captures finding id (PE-F-NNN) at the start of a table row.
ROW_RE = re.compile(r"^\|\s*(PE-F-\d{3})\s*\|([^\n]+)\|", re.MULTILINE)

# R2-F-002 adopt: SP-NNN token exact, 3-digit fixed + word boundary.
SP_TOKEN_RE = re.compile(r"SP-(\d{3})\b")

EXPECTED_FINDINGS = {f"PE-F-{i:03d}" for i in range(1, 17)}

# R3-F-R3-001 adopt: ADR-00020 `related_sprints: SP-022` + SP022-T01 closure.
EXPECTED_OWNING_SPRINTS = {
    "SP-013",
    "SP-014",
    "SP-015",
    "SP-016",
    "SP-018",
    "SP-020",
    "SP-022",
}

# R1-F-002 + R3-F-R3-001 adopt: per-row exact mapping.
# PE-F-010 is normalized to SP-022 (ADR-00020 owner + SP022-T01 closure).
EXPECTED_OWNING_SPRINT_BY_FINDING = {
    "PE-F-001": "SP-013",
    "PE-F-002": "SP-013",
    "PE-F-003": "SP-014",
    "PE-F-004": "SP-014",
    "PE-F-005": "SP-014",
    "PE-F-006": "SP-015",
    "PE-F-007": "SP-015",
    "PE-F-008": "SP-016",
    "PE-F-009": "SP-016",
    "PE-F-010": "SP-022",  # R3-F-R3-001 adopt
    "PE-F-011": "SP-018",
    "PE-F-012": "SP-018",
    "PE-F-013": "SP-018",
    "PE-F-014": "SP-020",
    "PE-F-015": "SP-020",
    "PE-F-016": "SP-020",
}

# R1-F-003 adopt: header row exact match.
EXPECTED_HEADER_CELLS = (
    "Finding ID",
    "Owning Sprint",
    "trace status",
    "post-P0.1 contract test PASS gate",
    "symptom",
)

SEPARATOR_CELL_RE = re.compile(r"^-+$")

# R1-F-006 adopt: PE-F-010 closure marker AND `SP022-T01`
# + ANY of closure words + NONE of negative words.
T01_AND_MARKER = "SP022-T01"
T01_CLOSURE_WORDS = ("closed", "実装完了", "completed", "PR #70")
T01_NEGATIVE_WORDS = ("TODO", "予定", "未完了", "pending")

# R1-F-004 adopt: 20 chars unified threshold.
SYMPTOM_MIN_CHARS = 20


def _split_row_cells(row: str) -> list[str]:
    """Split a markdown table row like ``| a | b |`` into cell strings.

    Leading and trailing ``|`` produce empty cells which are dropped so that
    only the actual content cells remain.
    """

    parts = row.split("|")
    return [c.strip() for c in parts[1:-1]]


def parse_section(content: str) -> list[str] | None:
    """Extract lines inside ``## Phase E adversarial closure trace`` section.

    R1-F-012 + R2-F-001 adopt: line-based parser with suffix-tolerant header.
    Returns the lines between the matching header and the next ``## `` heading,
    or ``None`` if the section is not present.
    """

    lines = content.split("\n")
    in_section = False
    section_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not in_section and stripped.startswith(SECTION_HEADER_PREFIX):
            in_section = True
            continue
        if in_section and line.startswith("## "):
            break
        if in_section:
            section_lines.append(line)
    if not in_section:
        return None
    return section_lines


def verify_header(section_lines: list[str], pack: Path) -> list[str]:
    """Verify the first table header matches the expected 5-column schema.

    R1-F-003 adopt.
    """

    violations: list[str] = []
    header_idx: int | None = None
    for i, line in enumerate(section_lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "Finding ID" in stripped:
            header_idx = i
            break
    if header_idx is None:
        violations.append(
            "VIOLATION "
            "reason_code=framework_intake_violation_phase_e_trace_header_mismatch "
            f"evidence={pack}:phase_e_section label=header_row_not_found"
        )
        return violations
    header_cells = _split_row_cells(section_lines[header_idx])
    if tuple(header_cells) != EXPECTED_HEADER_CELLS:
        violations.append(
            "VIOLATION "
            "reason_code=framework_intake_violation_phase_e_trace_header_mismatch "
            f"evidence={pack}:phase_e_section "
            f"label=actual={header_cells}|expected={list(EXPECTED_HEADER_CELLS)}"
        )
    if header_idx + 1 < len(section_lines):
        sep_cells = _split_row_cells(section_lines[header_idx + 1])
        if len(sep_cells) != 5 or not all(SEPARATOR_CELL_RE.match(c) for c in sep_cells):
            violations.append(
                "VIOLATION "
                "reason_code=framework_intake_violation_phase_e_trace_header_mismatch "
                f"evidence={pack}:phase_e_section "
                f"label=separator_row_invalid={sep_cells}"
            )
    return violations


def verify_rows(section_body: str, pack: Path) -> list[str]:
    """Verify PE-F-NNN rows: completeness, columns, symptom, owner, PE-F-010 closure."""

    violations: list[str] = []
    rows: dict[str, str] = {}
    # F-PR72-001 adopt: detect duplicate PE-F-NNN rows (dict overwrite silently
    # accepted a malformed matrix with 17+ rows whose IDs collide).
    row_counts: dict[str, int] = {}
    for row_match in ROW_RE.finditer(section_body):
        finding_id = row_match.group(1)
        row_counts[finding_id] = row_counts.get(finding_id, 0) + 1
        if finding_id not in rows:
            rows[finding_id] = row_match.group(0)
    for finding_id, count in sorted(row_counts.items()):
        if count > 1:
            violations.append(
                "VIOLATION "
                "reason_code=framework_intake_violation_phase_e_trace_finding_duplicated "
                f"evidence={pack}:phase_e_section finding={finding_id} count={count}"
            )

    # R1-F-013 adopt: all 16 findings present, no extra (PE-F-017+).
    missing = EXPECTED_FINDINGS - set(rows.keys())
    extra = set(rows.keys()) - EXPECTED_FINDINGS
    for finding_id in sorted(missing):
        violations.append(
            "VIOLATION "
            "reason_code=framework_intake_violation_phase_e_trace_finding_missing "
            f"evidence={pack}:phase_e_section finding={finding_id}"
        )
    for finding_id in sorted(extra):
        violations.append(
            "VIOLATION "
            "reason_code=framework_intake_violation_phase_e_trace_finding_unexpected "
            f"evidence={pack}:phase_e_section finding={finding_id}"
        )

    for finding_id in sorted(rows):
        row = rows[finding_id]
        cells = _split_row_cells(row)
        # F-PR72-002 adopt: enforce exact 5 cells (extra cells were silently accepted).
        if len(cells) != 5:
            violations.append(
                "VIOLATION "
                "reason_code=framework_intake_violation_phase_e_trace_symptom_missing "
                f"evidence={pack}:{finding_id} "
                f"label=row_column_count={len(cells)}_expected_5"
            )
            continue
        symptom = cells[4]
        if len(symptom) < SYMPTOM_MIN_CHARS:
            violations.append(
                "VIOLATION "
                "reason_code=framework_intake_violation_phase_e_trace_symptom_missing "
                f"evidence={pack}:{finding_id} "
                f"label=symptom_too_short={len(symptom)}_min={SYMPTOM_MIN_CHARS}"
            )

        # R1-F-002 + R2-F-002 adopt: owning cell must contain exactly one SP-NNN
        # token and that token must equal the per-row expected value.
        owning_cell = cells[1]
        expected_sprint = EXPECTED_OWNING_SPRINT_BY_FINDING.get(finding_id)
        sp_tokens = [f"SP-{m}" for m in SP_TOKEN_RE.findall(owning_cell)]
        if (
            expected_sprint is None
            or len(sp_tokens) != 1
            or sp_tokens[0] != expected_sprint
        ):
            violations.append(
                "VIOLATION "
                "reason_code=framework_intake_violation_phase_e_trace_owning_sprint_invalid "
                f"evidence={pack}:{finding_id} "
                f"label=owning_cell={owning_cell[:60]}"
                f"|tokens={sp_tokens}|expected={expected_sprint}"
            )

        # R1-F-006 + F-PR72-003 adopt: PE-F-010 closure marker AND/AND/NOT.
        # F-PR72-003: negative word check is case-insensitive so `Pending` / `todo`
        # variants are caught alongside `pending` / `TODO`.
        if finding_id == "PE-F-010":
            row_lower = row.lower()
            has_t01 = T01_AND_MARKER in row
            has_closure = any(w in row for w in T01_CLOSURE_WORDS)
            has_negative = any(w.lower() in row_lower for w in T01_NEGATIVE_WORDS)
            if not (has_t01 and has_closure) or has_negative:
                violations.append(
                    "VIOLATION "
                    "reason_code=framework_intake_violation_phase_e_trace_t01_closure_marker_missing "
                    f"evidence={pack}:PE-F-010 "
                    f"label=t01={has_t01}|closure={has_closure}|negative={has_negative}"
                )

    return violations


def run(pack: Path) -> list[str]:
    """Run all verifications and return a list of violation strings."""

    violations: list[str] = []
    if not pack.exists():
        violations.append(
            "VIOLATION "
            "reason_code=framework_intake_violation_phase_e_trace_pack_missing "
            f"evidence={pack} label=sp022_pack_not_found"
        )
        return violations
    content = pack.read_text(encoding="utf-8")
    section_lines = parse_section(content)
    if section_lines is None:
        violations.append(
            "VIOLATION "
            "reason_code=framework_intake_violation_phase_e_trace_section_missing "
            f"evidence={pack}:1 label=phase_e_section_header_not_found"
        )
        return violations
    violations.extend(verify_header(section_lines, pack))
    section_body = "\n".join(section_lines)
    violations.extend(verify_rows(section_body, pack))
    return violations


def main() -> int:
    parser = argparse.ArgumentParser(
        description="SP022-T04 Phase E adversarial closure trace audit"
    )
    parser.add_argument("--mode", choices=["baseline-scan"], default="baseline-scan")
    parser.add_argument(
        "--pack-path",
        type=Path,
        default=DEFAULT_PACK,
        help=(
            "Path to SP-022 framework_intake_hardening Pack. "
            "Tests override this with tmp_path copies (R1-F-001 adopt)."
        ),
    )
    args = parser.parse_args()
    violations = run(args.pack_path)
    for v in violations:
        print(v)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
