# SP022-T08 Batch 1: Signed journal verification CLI (offline JSONL mode)

最終更新: 2026-05-20 (r3、R1 17 + R2 2 = 19 件全件 adopt: R2 HIGH×2 architecture/compatibility fix)

`plan_status`: 🟥 heavy (T08 batch 分割の batch 1、SP-012 carry-over 9 件のうち **signed journal verification CLI** 単独 scope、CRITICAL invariant 直結 = audit_events hash chain tamper detection)

## 1. 目的 (Goal)

Sprint 12 batch 10 (PR #66) で完成済の **signed journal hash chain pure function pipeline** (`backend/app/services/audit/signed_journal.py`) を **CLI wrapper** で expose、SP-012 §128 host migration drill / SP022-T09 実機 drill / post-P0.1 audit verification の operational tool として確立。

具体的に本 batch で:

1. `scripts/taskhub_admin.py` の `verify` subcommand に `--signed-journal` flag + `--input <jsonl>` 引数追加
2. **offline JSONL verification mode**: 標準入力または file から audit_events を JSON Lines として読み、`build_signed_journal_chain` で chain を構築、`final_hash` / `entry_count` を出力。`--expected-final-hash <hex>` 指定時は computed と比較して tamper detection
3. JSONL schema: 各 line は `{id, event_type, tenant_id, actor_id, principal_id, correlation_id, trace_id, event_payload, created_at}` の JSON object (DB row mirror、AuditEvent ORM の attributes を duck-typing)
4. CLI 自体は **DB 接続なし** (Phase 1 = offline mode 、actual DB connection / session が不要)、本 batch 1 では `taskhub_signed_journal_offline.py` を独立 module として配置。**注 (R2-F-001 adopt)**: `signed_journal.py` は `backend.app.db.models.audit_event.AuditEvent` を import (型注釈用)、`backend.app.services.audit.__init__` も `AuditExporter` を eager import するため、**Python module import の transitivity で `backend.app.db` chain も import されることは避けられない**。「DB 接続なし」とは "actual DB session 不要" の意味 (CLI 起動時に asyncpg/sqlalchemy connection は確立しない)、ORM models を **import するだけ** は許容。Phase 2 で `signed_journal_core.py` 等への pure 抽出を判断 (本 batch 1 では scope 外)
5. Exit code 0 = PASS / 1 = tamper detected (or `--expected-final-hash` mismatch) / 2 = CLI usage error

**post-P0.1 carry-over (本 batch 対象外)**: real DB integration (BL-0149 endpoint + AuditEventRepository.append 経由)、frontend dashboard wiring、private staging E2E は **batch 2-5 で実装**。

## 2. 背景 (Background)

- Sprint 12 batch 10 (PR #66 sha 4c07b86 merged) で `SignedJournalChain` + `build_signed_journal_chain` + `verify_signed_journal_chain` を pure function pipeline で完成 (BL-0149 evidence chain 4-stage: Acceptance Artifact → Audit Payload → AuditEvent ORM → SignedJournalChain)
- pure function は `backend/app/services/audit/signed_journal.py` 配下、AuditEvent ORM 受領 (duck-typed)、RFC 8785 JCS canonical + NFC UTF-8 + SHA-256、`final_hash` invariant + `previous_hash` chain linking + `False` fail-closed on tamper
- T08 全体 scope (SP-022 line 68): taskhub real I/O (10 subcommands all) + 実 DB write integration (BL-0149 sign-off endpoint + AuditEventRepository.append) + signed journal CLI + private staging E2E + frontend dashboard backend API wiring
- T08 を batch 分割 (`.claude/reference/task-planning-matrix.md` §2 で公式化): batch 1 = signed journal CLI **offline mode** / batch 2 = backup-restore real I/O / batch 3 = migrate-status-verify real I/O / batch 4 = BL-0149 実 DB write / batch 5 = signed journal CLI **DB mode** + private staging E2E / batch 6 = frontend backend wiring
- 本 batch 1 は **autonomous-friendly** な atomic scope: pure function + CLI wrapper + JSONL test fixtures (DB / Docker / Redis 不要)

## 3. Scope (実装範囲)

### 3.1 must_ship (本 PR 内)

| # | 対象 | 種別 |
|---|---|---|
| 1 | `scripts/taskhub_signed_journal_offline.py` (NEW) | offline JSONL verification module: JSONL line parser + `AuditEventLike` dataclass (duck-typed AuditEvent mirror、DB import なし) + `verify_jsonl_signed_journal()` wrapper |
| 2 | `scripts/taskhub_admin.py` (MODIFY): `_cmd_verify` extension + `--signed-journal` + `--input` + `--expected-final-hash` 引数追加 | verify subcommand に signed journal mode 追加、既存 `--integrity` / `--network-invariant` / `--multi-agent` skeleton flag と共存 |
| 3 | `tests/scripts/test_taskhub_signed_journal_offline.py` (NEW) | unit fixtures: positive (valid chain PASS) + negative (tamper / insertion / deletion / reorder / malformed JSONL / missing fields / NaN-Inf reject / impossible datetime) + cross-platform deterministic (build/verify reference) |
| 4 | `tests/scripts/test_taskhub_admin.py` (MODIFY) | `taskhub verify --signed-journal --input <jsonl>` の CLI 経由 fixture: positive + negative (tamper / missing file / malformed input) + skeleton flag との argparse 共存 verify |
| 5 | `.claude/plans/sp022-t08-batch1-signed-journal-cli.md` (本計画、commit 含む) | - |
| 6 | `docs/sprints/SP-022_framework_intake_hardening.md` (MODIFY) | `## Review` に SP022-T08 batch 1 完了記録、`plan_status` を `🟥 heavy + batch 分割 (batch 1 完了済、batch 2-6 carry-over)` に update |

### 3.2 対象外 (本 batch 1 では実装しない)

- **DB integration mode** (`taskhub verify --signed-journal --from-db`): batch 5 で実装、AuditEventRepository.fetch_ordered + asyncpg session + `--tenant-id` / `--project-id` filter
- **`taskhub verify --signed-journal --tail <N>`** (最新 N 件のみ verify): batch 5
- **frontend dashboard 表示**: batch 6 で実装、`/api/audit/signed-journal-status` endpoint + Server Component
- **BL-0149 sign-off endpoint 実 DB write**: batch 4 で実装、P0AcceptanceAuditWriter.append() → AuditEventRepository.append() chain
- **backup-restore 実 I/O / migrate 実 I/O**: T02 Phase 2-3 + T08 batch 2-3 で実装
- **private staging CI/E2E** (signed journal を CI で run): batch 5 で実装
- **age key 安全運搬 / SOPS rotation**: T02 Phase 2-3 + T08 別 batch
- **Signed journal CLI を destructive subcommand に分類して approval gate を通す**: 本 batch 1 では verify は **non-destructive** (read-only)、Phase 1 T02 と同 invariant
- **JSONL 入力の自動生成 (DB から export)**: batch 5 で実装、本 batch 1 は **manual / external tool 経由 JSONL** を verify する operational tool

## 4. CLI 設計

### 4.1 引数

```
taskhub verify --signed-journal --input <path>.jsonl [--expected-final-hash <sha256-hex>] [--max-entries <int>] [--max-line-bytes <int>]
```

- `--signed-journal`: 本 mode を有効化。R1-F-008 adopt: 既存 `--integrity` / `--network-invariant` / `--multi-agent` skeleton flag と **argparse mutually exclusive group** にする (silent ignore 廃止、operator 誤解防止)
- `--input <path>.jsonl`: JSONL file path (`-` 指定で stdin 読込)
- `--expected-final-hash <hex>`: 64 char SHA-256 hex (オプション)。指定時は computed `final_hash` と比較、不一致なら tamper detection で exit 1。**R1-F-007 adopt**: lowercase hex 限定 (regex `^[0-9a-f]{64}$`)、違反は **exit 2 usage error** (tamper でなく invalid arg)
- `--max-entries <int>`: chain build 中に entries が `max_entries` を超えたら abort (DoS 防御)。**R1-F-015 adopt**: 範囲 `1 <= N <= 100000`、範囲外は exit 2、default 100000
- `--max-line-bytes <int>`: 1 行あたり最大バイト数 (R1-F-002 adopt: DoS 防御強化)、範囲 `1024 <= N <= 1048576` (1MB)、default 65536 (64KB)、超過は exit 2

### 4.2 出力 (stdout)

```json
{
  "mode": "signed-journal-offline",
  "entry_count": 42,
  "final_hash": "abc123...def",
  "verification_performed": true,           // R1-F-014 adopt: --expected-final-hash 指定時 true
  "expected_final_hash": "abc123...def",    // --expected-final-hash 指定時のみ
  "verified": true,                         // --expected-final-hash 指定時のみ
  "tamper_detected": false,                 // --expected-final-hash 指定 + 不一致時のみ true
  "warnings": [],                           // R1-F-012 adopt: empty_chain 等の warning (reason_code とは別軸)
  "ignored_fields": [],                     // R1-F-017 adopt: extra fields は reject (本 batch では使用しない予定、defensive design)
  "reason_code": "signed_journal_offline_verified"
}
```

**R1-F-014 adopt**: `--expected-final-hash` 未指定時は `verification_performed=false` を明示、`verified` / `tamper_detected` field は不在 (computed final_hash のみ出力、verifier として弱い旨を明示)。

### 4.3 Exit code (R1-F-003 adopt: 例外分類を明示)

- **0 (PASS)**: chain build 成功 + (`--expected-final-hash` 未指定 OR computed と一致)
- **1 (tamper detected)**: `--expected-final-hash` ≠ computed final_hash (operator が明示的 verification を要求した場合の tamper 検出)
- **2 (CLI usage error)**: 以下すべて
  - `--input` file not found / read 不能
  - `--signed-journal` 指定 + `--input` 未指定
  - `--expected-final-hash` regex 違反 (`^[0-9a-f]{64}$` 不一致)
  - `--max-entries` / `--max-line-bytes` 範囲外
  - JSONL parse error / required field 欠落 / type 不正 / NaN/Infinity reject / impossible datetime
  - max_entries / max_line_bytes 超過
  - extra fields in JSONL line (R1-F-017 adopt)
  - 一行 / payload 内の structural anomaly

**R1-F-003 adopt**: `build_signed_journal_chain` 内の ValueError は **input schema** に起因するもの (NaN/Inf reject 等) → exit 2、`verify_signed_journal_chain` の False return (chain structural inconsistency) → exit 1 として **専用例外型または result enum** で区別する。本 batch 1 では `build_signed_journal_chain` の ValueError は input invalidity として扱う方針 (CLI 側で input layer での catch → exit 2)。

### 4.4 JSONL line schema (strict、R1-F-006 + R1-F-010 + R1-F-016 + R1-F-017 adopt)

**Strict structural schema** (R1-F-016 adopt: event_type の domain enum validation は本 batch では行わない、structural validation のみ。Operational note: event_type typo は expected_final_hash mismatch で検出する前提、unit JSONL verify では検出しない)。

各 line は次の field を持つ JSON object (extra fields **reject**、本 batch defensive、R1-F-017 adopt):

| field | type | nullability | note |
|---|---|---|---|
| `id` | str (UUID hex format) | required non-empty | audit_event_id、ORM `id` と同じ string シリアライズで hash 一致 |
| `event_type` | str | required non-empty | structural のみ (enum validation なし、R1-F-016 adopt) |
| `tenant_id` | int | required | `>= 0` |
| `actor_id` | str (UUID) \| null | **required nullable** (R1-F-006 adopt: explicit null 必須、欠落 → exit 2) | DB row mirror 厳密性のため null 明示必須 |
| `principal_id` | str (UUID) \| null | **required nullable** | 同上 |
| `correlation_id` | str \| null | **required nullable** | 同上 |
| `trace_id` | str \| null | **required nullable** | 同上 |
| `event_payload` | JSON object | required | dict (`{}` 許容)、**`json.loads(parse_constant=...)` で NaN/Infinity reject** (R1-F-004 adopt) |
| `created_at` | str (ISO 8601 + **timezone-aware 必須**) | required | R1-F-010 adopt: naive datetime は exit 2 (timezone-aware 必須化、audit verification の CRITICAL invariant に寄せる) |

Required field 欠落 / type 不正 / extra field 存在 / NaN/Inf in event_payload / naive datetime → exit 2 + reason_code (下記 §4.5)。

**R1-F-001 adopt — AuditEventLike contract**:
- `id`: str UUID hex (lowercase or canonical UUID string、`_serialize_audit_event` が `str(audit_event.id)` で変換するため string-form で一致)
- `actor_id` / `principal_id`: str (UUID hex) または None、同上
- `tenant_id`: int (`_serialize_audit_event` が `int(audit_event.tenant_id)` で int-cast、JSONL は int で固定)
- `created_at`: timezone-aware `datetime`、`_serialize_audit_event` が `astimezone(UTC).isoformat()` で UTC normalize + 出力。JSONL string は `datetime.fromisoformat()` でパース後、tzinfo の有無を verify。

**reference hash test** (R1-F-001 + R1-F-009 adopt): DoD に DB mirror fixture 由来の reference final_hash を含める。fixture data + computed final_hash を test に固定し、cross-platform deterministic を verify。

### 4.5 Reason codes (R1-F-003 + R1-F-012 + R1-F-014 adopt: 例外分類 + empty_chain 優先順位)

| reason_code | trigger | exit code |
|---|---|---|
| `signed_journal_offline_verified` | chain build + verify PASS (`--expected-final-hash` 指定 + 一致) | 0 |
| `signed_journal_offline_hash_computed` | `--expected-final-hash` 未指定、computed のみ出力 (R1-F-014 adopt: verifier として弱い旨を分離) | 0 |
| `signed_journal_offline_input_not_found` | `--input` file 不在 / read 不能 | 2 |
| `signed_journal_offline_input_too_large` | entries > `--max-entries` OR 行 > `--max-line-bytes` | 2 |
| `signed_journal_offline_jsonl_schema_invalid` | line parse / required field 欠落 / type 不正 / extra field / naive datetime (R1-F-006 + R1-F-010 + R1-F-017 adopt) | 2 |
| `signed_journal_offline_jsonl_non_finite_float` | event_payload に NaN/Infinity (R1-F-004 adopt: json.loads parse_constant で reject) | 2 |
| `signed_journal_offline_expected_hash_invalid` | `--expected-final-hash` regex 違反 (R1-F-007 adopt: usage error) | 2 |
| `signed_journal_offline_expected_hash_mismatch` | `--expected-final-hash` ≠ computed `final_hash` (R1-F-012 adopt: empty_chain と同居時は mismatch を優先) | 1 |
| `signed_journal_offline_empty_chain` | JSONL 0 行、`--expected-final-hash` 未指定なら exit 0 (`final_hash = SIGNED_JOURNAL_INITIAL_HASH`)、empty_chain は **`warnings` array に追加**、reason_code は exit 判定の主理由を維持 (R1-F-012 adopt) | 0 (mismatch 時は 1) |
| `signed_journal_offline_arg_out_of_range` | `--max-entries` / `--max-line-bytes` 範囲外 (R1-F-015 adopt) | 2 |

## 5. 実装詳細

### 5.1 `scripts/taskhub_signed_journal_offline.py` 構造

```python
"""Offline JSONL signed journal verification (SP022-T08 batch 1).

`backend/app/services/audit/signed_journal.py` の pure function を wrap、
DB 接続なしで JSONL 経由 audit_events を verify する CLI helper.

AuditEvent ORM は不要 (duck-typed): `id`, `event_type`, `tenant_id`,
`actor_id`, `principal_id`, `correlation_id`, `trace_id`, `event_payload`,
`created_at` の attribute access のみ.

DB integration は batch 5 で別 module (taskhub_signed_journal_db.py 等) で実装、
本 module は offline mode に絞る (import scope を minimal に保つため backend.app.db
は import しない).
"""

from __future__ import annotations
import dataclasses
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator
from uuid import UUID

# pure function pipeline import (backend.app.services.audit.signed_journal)
# 注: signed_journal.py は AuditEvent ORM type-hint を持つが、_serialize_audit_event
# は attribute access のみで duck-typing 可能。
from backend.app.services.audit.signed_journal import (
    SignedJournalChain,
    build_signed_journal_chain,
)

DEFAULT_MAX_ENTRIES = 100000

# Required fields for JSONL line schema (R1 plan strictness)
_REQUIRED_FIELDS = frozenset({
    "id", "event_type", "tenant_id", "event_payload", "created_at",
})
# Optional fields (null 許容)
_OPTIONAL_FIELDS = frozenset({
    "actor_id", "principal_id", "correlation_id", "trace_id",
})


@dataclasses.dataclass(frozen=True)
class AuditEventLike:
    """ORM-free AuditEvent mirror for offline signed journal verification.

    `_serialize_audit_event` (signed_journal.py 内) が要求する全 attribute を持つ
    dataclass、import scope に backend.app.db を含めない (CLI tool として軽量起動)。
    """
    id: str  # UUID hex string
    event_type: str
    tenant_id: int
    actor_id: str | None
    principal_id: str | None
    correlation_id: str | None
    trace_id: str | None
    event_payload: dict[str, Any]
    created_at: datetime


def _parse_jsonl_line(line: str, line_no: int) -> AuditEventLike:
    """JSONL 1 行 → AuditEventLike。schema 違反は ValueError raise."""
    try:
        data = json.loads(line)
    except json.JSONDecodeError as exc:
        msg = f"line {line_no}: invalid JSON: {exc}"
        raise ValueError(msg) from exc
    if not isinstance(data, dict):
        msg = f"line {line_no}: top-level must be JSON object"
        raise ValueError(msg)
    missing = _REQUIRED_FIELDS - set(data.keys())
    if missing:
        msg = f"line {line_no}: missing required fields {sorted(missing)}"
        raise ValueError(msg)
    # type validation
    if not isinstance(data["id"], str) or not data["id"]:
        msg = f"line {line_no}: 'id' must be non-empty string"
        raise ValueError(msg)
    if not isinstance(data["event_type"], str) or not data["event_type"]:
        msg = f"line {line_no}: 'event_type' must be non-empty string"
        raise ValueError(msg)
    if not isinstance(data["tenant_id"], int) or data["tenant_id"] < 0:
        msg = f"line {line_no}: 'tenant_id' must be non-negative int"
        raise ValueError(msg)
    if not isinstance(data["event_payload"], dict):
        msg = f"line {line_no}: 'event_payload' must be object"
        raise ValueError(msg)
    # parse created_at
    if not isinstance(data["created_at"], str):
        msg = f"line {line_no}: 'created_at' must be ISO 8601 string"
        raise ValueError(msg)
    try:
        created_at = datetime.fromisoformat(data["created_at"])
    except ValueError as exc:
        msg = f"line {line_no}: 'created_at' invalid ISO 8601: {exc}"
        raise ValueError(msg) from exc
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=timezone.utc)

    def _opt_str(key: str) -> str | None:
        v = data.get(key)
        if v is None:
            return None
        if not isinstance(v, str):
            msg = f"line {line_no}: '{key}' must be string or null"
            raise ValueError(msg)
        return v

    return AuditEventLike(
        id=data["id"],
        event_type=data["event_type"],
        tenant_id=data["tenant_id"],
        actor_id=_opt_str("actor_id"),
        principal_id=_opt_str("principal_id"),
        correlation_id=_opt_str("correlation_id"),
        trace_id=_opt_str("trace_id"),
        event_payload=data["event_payload"],
        created_at=created_at,
    )


def _read_jsonl(input_path: str, max_entries: int) -> Iterator[AuditEventLike]:
    """Stream JSONL file (or stdin if path == '-')。skip blank lines。"""
    source: Any
    if input_path == "-":
        source = sys.stdin
    else:
        p = Path(input_path)
        if not p.exists():
            msg = f"input file not found: {input_path}"
            raise FileNotFoundError(msg)
        source = p.open("r", encoding="utf-8")
    try:
        count = 0
        for line_no, line in enumerate(source, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            count += 1
            if count > max_entries:
                msg = f"input exceeds max_entries={max_entries}"
                raise ValueError(msg)
            yield _parse_jsonl_line(stripped, line_no)
    finally:
        if source is not sys.stdin:
            source.close()


def verify_jsonl_signed_journal(
    input_path: str,
    *,
    expected_final_hash: str | None = None,
    max_entries: int = DEFAULT_MAX_ENTRIES,
) -> dict[str, Any]:
    """Build chain from JSONL, optionally compare with expected_final_hash.

    Returns dict with keys: mode, entry_count, final_hash, verified (if expected
    provided), tamper_detected (if expected provided), reason_code.

    Raises FileNotFoundError, ValueError as appropriate (caller maps to exit codes).
    """
    events = list(_read_jsonl(input_path, max_entries))
    try:
        chain = build_signed_journal_chain(events)
    except ValueError:
        raise  # caller maps to exit 1

    result: dict[str, Any] = {
        "mode": "signed-journal-offline",
        "entry_count": chain.entry_count,
        "final_hash": chain.final_hash,
        "reason_code": "signed_journal_offline_verified",
    }
    if expected_final_hash is not None:
        verified = chain.final_hash == expected_final_hash
        result["expected_final_hash"] = expected_final_hash
        result["verified"] = verified
        result["tamper_detected"] = not verified
        if not verified:
            result["reason_code"] = "signed_journal_offline_expected_hash_mismatch"
    if chain.entry_count == 0:
        result["reason_code"] = "signed_journal_offline_empty_chain"
    return result
```

### 5.2 `scripts/taskhub_admin.py` _cmd_verify extension

```python
def _cmd_verify(args: argparse.Namespace) -> int:
    """`taskhub verify [--integrity] [--network-invariant] [--multi-agent] [--signed-journal --input <path>]` skeleton + offline signed journal mode."""
    # SP022-T08 batch 1: signed journal offline mode (real I/O、非 skeleton)
    if args.signed_journal:
        from scripts.taskhub_signed_journal_offline import (
            verify_jsonl_signed_journal,
            DEFAULT_MAX_ENTRIES,
        )
        if not args.input:
            print("ERROR: --signed-journal requires --input <path>.jsonl", file=sys.stderr)  # noqa: T201
            return 2
        try:
            result = verify_jsonl_signed_journal(
                args.input,
                expected_final_hash=args.expected_final_hash,
                max_entries=args.max_entries or DEFAULT_MAX_ENTRIES,
            )
        except FileNotFoundError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)  # noqa: T201
            return 2
        except ValueError as exc:
            print(f"ERROR: {exc}", file=sys.stderr)  # noqa: T201
            return 2
        print(json.dumps(result, sort_keys=True))  # noqa: T201
        if result.get("tamper_detected"):
            return 1
        return 0

    # existing skeleton logic for --integrity / --network-invariant / --multi-agent
    checks: list[str] = []
    # ... (existing) ...
```

新 argparse args:

```python
sub_verify.add_argument(
    "--signed-journal",
    action="store_true",
    help="signed journal hash chain verification (SP022-T08 batch 1、offline JSONL mode)",
)
sub_verify.add_argument(
    "--input",
    type=str,
    default=None,
    help="JSONL file path (or '-' for stdin)、--signed-journal と組合せ必須",
)
sub_verify.add_argument(
    "--expected-final-hash",
    type=str,
    default=None,
    help="expected SHA-256 hex (64 chars)、computed final_hash と比較",
)
sub_verify.add_argument(
    "--max-entries",
    type=int,
    default=None,
    help="abort if JSONL exceeds N entries (default 100000、DoS 防御)",
)
```

### 5.3 `tests/scripts/test_taskhub_signed_journal_offline.py` 構造 (positive 7 + negative 18 + reference vector 1 = 26 fixtures)

**Positive (7):**
- `test_verify_valid_chain_passes` (3 events、computed `final_hash` returned)
- `test_verify_empty_jsonl_returns_initial_hash` (0 lines、`final_hash == SIGNED_JOURNAL_INITIAL_HASH`、empty_chain warning)
- `test_verify_with_matching_expected_hash` (`--expected-final-hash` 一致 → verified=True、tamper_detected=False、verification_performed=True)
- `test_verify_without_expected_hash_returns_hash_computed_reason` (R1-F-014 adopt: verification_performed=false、reason_code=signed_journal_offline_hash_computed)
- `test_verify_stdin_input` (`input_path == '-'` で stdin から読込)
- `test_verify_blank_lines_skipped` (blank / whitespace-only 行は無視)
- `test_verify_reference_vector_cross_platform_deterministic` (R1-F-001 + R1-F-009 adopt: DB mirror fixture data + 固定 reference final_hash で deterministic verify、timezone offset / microseconds / NFD Unicode / nested key ordering)

**Negative (18):**
- `test_verify_input_file_not_found` (FileNotFoundError → exit 2 input_not_found)
- `test_verify_jsonl_malformed_json_raises` (invalid JSON line → exit 2 schema_invalid)
- `test_verify_jsonl_top_level_not_object` (top-level array / string → exit 2 schema_invalid)
- `test_verify_missing_required_field_id` (id 不在 → exit 2 schema_invalid)
- `test_verify_missing_required_field_actor_id` (R1-F-006 adopt: actor_id 欠落 → exit 2、null は OK)
- `test_verify_extra_field_rejected` (R1-F-017 adopt: extra field 存在 → exit 2 schema_invalid)
- `test_verify_invalid_type_id_int` (id が int → exit 2 schema_invalid)
- `test_verify_invalid_type_tenant_id_str` (tenant_id が str → exit 2 schema_invalid)
- `test_verify_invalid_created_at_format` (ISO 8601 違反 → exit 2 schema_invalid)
- `test_verify_naive_datetime_rejected` (R1-F-010 adopt: timezone-aware 必須、naive → exit 2 schema_invalid)
- `test_verify_nan_in_event_payload_rejected` (R1-F-004 adopt: NaN reject → exit 2 non_finite_float)
- `test_verify_infinity_in_event_payload_rejected` (R1-F-004 adopt: Infinity reject)
- `test_verify_expected_hash_invalid_regex` (R1-F-007 adopt: uppercase / non-hex / 短文字列 → exit 2 expected_hash_invalid)
- `test_verify_expected_hash_mismatch_insertion` (R1-F-013 adopt: insertion tamper → exit 1 mismatch)
- `test_verify_expected_hash_mismatch_deletion` (R1-F-013 adopt: deletion → exit 1)
- `test_verify_expected_hash_mismatch_reorder` (R1-F-013 adopt: reorder → exit 1)
- `test_verify_max_entries_exceeded` (entries > max_entries → exit 2 input_too_large)
- `test_verify_max_line_bytes_exceeded` (R1-F-002 adopt: 1 line > max_line_bytes → exit 2 input_too_large)
- `test_verify_arg_out_of_range_max_entries` (R1-F-015 adopt: --max-entries=0 / 100001 / negative → exit 2 arg_out_of_range)

**Error message redaction (R1-F-005 adopt)**:
- `test_verify_error_message_no_raw_payload_leakage` (event_payload に secret-like string が含まれる malformed fixture で stderr に raw value が出ないこと verify、`line_no` + `field name` + `reason_code` のみが stderr に出る invariant)

### 5.4 `tests/scripts/test_taskhub_admin.py` 拡張 (CLI 経由 6 fixture 追加、R1-F-008 + R1-F-011 adopt)

- `test_cli_verify_signed_journal_requires_input` (`--signed-journal` 単独 → exit 2)
- `test_cli_verify_signed_journal_valid_jsonl_passes` (tmp jsonl with 3 events → exit 0、stdout contains final_hash)
- `test_cli_verify_signed_journal_tamper_detected` (`--expected-final-hash` 不一致 → exit 1)
- `test_cli_verify_signed_journal_mutually_exclusive_with_skeleton_flags` (R1-F-008 adopt: `--signed-journal --input` + `--integrity` 同時指定 → argparse exit 2、mutually exclusive group)
- `test_cli_verify_signed_journal_stdin_mode` (R1-F-011 adopt: `--input -` で stdin 渡し、file mode と同 final_hash assertion)
- `test_cli_verify_signed_journal_expected_hash_invalid_arg_exits_2` (R1-F-007 adopt: --expected-final-hash="INVALID" / "00" → exit 2 usage error)

### 5.5 既存 `_cmd_verify` skeleton flag との共存 (R1-F-008 + R2-F-002 adopt)

**R2-F-002 adopt 修正**: argparse `add_mutually_exclusive_group()` は既存テスト `test_cli_verify_both_flags_skeleton_mode_returns_exit_1` (`--integrity --network-invariant` 受容) を破壊する。よって argparse-level の mutual exclusivity ではなく、**`_cmd_verify` 内の parse-time validation** で `--signed-journal` を skeleton flags と排他化する:

```python
def _cmd_verify(args: argparse.Namespace) -> int:
    skeleton_flags_present = any([
        args.integrity, args.network_invariant, args.multi_agent,
    ])
    if args.signed_journal and skeleton_flags_present:
        print(  # noqa: T201
            "ERROR: --signed-journal は --integrity / --network-invariant / "
            "--multi-agent と併用不可 (real I/O mode と skeleton mode は排他)",
            file=sys.stderr,
        )
        return 2
    if args.signed_journal:
        # real I/O mode
        ...
    # existing skeleton path (--integrity / --network-invariant / --multi-agent の併用は維持)
```

- `--signed-journal` 単独 → real I/O mode (本 batch 1)
- 既存 skeleton flag (`--integrity` / `--network-invariant` / `--multi-agent`) は **複数併用可** (既存テスト `test_cli_verify_both_flags_skeleton_mode_returns_exit_1` 維持)
- `--signed-journal` + skeleton flag 1+ 同時指定 → exit 2 (parse-time validation で reject、新規 negative test で verify)

silent ignore は廃止 (R1-F-008 adopt: operator 誤解防止)。argparse-level mutually exclusive group は不使用 (R2-F-002 adopt: 既存 regression 維持)。

## 6. 検証手順

```bash
# 1. module syntax check
uv run python -m py_compile scripts/taskhub_signed_journal_offline.py

# 2. unit tests (新規)
uv run pytest tests/scripts/test_taskhub_signed_journal_offline.py -v
uv run pytest tests/scripts/test_taskhub_admin.py::test_cli_verify_signed_journal_valid_jsonl_passes -v

# 3. CLI smoke (positive)
cat <<'EOF' > /tmp/sample-audit.jsonl
{"id":"00000000-0000-0000-0000-000000000001","event_type":"approval_requested","tenant_id":1,"actor_id":"00000000-0000-0000-0000-000000000002","principal_id":null,"correlation_id":null,"trace_id":null,"event_payload":{"foo":"bar"},"created_at":"2026-05-20T00:00:00+00:00"}
EOF
uv run taskhub verify --signed-journal --input /tmp/sample-audit.jsonl
# expected: exit 0 + JSON {"mode":"signed-journal-offline","entry_count":1,"final_hash":"...","reason_code":"signed_journal_offline_verified"}

# 4. CLI smoke (tamper detection)
uv run taskhub verify --signed-journal --input /tmp/sample-audit.jsonl \
  --expected-final-hash "0000000000000000000000000000000000000000000000000000000000000000"
# expected: exit 1 + tamper_detected=true

# 5. regression: full backend + ruff + mypy
uv run pytest tests/ -q
uv run ruff check backend tests
uv run mypy backend
```

## 7. レビュー観点 (codex-plan-review trigger 必須)

mandatory Codex gate (`.claude/rules/codex-usage-policy.md §14.1`、CRITICAL invariant 直結 = signed journal hash chain tamper detection):
- `codex-plan-review R1-R3` minimum + 採否判定

### 7.1 期待される review focus

1. JSONL schema strict validation (R1 で予想される指摘: extra field reject / NFC normalization on string values / event_payload sub-field validation 不要性)
2. duck-typing safety (`AuditEventLike` dataclass で `_serialize_audit_event` が要求する全 attribute を持つか、ORM type hint との covariance)
3. DoS 防御 (`--max-entries` default 100k の妥当性 / stream read で memory exhaustion 回避)
4. stdin mode (`-`) と file mode の 両方で fully testable か
5. existing skeleton flag (`--integrity` / `--network-invariant` / `--multi-agent`) との共存ロジック (本 mode 優先 / co-existence 設計)
6. exit code 設計 (0 PASS / 1 tamper / 2 CLI error の境界)
7. `--expected-final-hash` 不在時の挙動 (computed `final_hash` を stdout 出力するだけで exit 0、verifier として弱くないか)
8. error message redaction (audit_event.event_payload に secret pattern 等が含まれる可能性、stderr に raw payload を出さない保証)
9. CRITICAL invariant 直結 (signed_journal.py の pure function pipeline と本 CLI wrapper の hash 一致性) の cross-platform deterministic 保証
10. import scope (本 module が backend.app.db を import しない invariant、軽量 startup)

## 8. リスク / Rollback

| リスク | 影響 | mitigation |
|---|---|---|
| `_serialize_audit_event` の duck-typing が将来 ORM-only attribute (例: relationship lazy load) を要求し始める | offline mode 破綻 | 本 batch 1 で attribute access list を明示 (id / event_type / tenant_id / actor_id / principal_id / correlation_id / trace_id / event_payload / created_at)、pure function 側 ChangeLog で attribute 追加が出たら同期判断 (batch 5 で再評価) |
| JSONL parse 中の memory exhaustion (大規模 audit log) | DoS | `--max-entries` 100k default + streaming read (本 plan §5.1 `_read_jsonl` で generator pattern) |
| Cross-platform hash 不一致 (Windows / macOS / Linux) | verifier 破綻 | signed_journal.py は RFC 8785 JCS canonical + NFC UTF-8 で deterministic、本 module は wrap のみ、reference vector test で確認 |
| event_payload 内の secret leakage (raw API key 等) が error message に出る | leak risk | error 出力は `line_no` + field name のみ、raw value は出さない (本 plan §5.1 で `'created_at' invalid ISO 8601: {exc}` の `exc` は Python の ValueError message で raw value 含まない) |
| `--input -` (stdin) の TTY interactive 経由で test fragility | flaky tests | subprocess fixture で `stdin=tmp_file.read_text()` を渡す pattern、direct call は stdin redirect で test |
| Codex review が delayed | merge 遅延 | 30 min max polling、admin merge bypass (CI billing failure 継続) |

### Rollback (3 階層、SP022-T01/T03/T04/T07/PR74/PR75 と同 pattern)

- Tier 1 (pre-merge local): `git restore` 対象 file
- Tier 2 (post-merge): `--signed-journal` flag 無視 (`_cmd_verify` の早期 return path を temporary disable)、revert 後 SP-022 `## Review` に rollback 記録
- Tier 3 (break-glass): PR revert + signed_journal pure function pipeline (PR #66) は不変 (本 batch 1 は CLI wrapper のみ、pure function 側 invariant に影響なし)

## 9. commit 戦略

single commit。SP022-T01/T03/T04/T07 PR74 PR75 pattern 踏襲。

## 10. PR workflow

SP022-T01〜T07 pattern 踏襲: plan draft → codex-plan-review R1-R3 → 実装 → pre-commit verify → commit/push/PR → Codex auto-review polling + multi-round adopt + admin merge bypass。

## 11. DoD

### 11.1 必須 DoD

- [ ] `scripts/taskhub_signed_journal_offline.py` 新規作成 (JSONL parser + AuditEventLike dataclass + verify_jsonl_signed_journal()、§5.1 構造)
- [ ] `scripts/taskhub_admin.py` `_cmd_verify` extension + 4 引数追加 (`--signed-journal` / `--input` / `--expected-final-hash` / `--max-entries`)
- [ ] `tests/scripts/test_taskhub_signed_journal_offline.py` 14 fixture 全 PASS (positive 5 + negative 9)
- [ ] `tests/scripts/test_taskhub_admin.py` 拡張 4 fixture 全 PASS (signed_journal CLI integration)
- [ ] CRITICAL invariant 直結: signed_journal.py pure function pipeline を不変で使用 (新規 hash logic を CLI 側で実装しない、本 batch 1 は wrapper のみ)
- [ ] import scope: `taskhub_signed_journal_offline.py` は `backend.app.db` を import しない (軽量 CLI startup 保証)
- [ ] `--expected-final-hash` 不一致時 exit 1 + tamper_detected=true
- [ ] regression: tests/deploy/ + tests/scripts/ + tests/citations/ + backend 全 PASS (3432+ pytest)、ruff backend tests clean、mypy strict 230+ file pass
- [ ] codex-plan-review R{N} findings are triaged adopt/defer/reject, and all adopted CRITICAL/HIGH are resolved before implementation
- [ ] **R1-F-001 adopt**: AuditEventLike contract (UUID hex string / int tenant_id / timezone-aware datetime / dict event_payload)、DB mirror fixture から reference final_hash を test に固定
- [ ] **R1-F-002 adopt**: `--max-line-bytes` 64KB default + 1KB-1MB range validation 実装、line-by-line stream read で memory exhaustion 回避
- [ ] **R1-F-003 adopt**: exit code 整理 (input layer ValueError → exit 2、explicit expected_hash mismatch → exit 1)、専用例外型 or result enum で `_cmd_verify` に区別を渡す
- [ ] **R1-F-004 adopt**: `json.loads(line, parse_constant=...)` で NaN/Infinity reject、`signed_journal_offline_jsonl_non_finite_float` reason_code 新規
- [ ] **R1-F-005 adopt**: error message redaction — parser/module 内で sanitized error 型、stderr は `reason_code` + `line_no` + `field` のみ、raw payload value は出さない invariant、secret-like fixture test で verify
- [ ] **R1-F-006 adopt**: actor_id / principal_id / correlation_id / trace_id は **required nullable** (欠落 → exit 2、null 明示は OK)
- [ ] **R1-F-007 adopt**: `--expected-final-hash` regex `^[0-9a-f]{64}$` validation、違反 → exit 2 (tamper でなく usage error)
- [ ] **R1-F-008 adopt**: argparse mutually exclusive group で `--signed-journal` と skeleton flags を排他
- [ ] **R1-F-009 adopt**: reference vector test (timezone offset / microseconds / NFD Unicode / nested key ordering 固定値)
- [ ] **R1-F-010 adopt**: timezone-aware datetime 必須、naive → exit 2 schema_invalid
- [ ] **R1-F-011 adopt**: stdin mode (`--input -`) CLI test を subprocess stdin 経由で追加、file mode と同 final_hash assertion
- [ ] **R1-F-012 adopt**: empty_chain は `warnings` array に、reason_code は exit 判定の主理由 (mismatch 時は mismatch を優先)
- [ ] **R1-F-013 adopt**: insertion / deletion / reorder negative test を 3 fixture として明記
- [ ] **R1-F-014 adopt**: `--expected-final-hash` 未指定時は `verification_performed=false` + reason_code `signed_journal_offline_hash_computed`
- [ ] **R1-F-015 adopt**: `--max-entries` 範囲 `[1, 100000]` validation、`--max-line-bytes` 範囲 `[1024, 1048576]` validation、違反 → exit 2 arg_out_of_range
- [ ] **R1-F-016 adopt**: strict structural schema、event_type domain enum validation なし旨を operational note に明記
- [ ] **R1-F-017 adopt**: extra fields reject (本 batch defensive、operator 誤解防止)
- [ ] **R2-F-001 adopt**: `signed_journal.py` の AuditEvent runtime import を許容 (Python module transitivity 不可避)、CLI が actual DB session 不要 invariant に scope を限定、Phase 2 で pure 抽出判断 (本 batch 1 carry-over)
- [ ] **R2-F-002 adopt**: argparse mutually exclusive group 不使用、`_cmd_verify` 内 parse-time validation で `--signed-journal` と skeleton flags の排他化、既存 `--integrity --network-invariant` test 維持

### 11.2 任意 DoD (回帰確認)

- [ ] PR Codex auto-review R{N} clean (採否判定 3 分類 + multi-round polish)
- [ ] SP-022 Pack `## Review` に SP022-T08 batch 1 完了記録

## 12. 関連

- `backend/app/services/audit/signed_journal.py` (Sprint 12 batch 10 PR #66 で完成、本 batch 1 が wrap する pure function pipeline)
- ADR-00021 §3 (taskhub admin CLI spec)、`taskhub verify` subcommand の上位 spec
- SP-022 line 68 (SP022-T08 SP-012 carry-over 9 件、本 batch 1 = signed journal CLI part)
- SP-012 §128 (host migration drill command)、SP022-T09 実機 drill で本 CLI を使用
- `.claude/reference/task-planning-matrix.md` §2 (T08 = 🟥 heavy + batch 分割必須、本 batch 1 が batch 1)
- SP022-T01 PR #70 / T03 PR #71 / T04 PR #72 / T07 PR #73 / planning matrix PR #74 / T02 Phase 1 PR #75 (確立 pattern)
- Sprint 12 batch 7 `scripts/taskhub_admin.py` (本 batch 1 が integrate する skeleton)

## 13. R1+R2 plan-review findings adoption log

R1 (2026-05-20, codex-plan-review): 17 findings, **全件 adopt** (HIGH×5 / MEDIUM×9 / LOW×3).
R2 (2026-05-20, codex-plan-review Phase B): 2 HIGH findings, **全件 adopt** (architecture / compatibility)。

| ID | severity | category | summary | adopted location |
|---|---|---|---|---|
| F-001 | HIGH | inconsistency | AuditEventLike contract (UUID hex / int tenant_id / timezone-aware datetime)、DB mirror reference hash test | §4.4, §5.3 (reference_vector test), §11.1 DoD |
| F-002 | HIGH | risk | DoS 防御強化: `--max-line-bytes` 64KB default + range、stream read で全件積み不可避ならメモリ見積もり明示 | §4.1, §4.5, §11.1 DoD |
| F-003 | HIGH | inconsistency | exit code 整理 (input ValueError → exit 2、explicit hash mismatch → exit 1)、専用例外型 | §4.3 (exit code 整理), §4.5 reason_codes, §11.1 DoD |
| F-004 | HIGH | missing | NaN/Infinity reject (json.loads parse_constant)、`non_finite_float` reason_code | §4.4, §4.5, §5.3 negative test, §11.1 DoD |
| F-005 | HIGH | risk | error message redaction (sanitized error 型、raw payload value leak 防止) | §5.3 (error message redaction test), §11.1 DoD |
| F-006 | MEDIUM | missing | actor_id/principal_id/correlation_id/trace_id required nullable | §4.4, §5.3 negative test, §11.1 DoD |
| F-007 | MEDIUM | ambiguity | --expected-final-hash regex `^[0-9a-f]{64}$` validation、違反 → exit 2 usage error | §4.1, §4.5, §5.3 negative test, §5.4 CLI test, §11.1 DoD |
| F-008 | MEDIUM | ambiguity | --signed-journal と skeleton flags を argparse mutually exclusive group で排他 | §4.1, §5.5, §11.1 DoD |
| F-009 | MEDIUM | missing | reference vector を timezone offset / microseconds / NFD / nested key ordering で固定 | §4.4, §5.3 reference test, §11.1 DoD |
| F-010 | MEDIUM | risk | timezone-aware datetime 必須、naive → exit 2 | §4.4, §5.3 negative test, §11.1 DoD |
| F-011 | MEDIUM | missing | stdin mode CLI test を subprocess 経由で追加 | §5.4 CLI test, §11.1 DoD |
| F-012 | MEDIUM | ambiguity | empty_chain は warnings array、reason_code は mismatch を優先 | §4.2 output schema, §4.5, §11.1 DoD |
| F-013 | MEDIUM | missing | insertion / deletion / reorder negative test 3 fixture 明記 | §5.3 negative tests, §11.1 DoD |
| F-014 | MEDIUM | risk | --expected-final-hash 未指定時は verification_performed=false + signed_journal_offline_hash_computed reason | §4.2, §4.5, §5.3 positive test, §11.1 DoD |
| F-015 | LOW | missing | --max-entries / --max-line-bytes 範囲 validation | §4.1, §4.5, §5.3 negative test, §11.1 DoD |
| F-016 | LOW | ambiguity | strict structural schema, no domain enum validation 明記 | §4.4, §11.1 DoD |
| F-017 | LOW | missing | extra fields reject (本 batch defensive) | §4.4, §5.3 negative test, §11.1 DoD |
| R2-F-001 | HIGH | architecture | DB-free import 不可 (signed_journal.py + audit/__init__ が AuditEvent / AuditExporter を eager import)、CLI scope は "actual DB session 不要" に限定、Phase 2 で pure 抽出判断 | §1 #4, §11.1 DoD |
| R2-F-002 | HIGH | compatibility | argparse mutually exclusive group は既存 `--integrity --network-invariant` test 破壊、`_cmd_verify` 内 parse-time validation で排他化 | §5.5, §11.1 DoD |
