"use client";

import { useEffect, useRef, useState } from "react";

import { AgentRunStatusIndicator } from "@/components/agent-run-status-indicator-v2";
import {
  subscribeAgentRunStream,
  type SseEvent,
  type SseStreamState,
} from "@/lib/realtime/agent-run-sse";

// ADR-00038 (L-3 realtime): run 詳細の status + イベントタイムラインを SSE で live 更新する
// Client Component。SSR が seed した初期データから開始し、fetch-based SSE client で resume/
// reconnect/204停止を app 制御する。flag-off は proxy の 204 → client closed で storm を防ぐ。

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
  runId: string;
  initialStatus: string;
  initialBlockedReason: string | null;
  initialEvents: TimelineEvent[];
};

export function RunLiveTimeline({
  runId,
  initialStatus,
  initialBlockedReason,
  initialEvents,
}: Props) {
  const [status, setStatus] = useState(initialStatus);
  const [blockedReason, setBlockedReason] = useState(initialBlockedReason);
  const [events, setEvents] = useState<TimelineEvent[]>(initialEvents);
  const [connState, setConnState] = useState<SseStreamState>("connecting");
  const seenSeq = useRef<Set<number>>(new Set(initialEvents.map((event) => event.seq_no)));

  useEffect(() => {
    const initialLastEventId = initialEvents.reduce((max, event) => Math.max(max, event.seq_no), 0);
    const cleanup = subscribeAgentRunStream(runId, {
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
      },
      onState: setConnState,
    });
    return cleanup;
    // runId 固定。initialEvents/initialLastEventId は mount 時のみ参照 (SSR seed)。
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId]);

  const isTerminal = TERMINAL_STATUSES.has(status);

  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <div className="flex items-center justify-between gap-2">
        <h2 className="text-lg font-semibold">イベントタイムライン</h2>
        <div className="flex items-center gap-2">
          <AgentRunStatusIndicator status={status} blockedReason={blockedReason} />
          {!isTerminal ? <span
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
            </span> : null}
        </div>
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
                {index < events.length - 1 ? <div className="absolute top-3 h-full w-0.5 bg-line" /> : null}
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
                {event.payload_keys.length > 0 ? <p className="mt-0.5 text-xs text-muted-foreground">
                    keys: {event.payload_keys.join(", ")}
                  </p> : null}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <p className="mt-4 text-sm text-muted-foreground">イベントはまだ記録されていません</p>
      )}
    </article>
  );
}
