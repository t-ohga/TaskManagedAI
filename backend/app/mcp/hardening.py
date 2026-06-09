"""SP-034 (ADR-00026): MCP ingress hardening — mutation rate limit, max concurrent,
max tool-input bytes, and the read/mutate tool partition.

This module closes the SP-034 acceptance criteria:
- per-actor rate limit + max concurrent (ingress guard, BudgetGuard を補完する軽量 in-process gate)
- stdio hardening: max request bytes (per tool-call input、env allowlist は ``subprocess_env`` 側)

Design invariants:
- **input-size cap は transport-wide** (read + mutate 全 tool、Codex R2 F-3)。rate-limit と
  max-concurrent は **mutating tool のみ** (read tool の rate は無制限、dev workflow を阻害しない)。
- **actor-keyed forward-compat**: 現状 MCP は固定 default actor で動くため key は default actor。
  SP-016 で per-actor 認証が wired されると自動的に per-actor enforcement になる
  (idempotency table と同じ forward-compat 方針)。
- **scope = per-process DoS 緩和** (Codex R2 F-2): rate/concurrency state は module-global で
  **当該 server process 内に閉じる**。stdio deployment では client ごとに別 server process が
  spawn され得るため、本 guard は「単一 process 内の runaway loop / write storm を抑える DoS
  緩和」であり **cross-process な global per-actor quota ではない**。cross-process enforcement は
  共有 counter backend (Redis / PostgreSQL advisory lock) が必要で、per-actor 認証 (SP-016) +
  multi-agent orchestration (P0.1) と結合するため、そこで shared-backend 化する (現状は固定単一
  actor のため cross-process 共有の実益も限定的)。
- **fail-open**: guard 自身の内部エラーでは call を通す (可用性優先、security boundary は別 layer)。
- **generous env-tunable 既定値**: 単一ユーザー P0 の通常利用で発火しない閾値。
- raw secret / 引数値を error / log に含めない (tool 名と reason_code と件数のみ)。
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import deque
from typing import Any

from backend.app.repositories._payload_secret_scan import _PROHIBITED_PAYLOAD_KEYS

logger = logging.getLogger(__name__)

# --- Tool read/mutate partition (5+ source integrity: drift-guard test で全 39 と一致確認) ---

#: 状態変更を伴う mutating tool (ingress guard 対象)。
MUTATION_TOOLS: frozenset[str] = frozenset(
    {
        "ticket_create",
        "ticket_update",
        "ticket_comment",
        "ticket_link",
        "run_create",
        "run_cancel",
        "run_update",
        # run_cost は read 風の名前だが bridge_run_cost が AgentRun.cost_usd / tokens_* を
        # 書き込み commit する mutating path (Codex adversarial R1 HIGH、KPI 汚染防止)。
        "run_cost",
        "approval_request_create",
        "delegation_create",
        "delegation_accept",
        "delegation_submit",
        "delegation_review",
        "delegation_cancel",
        "superintendent_agent_register",
        "superintendent_agent_start",
        "superintendent_agent_stop",
        "superintendent_dispatch",
        "notification_resolve",
    }
)

#: read-only tool (guard 対象外、無制限)。
READ_TOOLS: frozenset[str] = frozenset(
    {
        "ticket_list",
        "ticket_show",
        "ticket_list_all",
        "ticket_search",
        "run_show",
        "run_list",
        "run_plan_dry_run",
        "approval_list",
        "approval_show",
        "audit_list",
        "context_show",
        "context_auto",
        "kpi_show",
        "notification_list",
        "project_list",
        "workflow_status",
        "delegation_inbox",
        "delegation_tree",
        "superintendent_agent_list",
        "superintendent_delegation_show",
    }
)

#: caller が指定してはならない server-owned identity / 制御 field。
_SERVER_OWNED_IDENTITY_FIELDS: frozenset[str] = frozenset(
    {
        "actor_id",
        "principal_id",
        "tenant_id",
        "policy_profile",
        "autonomy_level",
        "capability_token",
        "approval_request_id",
        "decided_by_actor_id",
        "provider_payload",
    }
)

#: caller が指定してはならない field の正本 (gap #3)。server-owned identity に加え、repo の canonical
#: prohibited secret key set (`_PROHIBITED_PAYLOAD_KEYS`、api_key / secret_capability_token / raw_token /
#: session_token 等の alias を含む) を union する (Codex R12 F-18、drift 回避のため canonical set を再利用)。
#: middleware はこの set に一致する top-level arg key を FastMCP validation 前に拒否し、raw value の
#: ログ / 例外 / payload 露出を防ぐ。
SERVER_OWNED_FORBIDDEN_FIELDS: frozenset[str] = (
    _SERVER_OWNED_IDENTITY_FIELDS | _PROHIBITED_PAYLOAD_KEYS
)


def _int_env(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        logger.warning("invalid int env %s=%r; using default %d", name, raw, default)
        return default
    return value if value > 0 else default


# --- Ingress limits (env-tunable、generous 既定値) ---

#: rate-limit window 内に許可する mutating call 数 (per actor)。
MUTATION_RATE_LIMIT: int = _int_env("TASKMANAGEDAI_MCP_MUTATION_RATE_LIMIT", 240)
#: rate-limit window 秒。
MUTATION_RATE_WINDOW_SEC: int = _int_env("TASKMANAGEDAI_MCP_MUTATION_RATE_WINDOW_SEC", 60)
#: 同時に in-flight な mutating call の上限 (per actor)。
MAX_CONCURRENT_MUTATIONS: int = _int_env("TASKMANAGEDAI_MCP_MAX_CONCURRENT_MUTATIONS", 32)
#: 1 tool-call の input 引数の合計 byte 上限。
#: Codex R3 F-4: これは FastMCP が JSON-RPC frame を deserialize した **後** の引数サイズ上限
#: (post-parse argument cap、defense-in-depth) であり、raw stdio frame の transport-level size
#: limit ではない。local trusted stdio (MCP client = user 自身の Claude Code/Codex、network 露出なし)
#: では transport-frame DoS は低優先で、FastMCP も transport size 設定を露出しない。真の frame-size
#: 制限は transport layer patch が必要で follow-up (P0 では本 post-parse cap で defense-in-depth)。
MAX_TOOL_INPUT_BYTES: int = _int_env("TASKMANAGEDAI_MCP_MAX_TOOL_INPUT_BYTES", 262144)

#: 現状の固定 actor key (forward-compat、SP-016 で認証 actor へ差し替わる)。
DEFAULT_ACTOR_KEY = "00000000-0000-4000-8000-000000000001"


class _AdmissionState:
    """in-process な sliding-window + concurrency 状態 (single asyncio process)。"""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._windows: dict[str, deque[float]] = {}
        self._inflight: dict[str, int] = {}

    def reset(self) -> None:
        with self._lock:
            self._windows.clear()
            self._inflight.clear()

    def admit(self, actor_key: str, now: float) -> str | None:
        """mutating call を受理してよいか判定。

        受理時は rate-window へ now を記録し inflight を +1 して ``None`` を返す。
        拒否時は状態を変えず reason_code を返す。
        """
        window = MUTATION_RATE_WINDOW_SEC
        rate_limit = MUTATION_RATE_LIMIT
        max_concurrent = MAX_CONCURRENT_MUTATIONS
        with self._lock:
            stamps = self._windows.setdefault(actor_key, deque())
            cutoff = now - window
            while stamps and stamps[0] <= cutoff:
                stamps.popleft()
            if len(stamps) >= rate_limit:
                return "rate_limited"
            if self._inflight.get(actor_key, 0) >= max_concurrent:
                return "too_many_concurrent"
            stamps.append(now)
            self._inflight[actor_key] = self._inflight.get(actor_key, 0) + 1
            return None

    def release(self, actor_key: str) -> None:
        with self._lock:
            current = self._inflight.get(actor_key, 0)
            if current <= 1:
                self._inflight.pop(actor_key, None)
            else:
                self._inflight[actor_key] = current - 1


_state = _AdmissionState()


def reset_admission_state() -> None:
    """test 用: ingress guard の in-process 状態をリセットする。"""
    _state.reset()


def estimate_input_bytes(arguments: dict[str, Any] | None) -> int:
    """tool-call の input 引数を UTF-8 byte 数で概算する (max request bytes 判定用)。

    Codex R16 F-24: **bounded iterative** (`str(deeply_nested)` の `RecursionError` を回避)。node 数が
    上限超なら ``MAX_TOOL_INPUT_BYTES + 1`` を返し too_large として reject する (異常に深い payload の
    fail-closed)。
    """
    if not arguments:
        return 0
    total = 0
    stack: list[object] = [arguments]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > _MAX_SECRET_SCAN_NODES:
            return MAX_TOOL_INPUT_BYTES + 1
        if isinstance(node, dict):
            for key, value in node.items():
                total += len(str(key).encode("utf-8"))
                stack.append(value)
        elif isinstance(node, list):
            stack.extend(node)
        else:
            total += len(str(node).encode("utf-8"))
    return total


#: secret scan が訪問する node 数の上限。超過 (= 異常に深い / 大きい payload) は fail-closed で
#: secret 扱いにする (Codex R16 F-24: 完全に scan できない構造を「安全」とみなさない)。
_MAX_SECRET_SCAN_NODES = 10000


def arguments_contain_secret(arguments: dict[str, Any] | None) -> bool:
    """tool-call 引数の key / string 値に secret-shaped pattern があるか (Codex R15 F-23 / R16 F-24)。

    forbidden field 名でない **unknown** top-level 引数の値 (`unexpected="sk-proj-..."`) や secret-shaped
    な **key** (`{"sk-proj-...": x}`) は FastMCP/Pydantic の additionalProperties rejection で raw value が
    ValidationError / WARNING ログへ露出する。FastMCP validation 到達前に broad scanner で検出し、middleware
    が **generic** error (field 名 / 値なし) で reject するための判定。

    Codex R16 F-24: **bounded iterative** (再帰せず明示 stack、`RecursionError` で fail-open する経路を排除)。
    node 数が ``_MAX_SECRET_SCAN_NODES`` を超える深い / 巨大 payload は完全 scan できないため
    **fail-closed** で True (secret 疑い) を返す。遅延 import (層分離 / 循環回避)。
    """
    from backend.app.services.security.secret_text_scan import assert_no_secret_in_text

    stack: list[object] = [arguments or {}]
    visited = 0
    while stack:
        node = stack.pop()
        visited += 1
        if visited > _MAX_SECRET_SCAN_NODES:
            return True  # 完全に scan できない構造は suspicious 扱い (fail-closed)。
        if isinstance(node, dict):
            for key, sub in node.items():
                key_str = str(key)
                # Codex R17 F-25: prohibited key 名 (capability_token / api_key 等) を **全 depth** で
                # 検出する。broad pattern (短い test token 等) に該当しない値でも nested prohibited key
                # は FastMCP validation で key+value を露出するため、key 名照合で先に止める。
                if key_str.lower() in SERVER_OWNED_FORBIDDEN_FIELDS:
                    return True
                try:
                    assert_no_secret_in_text(key_str, field="key")
                except ValueError:
                    return True
                stack.append(sub)
        elif isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, str):
            try:
                assert_no_secret_in_text(node, field="value")
            except ValueError:
                return True
    return False


def admission_error(
    reason_code: str, tool_name: str, fields: list[str] | None = None
) -> dict[str, Any]:
    """ingress 拒否時の structured error (raw 引数値を含めない)。

    Codex R7 F-11: 正本 key は ``error_code`` (MCP error semantics)。middleware はこの payload を
    ``ToolError`` 経由で返し、MCP client には ``isError: true`` として届く。
    Codex R11 F-16: ``caller_supplied_field_rejected`` では拒否した server-owned field の **名前のみ**
    (``fields``) を返し、raw value は一切含めない。
    """
    payload: dict[str, Any] = {
        "error_code": reason_code,
        "tool": tool_name,
        "blocked_by": "mcp_ingress_guard",
    }
    if reason_code == "rate_limited":
        payload["retry_after_seconds"] = MUTATION_RATE_WINDOW_SEC
        payload["limit"] = MUTATION_RATE_LIMIT
        payload["window_seconds"] = MUTATION_RATE_WINDOW_SEC
    elif reason_code == "too_many_concurrent":
        payload["max_concurrent"] = MAX_CONCURRENT_MUTATIONS
    elif reason_code == "input_too_large":
        payload["max_input_bytes"] = MAX_TOOL_INPUT_BYTES
    elif reason_code == "caller_supplied_field_rejected" and fields:
        # field 名のみ (raw value は禁止、secret 漏洩防止)。
        payload["fields"] = list(fields)
    return payload


def input_size_exceeded(input_bytes: int) -> bool:
    """tool-call の post-parse 引数サイズが上限を超えるか (read/mutate 共通の defense-in-depth)。

    Codex adversarial R2 F-3: 引数サイズ cap は read tool も含む全 tool call に適用する
    (oversized read 引数で memory/CPU/DB-heavy path に誘導されるのを防ぐ)。
    Codex R3 F-4: これは transport frame-size limit ではなく post-parse argument cap (上記 const 参照)。
    """
    return input_bytes > MAX_TOOL_INPUT_BYTES


def check_admission(actor_key: str, now: float | None = None) -> str | None:
    """mutating tool の rate-limit + concurrency admission を判定する。

    受理時は inflight を +1 する。呼び出し側は受理時に必ず ``release_admission`` を呼ぶこと。
    input-size は :func:`input_size_exceeded` で別途 (transport-wide) に判定する。
    """
    moment = time.monotonic() if now is None else now
    return _state.admit(actor_key, moment)


def release_admission(actor_key: str) -> None:
    _state.release(actor_key)
