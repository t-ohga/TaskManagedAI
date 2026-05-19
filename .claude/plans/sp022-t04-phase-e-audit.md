# SP022-T04: Phase E adversarial closure audit-only trace

最終更新: 2026-05-20 (r4, R3 1 CRITICAL adopt: F-R3-001 PE-F-010 owner SP-016→SP-022 (ADR-00020 related_sprints と整合))

## 1. 目的 (Goal)

SP-022 受け入れ条件 (`docs/sprints/SP-022_framework_intake_hardening.md` line 108): **Phase E 16 finding (PE-F-001〜PE-F-016) すべてが owning ADR/Sprint Pack に trace 済 (audit-only gate)** を CI 機械検査で恒久化する。

具体的に本 task で:
1. SP-022 内 `## Phase E adversarial closure trace` matrix を **symptom column 追加** で拡張 (current matrix は ID + Owning Sprint + trace status + post-P0.1 gate の 4 column のみ、symptom 不在)
2. PE-F-010 (Framework intake CI 機械検査) は **ADR-00020 owner + SP022-T01 で実装完了** marker 追加
3. `scripts/ci/check_phase_e_trace.sh` 追加: SP-022 内 matrix が PE-F-001〜PE-F-016 全 16 件カバーすることを機械検査
4. `tests/deploy/test_phase_e_trace.py` 追加: pytest fixture for CI gate verify (positive 全件カバー pass / negative finding 欠落 fail)
5. CI workflow に "Phase E trace audit check (SP022-T04)" step 追加 (R1-F-011 adopt: canonical name 統一)
6. SP-022 Pack `## Review` に SP022-T04 完了記録

**post-P0.1 実 contract test PASS** は各 owning sprint exit gate で実施 (本 T04 scope 外、SP-022 受け入れ条件 line 108 通り)。

## 2. 背景 (Background)

- Phase E (codex-adversarial-review、defensive review) 2026-05-10 完了 (`docs/設計検討/phase-c-multi-agent-spec-draft.md` §11.3 「Strengthening Catalog」 + `docs/設計検討/phase-h-closure-ledger.md` line 17-19)
- 16 finding (PE-F-001〜PE-F-016): HIGH 12 + MEDIUM 4、CRITICAL 0、全件 adopt
- SP-022 §Phase E adversarial closure trace matrix (line 230-249): 既存 4 column matrix を保持、本 task で symptom + completion marker 追加で拡張
- SP022-T01 PR #70 で PE-F-010 (Framework intake CI 機械検査) を ADR-00020 8 verify item で実装完了 (R1-R8 累計 38 adopt finding)
- SP022-T04 受け入れ条件 (SP-022 line 77 / line 108): audit-only gate、SP-022 内 matrix で各 finding の owning sprint 割り当て + 受け入れ条件 trace の **文書確認のみ**、実 contract test PASS は post-P0.1 SP-013〜020 owning sprint exit gate carry-over (F-PLAN-R3-001 + F-PLAN-R5-001 + F-ADV-R2-006 + F-R2-003 adopt)
- 本 T04 scope は **trace matrix の機械検査恒久化** に絞る (matrix の row 数 = 16、各 owning sprint 割り当て確認、symptom 短文付与)

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `scripts/ci/check_phase_e_trace.sh` (NEW) | 新規 CI script、SP-022 matrix の 16 finding カバー verify + symptom column 存在 verify |
| 2 | `scripts/ci/_phase_e_trace_verifier.py` (NEW) | Python helper、SP-022 Pack を parse、PE-F-001〜PE-F-016 全件カバー + owning sprint mapping + symptom 文字列存在 verify、`--pack-path` 引数で fixture override 可能 (R1-F-001 adopt) |
| 3 | `tests/deploy/test_phase_e_trace.py` (NEW) | pytest fixture: positive (clean SP-022 → pass) + negative (finding 欠落 / symptom 不在 → fail)、negative fixture は `--pack-path` で `tmp_path` 内 fake pack を verify (R1-F-001 adopt) |
| 4 | `docs/sprints/SP-022_framework_intake_hardening.md` (MODIFY) | `## Phase E adversarial closure trace` matrix を **symptom column 追加 + 5 column** に拡張、PE-F-010 `✅ closed by SP022-T01 (PR #70 merged 2026-05-19)` marker、`## Review` に SP022-T04 完了記録 |
| 5 | `.github/workflows/ci-smoke.yml` (MODIFY) | `backend-quality` job に "Phase E trace audit check (SP022-T04)" step 追加 (R1-F-011 adopt: canonical name) |
| 6 | `.claude/plans/sp022-t04-phase-e-audit.md` (本計画、commit 含む) | - |

### 3.2 対象外 (本 task では実装しない)

- **PE-F-001〜PE-F-016 の owning Sprint Pack must_ship update**: 各 owning Sprint Pack (SP-013/SP-014/SP-015/SP-016/SP-018/SP-020) の must_ship 内 PE-F-XXX 追加は **owning sprint 起票 PR で実施** (SP-022 受け入れ条件通り audit-only、本 T04 では SP-022 内 trace matrix の存在のみ verify)
- **実 contract test PASS**: post-P0.1 owning sprint exit gate carry-over (SP-022 受け入れ条件 line 108 通り、本 T04 scope 外)
- **PE-F-010 以外の closure 実装**: 他 finding の実装は各 owning sprint 着手時に実施、本 T04 では trace matrix の structural verify のみ
- **owning sprint mapping 変更**: 現 matrix の sprint mapping は SP-022 PR #67 で確立 (PE-F-001/002→SP-013、PE-F-003/004/005→SP-014、PE-F-006/007→SP-015、PE-F-008/009→SP-016、PE-F-011/012/013→SP-018、PE-F-014/015/016→SP-020)、本 T04 では **PE-F-010 のみ SP-016→SP-022 へ正規化** (R3-F-R3-001 adopt: ADR-00020 `related_sprints: SP-022_framework_intake_hardening` + SP-016 Pack 実 PE-F refs は PE-F-006/PE-F-014 のみで PE-F-010 を owning しないため、現 matrix の SP-016 mapping が ADR と drift。最小 fix として PE-F-010 owner を ADR/Sprint 正本である SP-022 に変更、closure は SP022-T01 で実装済)、他 finding の mapping は変更なし
- **symptom 文字列と §11.3 の機械整合**: R1-F-005 adopt — T04 は audit-only structural gate のみ、symptom と finding の対応誤りは **手動レビュー観点 (§7.1 #2 + #2.5)** で担保。機械化は post-T04 SP-022.X で symptom keyword map 拡張時に判断

## 4. CI gate 機械検査方針

### 4.1 検査対象

`docs/sprints/SP-022_framework_intake_hardening.md` 内 `## Phase E adversarial closure trace` section (現行 heading は suffix 付き `## Phase E adversarial closure trace (PE-F-001〜PE-F-016、F-R2-003 adopt: ...)`、R2-F-001 adopt: 完全一致ではなく **`startswith("## Phase E adversarial closure trace")` で suffix 許容**):

- table header: `| Finding ID | Owning Sprint | trace status | post-P0.1 contract test PASS gate | symptom |` (本 T04 で 5 column 化、symptom 追加)
- table header の **列名・順序を完全一致** で verify (R1-F-003 adopt: 5 cells でも column 名・順序が drift しないこと)
- table separator row (`|---|---|---|---|---|`) も 5 columns 一致 verify (R1-F-003 adopt)
- PE-F-001〜PE-F-016 全 16 row 存在
- 各 row の `symptom` column が非空 (**20+ chars**、本 R1-F-004 adopt で plan・scanner・pytest を 20 chars 基準で統一)
- PE-F-010 row に `SP022-T01` AND (`closed`|`実装完了`|`completed`|`PR #70` のいずれか) AND `TODO`|`予定`|`未完了`|`pending` のいずれも非含有 (R1-F-006 adopt: 偽陽性防止)
- **expected 16 IDs 完全一致** (extra finding PE-F-017+ 検出、R1-F-013 adopt)
- **per-row owning sprint mapping** は owning cell から **`SP-\d{3}` token を regex で全件抽出**し、**exactly 1 token** かつ期待 sprint と完全一致 (R2-F-002 adopt: substring 部分一致禁止、`SP-013 / SP-014` や `SP-0139` 等の bypass を deny)

### 4.2 機械検査 implementation

`scripts/ci/check_phase_e_trace.sh` + `scripts/ci/_phase_e_trace_verifier.py`:

1. SP-022 Pack を Python で read (default path、`--pack-path` 引数で override 可能、R1-F-001 adopt)
2. `## Phase E adversarial closure trace` section を **line-based parser** で抽出 (R1-F-012 adopt: `+2` offset 廃止、`line.startswith("## ") and not first_header` で安全に section boundary 判定)。section 開始判定は **`stripped_line.startswith("## Phase E adversarial closure trace")`** で **suffix 許容** (R2-F-001 adopt: 現行 SP-022 見出し `## Phase E adversarial closure trace (PE-F-001〜PE-F-016、...)` を block しない)
3. section 内最初の table の header row を抽出、5 column 完全一致 verify (R1-F-003 adopt)
4. table row 抽出 (`| PE-F-XXX | ...` regex)
5. 16 IDs (PE-F-001 〜 PE-F-016) 完全一致 verify、missing + **extra (PE-F-017+) も violation** (R1-F-013 adopt)
6. 各 row の column 数 verify (5 columns、symptom 含む) + symptom 非空 + 20+ chars (R1-F-004 adopt: scanner = 20 chars 基準、plan・DoD・pytest 名も 20 chars に統一)
7. PE-F-010 row に closure marker 存在 verify (R1-F-006 adopt: AND 条件 `SP022-T01` + 完了表現 OR + 否定語 NOT)
8. **per-row owning sprint mapping** verify (R1-F-002 + R2-F-002 adopt): owning cell から `SP-\d{3}` regex で **全件抽出**、抽出結果が **exactly 1 token** かつ `EXPECTED_OWNING_SPRINT_BY_FINDING` の期待値と完全一致 (substring `in` 比較禁止、`SP-013 / SP-014` の複数 token / `SP-0139` の桁数 drift / `not SP-013; now SP-014` の偽トークン経路を deny)
9. 違反検出時は `framework_intake_violation_phase_e_trace_*` reason_code emit (本 task で新規 reason code、ADR-00020 と整合)

### 4.3 CI mode

SP022-T01/T03 pattern 踏襲。**baseline-scan のみ** (本 task は audit gate、PR diff trigger 不要、毎 CI run で SP-022 Pack の trace matrix 整合を確認):

- 本 task は SP-022 Pack 自身の structural verify、PR 差分有無に関係なく毎 run
- emergency disable repository variable `PHASE_E_TRACE_CHECK_DISABLED=1` (admin only、SP022-T01/T03 と同 pattern)
- emergency disable 時の wrapper 出力: `phase_e_trace_check: SKIP disabled_by=PHASE_E_TRACE_CHECK_DISABLED` を stdout 出力 + `audit_marker: emergency_disable=true` / `audit_marker: requires_retro_pack_within_24h=true` / `audit_marker: ADR=ADR-00020` を stderr 出力 + exit 0 (R1-F-008 adopt: SP022-T01/T03 と同 pattern)
- disable 期間中は SP-022 `## Review` に `disable 日時 / 理由 / 復旧 commit SHA` 必須記録

### 4.4 reason_code

| condition | reason_code |
|---|---|
| SP-022 Pack file 不在 (`--pack-path` で指定したファイル不在) | `framework_intake_violation_phase_e_trace_pack_missing` (R1-F-009 adopt: §4.4 / pytest 期待値の整合) |
| `## Phase E adversarial closure trace` section 不在 | `framework_intake_violation_phase_e_trace_section_missing` |
| PE-F-XXX row 欠落 (16 件未満) | `framework_intake_violation_phase_e_trace_finding_missing` |
| 想定外 PE-F-ID (PE-F-017 以上 等) row 検出 | `framework_intake_violation_phase_e_trace_finding_unexpected` (R1-F-013 adopt) |
| table header 列名・順序 mismatch | `framework_intake_violation_phase_e_trace_header_mismatch` (R1-F-003 adopt) |
| symptom column 不在 / 空 / 20 chars 未満 | `framework_intake_violation_phase_e_trace_symptom_missing` |
| owning sprint mapping invalid (per-row 固定 mapping 不一致 or 期待 set 外) | `framework_intake_violation_phase_e_trace_owning_sprint_invalid` (R1-F-002 adopt) |
| PE-F-010 closure marker 不在 (`SP022-T01` + 完了表現 AND 否定語 NOT) | `framework_intake_violation_phase_e_trace_t01_closure_marker_missing` (R1-F-006 adopt) |

## 5. 実装詳細

### 5.1 `scripts/ci/_phase_e_trace_verifier.py` 構造

```python
"""Phase E adversarial closure trace audit (SP022-T04, ADR-00020 audit-only gate).

Verifies SP-022 framework_intake_hardening Pack contains a valid Phase E trace matrix:
- All 16 findings (PE-F-001〜PE-F-016) present, no extra (PE-F-017+)
- 5-column table header exactly matching expected name/order
- 5-column separator row
- symptom column non-empty and >= 20 chars
- PE-F-010 marked as closed by SP022-T01 (AND closure marker, AND no TODO/pending words)
- Each owning sprint exactly matches EXPECTED_OWNING_SPRINT_BY_FINDING fixed map
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

DEFAULT_PACK = Path("docs/sprints/SP-022_framework_intake_hardening.md")
# R2-F-001 adopt: 現行 SP-022 見出しは `## Phase E adversarial closure trace (PE-F-001〜...)` 形式、suffix 許容
SECTION_HEADER_PREFIX = "## Phase E adversarial closure trace"
ROW_RE = re.compile(r"^\|\s*(PE-F-\d{3})\s*\|([^\n]+)\|", re.MULTILINE)
SP_TOKEN_RE = re.compile(r"SP-(\d{3})\b")  # R2-F-002 adopt: SP-NNN token exact, 3 桁固定 + word boundary
EXPECTED_FINDINGS = {f"PE-F-{i:03d}" for i in range(1, 17)}
# R3-F-R3-001 adopt: ADR-00020 `related_sprints: SP-022` + SP022-T01 closure を反映、PE-F-010 owner を SP-022 に正規化
EXPECTED_OWNING_SPRINTS = {"SP-013", "SP-014", "SP-015", "SP-016", "SP-018", "SP-020", "SP-022"}

# R1-F-002 + R3-F-R3-001 adopt: per-row exact mapping (PR #67 で確立、PE-F-010 のみ SP-022 へ正規化)
EXPECTED_OWNING_SPRINT_BY_FINDING = {
    "PE-F-001": "SP-013", "PE-F-002": "SP-013",
    "PE-F-003": "SP-014", "PE-F-004": "SP-014", "PE-F-005": "SP-014",
    "PE-F-006": "SP-015", "PE-F-007": "SP-015",
    "PE-F-008": "SP-016", "PE-F-009": "SP-016",
    "PE-F-010": "SP-022",  # R3-F-R3-001 adopt: ADR-00020 + SP022-T01 closure 整合
    "PE-F-011": "SP-018", "PE-F-012": "SP-018", "PE-F-013": "SP-018",
    "PE-F-014": "SP-020", "PE-F-015": "SP-020", "PE-F-016": "SP-020",
}

# R1-F-003 adopt: header row exact match
EXPECTED_HEADER_CELLS = (
    "Finding ID",
    "Owning Sprint",
    "trace status",
    "post-P0.1 contract test PASS gate",
    "symptom",
)
SEPARATOR_CELL_RE = re.compile(r"^-+$")

# R1-F-006 adopt: PE-F-010 closure marker strict AND/AND-NOT
T01_AND_MARKER = "SP022-T01"
T01_CLOSURE_WORDS = ("closed", "実装完了", "completed", "PR #70")
T01_NEGATIVE_WORDS = ("TODO", "予定", "未完了", "pending")


def parse_section(content: str) -> tuple[list[str] | None, list[str]]:
    """R1-F-012 + R2-F-001 adopt: line-based parser, suffix-tolerant section header match.

    Section header is matched with `startswith` (not exact) so that the current
    `## Phase E adversarial closure trace (PE-F-001〜PE-F-016、...)` heading
    is accepted. Section ends at the next `## ` heading.
    """
    lines = content.split("\n")
    in_section = False
    section_lines: list[str] = []
    violations: list[str] = []
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
        return None, violations
    return section_lines, violations


def verify_header(section_lines: list[str], pack: Path) -> list[str]:
    """R1-F-003 adopt: verify first table header + separator row exact match."""
    violations: list[str] = []
    header_idx: int | None = None
    for i, line in enumerate(section_lines):
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|") and "Finding ID" in stripped:
            header_idx = i
            break
    if header_idx is None:
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_header_mismatch "
            f"evidence={pack}:phase_e_section label=header_row_not_found"
        )
        return violations
    header_cells = [c.strip() for c in section_lines[header_idx].split("|")[1:-1]]
    if tuple(header_cells) != EXPECTED_HEADER_CELLS:
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_header_mismatch "
            f"evidence={pack}:phase_e_section "
            f"label=actual={header_cells}|expected={list(EXPECTED_HEADER_CELLS)}"
        )
    if header_idx + 1 < len(section_lines):
        sep_cells = [c.strip() for c in section_lines[header_idx + 1].split("|")[1:-1]]
        if len(sep_cells) != 5 or not all(SEPARATOR_CELL_RE.match(c) for c in sep_cells):
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_header_mismatch "
                f"evidence={pack}:phase_e_section label=separator_row_invalid={sep_cells}"
            )
    return violations


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--mode", choices=["baseline-scan"], default="baseline-scan")
    # R1-F-001 adopt: --pack-path for tmp_path fixture override
    p.add_argument("--pack-path", type=Path, default=DEFAULT_PACK)
    args = p.parse_args()
    violations: list[str] = []
    pack = args.pack_path

    if not pack.exists():
        print(
            f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_pack_missing "
            f"evidence={pack} label=sp022_pack_not_found"
        )
        return 1
    content = pack.read_text(encoding="utf-8")

    section_lines, sec_violations = parse_section(content)
    violations.extend(sec_violations)
    if section_lines is None:
        print(
            f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_section_missing "
            f"evidence={pack}:1 label=phase_e_section_header_not_found"
        )
        return 1

    # R1-F-003 adopt: verify header + separator
    violations.extend(verify_header(section_lines, pack))

    section_body = "\n".join(section_lines)

    # extract rows
    rows: dict[str, str] = {}
    for row_match in ROW_RE.finditer(section_body):
        rows[row_match.group(1)] = row_match.group(0)

    # check 1: all 16 findings present + no extra (R1-F-013 adopt)
    missing = EXPECTED_FINDINGS - set(rows.keys())
    extra = set(rows.keys()) - EXPECTED_FINDINGS
    for finding_id in sorted(missing):
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_finding_missing "
            f"evidence={pack}:phase_e_section finding={finding_id}"
        )
    for finding_id in sorted(extra):
        violations.append(
            f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_finding_unexpected "
            f"evidence={pack}:phase_e_section finding={finding_id}"
        )

    # check 2: per-row column count + symptom + owning sprint (per-row exact map)
    for finding_id in sorted(rows):
        row = rows[finding_id]
        cells = [c.strip() for c in row.split("|")[1:-1]]  # strip leading/trailing empties from |...|
        if len(cells) < 5:
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_symptom_missing "
                f"evidence={pack}:{finding_id} label=row_column_count={len(cells)}_expected_5"
            )
            continue
        symptom = cells[4]
        # R1-F-004 adopt: 20 chars unified threshold (scanner + plan + pytest + DoD all use 20)
        if len(symptom) < 20:
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_symptom_missing "
                f"evidence={pack}:{finding_id} label=symptom_too_short={len(symptom)}_min=20"
            )

        # R1-F-002 + R2-F-002 adopt: SP-NNN regex token exact, exactly 1 token, equals expected
        owning_cell = cells[1]
        expected_sprint = EXPECTED_OWNING_SPRINT_BY_FINDING.get(finding_id)
        sp_tokens = [f"SP-{m}" for m in SP_TOKEN_RE.findall(owning_cell)]
        if expected_sprint is None or len(sp_tokens) != 1 or sp_tokens[0] != expected_sprint:
            violations.append(
                f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_owning_sprint_invalid "
                f"evidence={pack}:{finding_id} "
                f"label=owning_cell={owning_cell[:60]}|tokens={sp_tokens}|expected={expected_sprint}"
            )

        # R1-F-006 adopt: PE-F-010 closure marker — AND (T01_AND_MARKER) + ANY(closure words) + NONE(negative words)
        if finding_id == "PE-F-010":
            has_t01 = T01_AND_MARKER in row
            has_closure = any(w in row for w in T01_CLOSURE_WORDS)
            has_negative = any(w in row for w in T01_NEGATIVE_WORDS)
            if not (has_t01 and has_closure) or has_negative:
                violations.append(
                    f"VIOLATION reason_code=framework_intake_violation_phase_e_trace_t01_closure_marker_missing "
                    f"evidence={pack}:PE-F-010 "
                    f"label=t01={has_t01}|closure={has_closure}|negative={has_negative}"
                )

    for v in violations:
        print(v)
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main())
```

### 5.2 `scripts/ci/check_phase_e_trace.sh` (簡略)

SP022-T01/T03 と同 pattern (emergency disable + mode determination)。SOP gate と異なり diff-gate なし、baseline-scan のみ。

emergency disable 時 (R1-F-008 adopt):
```bash
if [ "${PHASE_E_TRACE_CHECK_DISABLED:-0}" = "1" ]; then
  echo "phase_e_trace_check: SKIP disabled_by=PHASE_E_TRACE_CHECK_DISABLED"
  echo "audit_marker: emergency_disable=true" >&2
  echo "audit_marker: requires_retro_pack_within_24h=true" >&2
  echo "audit_marker: ADR=ADR-00020" >&2
  exit 0
fi
```

### 5.3 `tests/deploy/test_phase_e_trace.py`

pytest fixture (positive 4 + negative 3 = 7、`--pack-path` で `tmp_path` 内 fake pack を verify、R1-F-001 adopt):

**Positive (current SP-022 で baseline pass):**
- `test_sp022_pack_trace_matrix_all_findings_present` (PE-F-001〜PE-F-016 完全一致、missing/extra なし)
- `test_sp022_pack_pe_f_010_has_t01_closure_marker` (PE-F-010 row: `SP022-T01` AND closure word AND NOT negative)
- `test_sp022_pack_symptom_column_min_20_chars` (各 row の symptom column 20+ chars、R1-F-004 adopt unified threshold)
- `test_sp022_pack_owning_sprint_per_row_exact_map` (各 row の owning sprint が `EXPECTED_OWNING_SPRINT_BY_FINDING` と一致、R1-F-002 adopt)

**Negative (tmp_path 内 fake pack、R1-F-001 adopt):**
- `test_fake_pack_missing_finding_fails` (fake で PE-F-001 削除 → `phase_e_trace_finding_missing`)
- `test_fake_pack_missing_symptom_fails` (4 column 形式の fake → `phase_e_trace_symptom_missing` or `header_mismatch`)
- `test_fake_pack_missing_t01_closure_marker_fails` (PE-F-010 row に SP022-T01 marker なし fake → `phase_e_trace_t01_closure_marker_missing`)
- `test_fake_pack_owning_sprint_multi_token_fails` (fake で `SP-013 / SP-014` 等 2 token → `phase_e_trace_owning_sprint_invalid`、R2-F-002 adopt: substring bypass を deny する regression)
- `test_fake_pack_owning_sprint_drift_token_fails` (fake で `SP-0139` / `SP-013999` 等 4+ 桁 → `phase_e_trace_owning_sprint_invalid`、R2-F-002 adopt: word boundary 確認)
- `test_fake_pack_section_header_with_suffix_passes` (fake で `## Phase E adversarial closure trace (custom suffix)` heading → section_missing にならず通過、R2-F-001 adopt: suffix 許容の positive regression)

fixture 全件で `subprocess.run([..., "--pack-path", str(tmp_pack)])` 経由で verify。

### 5.4 SP-022 Pack matrix update

Current matrix (line 230-249):
```
| Finding ID | Owning Sprint | trace status | post-P0.1 contract test PASS gate |
|---|---|---|---|
| PE-F-001 | SP-013 | (SP-013 着手時 must_ship 反映予定) | SP-013 exit gate |
...
```

Updated matrix (本 task で symptom column 追加 + PE-F-010 closure marker + PE-F-010 owner SP-016→SP-022 正規化、R1-F-007 adopt: PE-F-010 post-P0.1 gate cell の意味を「不要」ではなく「SP022-T01 で satisfied、T04 で追加 contract test なし」と限定、R3-F-R3-001 adopt: ADR-00020 `related_sprints: SP-022` + SP022-T01 closure 整合):
```
| Finding ID | Owning Sprint | trace status | post-P0.1 contract test PASS gate | symptom |
|---|---|---|---|---|
| PE-F-001 | SP-013 | (SP-013 着手時 must_ship 反映予定) | SP-013 exit gate | STANDARD_ROLE_IDS は custom role_id として禁止 (reserved namespace) / `role_scope=global + role_id=reviewer` で scope 含める / `receiver_kind=role` は server-owned role resolver |
...
| PE-F-010 | SP-022 | ✅ closed by SP022-T01 (PR #70 merged 2026-05-19、ADR-00020 8 verify CI 機械化、38 adopt findings) | SP022-T01 satisfied; no SP-016 exit gate (ADR-00020 + SP-022 owner、PE-F-010 CI closure already satisfied、T04 で追加 contract test なし) | Framework intake CI 機械検査: license / external API / persistence / telemetry denylist (8 verify ADR-00020) |
...
```

symptom 文字列は `docs/設計検討/phase-c-multi-agent-spec-draft.md` §11.3 から短文化抽出。

### 5.5 CI workflow integration

SP022-T01/T03 pattern 踏襲。Framework intake check と Drill timer alert-only check 直後に新 step (R1-F-011 adopt: canonical step name `Phase E trace audit check (SP022-T04)`):

```yaml
      - name: Phase E trace audit check (SP022-T04)
        # Emergency disable: PHASE_E_TRACE_CHECK_DISABLED=1 repository variable (admin only)
        env:
          PHASE_E_TRACE_CHECK_DISABLED: ${{ vars.PHASE_E_TRACE_CHECK_DISABLED }}
        run: bash scripts/ci/check_phase_e_trace.sh
```

## 6. 検証手順

```bash
# 1. script syntax
bash -n scripts/ci/check_phase_e_trace.sh
uv run --no-sync python -m py_compile scripts/ci/_phase_e_trace_verifier.py

# 2. local baseline-scan (SP-022 matrix update 後)
bash scripts/ci/check_phase_e_trace.sh
# 期待: phase_e_trace_check: PASS (mode=baseline-scan)

# 3. pytest (10 fixtures: 4 positive + 6 negative、R1-F-001 + R2-F-001 + R2-F-002 adopt)
uv run pytest tests/deploy/test_phase_e_trace.py -q
# 期待: 10 passed

# 4. regression: SP022-T01/T03 既存 fixture + ruff + mypy 全 PASS
uv run ruff check backend tests
uv run mypy backend
uv run pytest tests/deploy/ tests/citations/ -q
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (`.claude/rules/codex-usage-policy.md §14.1`、3+ file 横断 + audit-only invariant 直結):
- `codex-plan-review R1 minimum + 採否判定` 経路必須

### 7.1 期待される review focus

1. **matrix column count**: 4 → 5 column 化で既存 row migration の正確性 + header/separator 完全一致 verify (R1-F-003 adopt)
2. **symptom 短文化**: phase-c-multi-agent-spec-draft.md §11.3 からの抽出文の正確性
2.5. **symptom と finding の対応誤り** (R1-F-005 adopt: T04 は手動レビュー観点で担保): 各 PE-F-XXX row の symptom が §11.3 の対応する catalog entry に整合しているか、抽出元と短文化結果の対応 1:1 を確認
3. **PE-F-010 closure marker 形式**: `SP022-T01` AND closure word AND NOT negative word の AND/AND-NOT パターン (R1-F-006 adopt: 偽陽性 `SP022-T01 未完了` 等の deny)
4. **per-row owning sprint mapping invariant**: `EXPECTED_OWNING_SPRINT_BY_FINDING` 固定 mapping (R1-F-002 adopt、PR #67 で確立、本 task では mapping 変更なし)
5. **emergency disable 出力**: SP022-T01/T03 同様の `audit_marker:` stderr + `phase_e_trace_check: SKIP` stdout (R1-F-008 adopt)
6. **pytest fixture coverage**: positive 4 件 + negative 3 件、negative は `--pack-path` で `tmp_path` 内 fake pack を direct verify (R1-F-001 adopt)
7. **extra finding (PE-F-017+) 検出**: `framework_intake_violation_phase_e_trace_finding_unexpected` reason_code emit (R1-F-013 adopt)
8. **line-based parser の境界判定**: `+2` offset 廃止、`line.startswith("## ")` で次 level-2 heading を切り出し (R1-F-012 adopt)

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| matrix column 拡張で table 体裁崩れ | pytest fail | tests/deploy で existing structure を verify、本 PR 内で update 後 verify pass、header/separator exact match (R1-F-003 adopt) |
| symptom 文字列の抽出ミス | 不正確な audit | phase-c draft §11.3 から direct quote、変更不要 + 手動レビュー観点 §7.1 #2.5 (R1-F-005 adopt) |
| PE-F-010 closure marker mismatch | 偽 violation | AND/AND-NOT (R1-F-006 adopt) で偽陽性防止、`SP022-T01` + 完了表現 OR + 否定語 NOT |
| owning sprint mapping drift | post-P0.1 で SP-013-020 着手時の trace update 必要 | T04 では現 mapping 維持、変更は別 PR (owning sprint 起票時)、`EXPECTED_OWNING_SPRINT_BY_FINDING` 固定で drift 検出 (R1-F-002 adopt) |
| Codex review が delayed | merge 遅延 | 30 min max polling、admin merge bypass (CI billing failure 継続) |
| extra finding (PE-F-017+) silent pass | 想定外 ID 混入 | `framework_intake_violation_phase_e_trace_finding_unexpected` reason_code (R1-F-013 adopt) |

### Rollback (3 階層、SP022-T01/T03 と同)

- Tier 1 (pre-merge local): `git restore` 対象 file
- Tier 2 (post-merge): `PHASE_E_TRACE_CHECK_DISABLED=1` repository variable disable + 24h retro (SP-022 `## Review` 記録)
- Tier 3 (break-glass): script を `exit 0` skeleton 化

## 9. commit 戦略

single commit。SP022-T01/T03 pattern 踏襲。

## 10. PR workflow

SP022-T01/T03 pattern 踏襲: plan draft → codex-plan-review R1-R3 → 実装 → pre-commit verify → commit/push/PR → Codex auto-review polling + multi-round adopt + admin merge bypass。

## 11. DoD

- [ ] `scripts/ci/check_phase_e_trace.sh` + `_phase_e_trace_verifier.py` が SP-022 Pack の trace matrix を機械検査
- [ ] `--pack-path` argument で fixture override 可能 (R1-F-001 adopt)
- [ ] SP-022 §Phase E trace matrix が **5 column** (Finding ID / Owning Sprint / trace status / post-P0.1 gate / symptom) で 16 finding 全件カバー、extra なし (R1-F-013 adopt)
- [ ] table header + separator row が exact match (R1-F-003 adopt)
- [ ] PE-F-010 row に `SP022-T01` + closure word (AND) + 否定語 NOT (R1-F-006 adopt)
- [ ] per-row owning sprint mapping が `EXPECTED_OWNING_SPRINT_BY_FINDING` と一致、**exactly 1 token + 完全一致** (R1-F-002 + R2-F-002 adopt: substring `in` 比較禁止)
- [ ] section header parser は **`startswith("## Phase E adversarial closure trace")` で suffix 許容** (R2-F-001 adopt: 現行 SP-022 見出し `(PE-F-001〜...)` suffix を block しない)
- [ ] 各 row の symptom 20+ chars 統一 (R1-F-004 adopt: scanner + plan + pytest + DoD 全て 20 chars 基準)
- [ ] `tests/deploy/test_phase_e_trace.py` **10 fixture 全 PASS** (4 positive + 6 negative with `--pack-path` tmp_path、R2-F-001/R2-F-002 regression fixture 3 件追加)
- [ ] `.github/workflows/ci-smoke.yml` "Phase E trace audit check (SP022-T04)" step 追加 + `vars.PHASE_E_TRACE_CHECK_DISABLED` repository variable 経由 (R1-F-011 adopt: canonical step name)
- [ ] emergency disable 出力: `phase_e_trace_check: SKIP` stdout + `audit_marker:` stderr 3 行 (R1-F-008 adopt)
- [ ] SP-022 Pack `## Review` に SP022-T04 完了記録
- [ ] SP022-T01/T03 既存 fixture 全 PASS (regression なし)
- [ ] **codex-plan-review R{N} findings are triaged adopt/defer/reject, and all adopted CRITICAL/HIGH are resolved before implementation** (R1-F-010 adopt: 旧 `CRITICAL=0 + HIGH≤2 clean` を厳格化、計画段階で HIGH 残存を曖昧に許容しない)
- [ ] PR Codex auto-review R{N} clean (採否判定 3 分類 + multi-round polish)

## 12. 関連

- ADR-00020 (Framework Intake Checklist) — PE-F-010 を SP022-T01 で実装完了
- SP-022 §Phase E adversarial closure trace matrix (本 task で拡張)
- `docs/設計検討/phase-c-multi-agent-spec-draft.md` §11.3 (Strengthening Catalog、PE-F-001〜PE-F-016 symptom source)
- `docs/設計検討/phase-h-closure-ledger.md` (closure history)
- SP022-T01 PR #70 / SP022-T03 PR #71 — 確立 pattern (Python scanner + bash wrapper + pytest fixture + emergency disable + admin merge bypass)

## 13. R1+R2+R3 plan-review findings adoption log

R1 (2026-05-19 23:52, codex-plan-review): 13 findings, **全件 adopt** (HIGH×3 / MEDIUM×6 / LOW×4).
R2 (2026-05-20 00:06, codex-plan-review): 2 HIGH findings, **全件 adopt** (F-R2-001 section header suffix + F-R2-002 SP-NNN token exact match).
R3 (2026-05-20 00:13, codex-plan-review): 1 CRITICAL finding, **adopt** (F-R3-001 PE-F-010 owner SP-016→SP-022、ADR-00020 `related_sprints: SP-022` + SP-016 Pack 実 PE-F refs PE-F-006/PE-F-014 のみと整合)。**READY for implementation** (CRITICAL=0 残存、HIGH ≤ 2 satisfied)。

| ID | severity | category | summary | adopted location |
|---|---|---|---|---|
| F-001 | HIGH | ambiguity | verifier に `--pack-path` 追加で fixture override | §3.1 #2, §4.2, §5.1 (argparse), §5.3 (tmp_path), §11 DoD |
| F-002 | HIGH | missing | per-row owning sprint mapping (`EXPECTED_OWNING_SPRINT_BY_FINDING`) で drift 検出 | §4.1, §4.4, §5.1, §7.1 #4, §8 mitigation, §11 DoD |
| F-003 | HIGH | inconsistency | table header + separator row exact match verify | §4.1, §4.4, §5.1 (verify_header), §7.1 #1, §11 DoD |
| F-004 | MEDIUM | inconsistency | symptom threshold 20 chars 統一 (plan/scanner/pytest/DoD) | §4.1, §5.1 (`< 20`), §5.3 (test name `min_20_chars`), §11 DoD |
| F-005 | MEDIUM | missing | T04 audit-only に絞り、symptom と finding の対応誤りは手動レビュー §7.1 #2.5 | §3.2, §7.1 #2.5, §8 mitigation |
| F-006 | MEDIUM | risk | PE-F-010 closure marker は AND `SP022-T01` + ANY 完了表現 + NONE 否定語 | §4.1, §5.1 (T01_AND_MARKER + T01_CLOSURE_WORDS + T01_NEGATIVE_WORDS), §7.1 #3, §11 DoD |
| F-007 | MEDIUM | ambiguity | PE-F-010 post-P0.1 gate cell の意味を「不要」ではなく「T01 で satisfied、T04 追加 contract test なし」と限定 | §5.4 |
| F-008 | MEDIUM | missing | emergency disable: stdout `phase_e_trace_check: SKIP` + stderr `audit_marker:` 3 行 | §4.3, §5.2, §7.1 #5, §11 DoD |
| F-009 | MEDIUM | inconsistency | `pack_missing` reason_code を §4.4 + negative fixture に追加 | §4.4 |
| F-010 | LOW | planning | DoD 強化: 計画段階で adopted CRITICAL/HIGH 全件 resolved を要求 | §11 DoD |
| F-011 | LOW | ambiguity | CI step name canonical: `Phase E trace audit check (SP022-T04)` | §1 #5, §3.1 #5, §5.5, §11 DoD |
| F-012 | LOW | risk | section truncate を line-based parser 化 (`+2` offset 廃止) | §4.2, §5.1 (parse_section), §7.1 #8 |
| F-013 | LOW | missing | extra finding (PE-F-017+) を violation: `phase_e_trace_finding_unexpected` | §4.1, §4.4, §5.1 (extra set), §7.1 #7, §8 mitigation, §11 DoD |
| F-R2-001 | HIGH | inconsistency | section header parser: `startswith("## Phase E adversarial closure trace")` で suffix 許容、現行 SP-022 見出し `(PE-F-001〜...)` を block しない | §4.1, §4.2 step 2, §5.1 (SECTION_HEADER_PREFIX, parse_section), §5.3 (suffix passes fixture), §11 DoD |
| F-R2-002 | HIGH | risk | owning sprint cell から `SP-\d{3}` regex 全件抽出、exactly 1 token + 完全一致、`SP-013 / SP-014` / `SP-0139` / `not SP-013; now SP-014` 等の substring bypass を deny | §4.1, §4.2 step 8, §5.1 (SP_TOKEN_RE, findall + exactly 1), §5.3 (multi_token + drift_token fixtures), §11 DoD |
| F-R3-001 | CRITICAL | inconsistency | PE-F-010 owner を SP-016→SP-022 へ正規化 (ADR-00020 `related_sprints: SP-022` + SP-016 Pack 実 PE-F refs PE-F-006/PE-F-014 のみで PE-F-010 を owning しない drift を解消)、`EXPECTED_OWNING_SPRINTS` に `SP-022` 追加、`EXPECTED_OWNING_SPRINT_BY_FINDING["PE-F-010"] = "SP-022"`、post-P0.1 gate cell を `SP022-T01 satisfied; no SP-016 exit gate` に変更 | §3.2 (scope 例外明文化), §5.1 (EXPECTED_OWNING_SPRINTS + BY_FINDING), §5.4 (PE-F-010 row PE-F-010 → SP-022) |
