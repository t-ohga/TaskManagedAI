"use client";

import { useEffect, useRef, useState } from "react";

import { AgentRunStatusIndicator } from "@/components/agent-run-status-indicator-v2";
import { RoleBadge } from "@/components/role-badge";
import { Breadcrumb } from "@/components/breadcrumb";
import { RunCancelButton } from "@/components/run-cancel-button";
import {
  subscribeAgentRunStream,
  type SseEvent,
  type SseStreamState,
} from "@/lib/realtime/agent-run-sse";

// ADR-00038 (L-3 realtime): run 詳細全体を SSE で live 更新する Client Component。
// live status を **1 箇所で所有** し、header / basic-info の status indicator + cancel button +
// timeline をすべて live status で render する (Codex PR #301 P2-3: status が timeline 内のみだと
// header/cancel が server 値のまま stale になる不整合を解消)。SSR が初期データを seed する。
// flag-off は proxy の 204 → client closed で reconnect storm を防ぐ。

export type RunDetailSeed = {
  id: string;
  status: string;
  blocked_reason: string | null;
  role_id: string | null;
  parent_run_id: string | null;
  error_code: string | null;
  cost_usd: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  created_at: string | null;
  completed_at: string | null;
};

export type TimelineEvent = {
  id: string;
  event_type: string;
  seq_no: number;
  payload_keys: string[];
  created_at: string | null;
};

const EVENT_LABELS: Record<string, string> = {
  run_queued: "実行キュー追加",
  context_gathered: "コンテキスト収集",
  provider_requested: "プロバイダー呼出",
  provider_responded: "プロバイダー応答",
  artifact_generated: "成果物生成",
  schema_validated: "スキーマ検証",
  validation_failed: "検証失敗",
  policy_linted: "ポリシーチェック",
  policy_blocked: "ポリシー拒否",
  budget_blocked: "予算超過",
  runtime_blocked: "ランタイム拒否",
  diff_ready: "差分準備完了",
  approval_requested: "承認要求",
  approval_decided: "承認決定",
  runner_started: "ランナー起動",
  runner_completed: "ランナー完了",
  runner_blocked: "ランナー拒否",
  repo_pr_opened: "PR 作成",
  run_completed: "実行完了",
  run_failed: "実行失敗",
  run_cancelled: "実行キャンセル",
};

const TERMINAL_STATUSES = new Set([
  "completed",
  "failed",
  "cancelled",
  "provider_refused",
  "repair_exhausted",
]);

const CONNECTION_LABELS: Record<SseStreamState, string> = {
  connecting: "接続中",
  open: "ライブ更新中",
  reconnecting: "再接続中",
  closed: "更新停止",
  error: "接続エラー",
};

type Props = {
  run: RunDetailSeed;
  initialEvents: TimelineEvent[];
};

export function RunDetailLive({ run, initialEvents }: Props) {
  const [status, setStatus] = useState(run.status);
  const [blockedReason, setBlockedReason] = useState(run.blocked_reason);
  const [completedAt, setCompletedAt] = useState(run.completed_at);
  const [errorCode, setErrorCode] = useState(run.error_code);
  const [events, setEvents] = useState<TimelineEvent[]>(initialEvents);
  const [connState, setConnState] = useState<SseStreamState>("connecting");
  const seenSeq = useRef<Set<number>>(new Set(initialEvents.map((event) => event.seq_no)));

  useEffect(() => {
    const initialLastEventId = initialEvents.reduce((max, event) => Math.max(max, event.seq_no), 0);
    const cleanup = subscribeAgentRunStream(run.id, {
      initialLastEventId,
      onEvent: (event: SseEvent) => {
        if (seenSeq.current.has(event.seq_no)) return;
        seenSeq.current.add(event.seq_no);
        setEvents((prev) =>
          [
            ...prev,
            {
              id: event.event_id,
              event_type: event.event_type,
              seq_no: event.seq_no,
              payload_keys: event.payload_keys,
              created_at: event.created_at,
            },
          ].sort((a, b) => a.seq_no - b.seq_no)
        );
      },
      onStatus: (next) => {
        setStatus(next.status);
        setBlockedReason(next.blocked_reason);
        setCompletedAt(next.completed_at);
        setErrorCode(next.error_code);
      },
      onState: setConnState,
    });
    return cleanup;
    // run.id 固定。SSR seed (initialEvents) は mount 時のみ参照。run.id 変更は page 側の key で remount。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [run.id]);

  const isTerminal = TERMINAL_STATUSES.has(status);

  return (
    <section aria-label="AI 実行詳細" className="grid gap-6">
      <header className="grid gap-2">
        <Breadcrumb
          items={[
            { label: "ダッシュボード", href: "/dashboard" },
            { label: "AI 実行", href: "/runs" },
            { label: run.id.slice(0, 8) + "..." },
          ]}
        />
        <div className="flex items-center gap-4">
          <h1 className="text-3xl font-semibold tracking-normal">AI 実行詳細</h1>
          <AgentRunStatusIndicator status={status} blockedReason={blockedReason} />
          <RoleBadge role={run.role_id} />
        </div>
      </header>

      <div className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">基本情報</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">実行 ID</dt>
              <dd className="font-mono text-xs">{run.id.slice(0, 12)}...</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">ステータス</dt>
              <dd>
                <AgentRunStatusIndicator status={status} blockedReason={blockedReason} />
              </dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">役割</dt>
              <dd>
                <RoleBadge role={run.role_id} />
              </dd>
            </div>
            {run.parent_run_id ? (
              <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">親実行</dt>
                <dd>
                  <a
                    href={`/runs/${run.parent_run_id}`}
                    className="font-mono text-xs text-accent hover:underline"
                  >
                    {run.parent_run_id.slice(0, 8)}...
                  </a>
                </dd>
              </div>
            ) : null}
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">作成日時</dt>
              <dd>{run.created_at ? new Date(run.created_at).toLocaleString("ja-JP") : "—"}</dd>
            </div>
            {completedAt ? (
              <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">完了日時</dt>
                <dd>{new Date(completedAt).toLocaleString("ja-JP")}</dd>
              </div>
            ) : null}
          </dl>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">コスト・トークン</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">コスト</dt>
              <dd>
                {run.cost_usd != null && run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : "未計測"}
              </dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">入力トークン</dt>
              <dd>{run.tokens_input?.toLocaleString() ?? "未計測"}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">出力トークン</dt>
              <dd>{run.tokens_output?.toLocaleString() ?? "未計測"}</dd>
            </div>
            {errorCode ? (
              <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">エラーコード</dt>
                <dd className="font-mono text-xs text-red-600">{errorCode}</dd>
              </div>
            ) : null}
          </dl>
        </article>
      </div>

      {!isTerminal ? <RunCancelButton runId={run.id} /> : null}

      <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
        <div className="flex items-center justify-between gap-2">
          <h2 className="text-lg font-semibold">イベントタイムライン</h2>
          {!isTerminal ? (
            <span
              className="flex items-center gap-1 text-[10px] text-muted-foreground"
              aria-live="polite"
            >
              <span
                className={
                  connState === "open"
                    ? "h-2 w-2 rounded-full bg-green-500"
                    : connState === "error"
                      ? "h-2 w-2 rounded-full bg-red-500"
                      : "h-2 w-2 rounded-full bg-amber-400"
                }
                aria-hidden="true"
              />
              {CONNECTION_LABELS[connState]}
            </span>
          ) : null}
        </div>
        <p className="mt-1 text-xs text-muted-foreground">
          追記専用。シークレットは表示されません。
        </p>
        {events.length > 0 ? (
          <div className="mt-4 space-y-3">
            {events.map((event, index) => (
              <div key={event.id} className="flex items-start gap-3">
                <div className="relative flex flex-col items-center">
                  <div className="h-3 w-3 rounded-full border-2 border-accent bg-panel" />
                  {index < events.length - 1 ? (
                    <div className="absolute top-3 h-full w-0.5 bg-line" />
                  ) : null}
                </div>
                <div className="flex-1 pb-3">
                  <div className="flex items-center gap-2">
                    <span className="text-sm font-medium">
                      {EVENT_LABELS[event.event_type] ?? event.event_type}
                    </span>
                    <span className="text-[10px] text-muted-foreground">
                      {event.created_at ? new Date(event.created_at).toLocaleString("ja-JP") : ""}
                    </span>
                  </div>
                  {event.payload_keys.length > 0 ? (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      keys: {event.payload_keys.join(", ")}
                    </p>
                  ) : null}
                </div>
              </div>
            ))}
          </div>
        ) : (
          <p className="mt-4 text-sm text-muted-foreground">イベントはまだ記録されていません</p>
        )}
      </article>
    </section>
  );
}
