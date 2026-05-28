import { notFound } from "next/navigation";

import { fetchBackendRaw } from "@/lib/api/client";
import { RunCancelButton } from "@/components/run-cancel-button";
import { AgentRunStatusIndicator } from "@/components/agent-run-status-indicator-v2";
import { RoleBadge } from "@/components/role-badge";

export const dynamic = "force-dynamic";

type RunDetail = {
  id: string;
  status: string;
  blocked_reason: string | null;
  role_id: string | null;
  parent_run_id: string | null;
  project_id: string;
  error_code: string | null;
  error_summary: string | null;
  cost_usd: number | null;
  tokens_input: number | null;
  tokens_output: number | null;
  created_at: string | null;
  completed_at: string | null;
};

type RunEvent = {
  id: string;
  event_type: string;
  actor_id: string | null;
  payload_keys: string[];
  created_at: string | null;
};

async function loadRun(id: string): Promise<{ run: RunDetail; events: RunEvent[] } | null> {
  try {
    const res = await fetchBackendRaw(`/api/v1/agent_runs/${id}` as `/${string}`);
    const raw = res as Record<string, unknown>;
    return {
      run: raw as unknown as RunDetail,
      events: ((raw?.events ?? []) as RunEvent[]),
    };
  } catch {
    return null;
  }
}

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

const EVENTS_PER_PAGE = 20;

type Props = {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ epage?: string }>;
};

export default async function RunDetailPage({ params, searchParams }: Props) {
  const { id } = await params;
  const sp = await searchParams;
  const parsedEpage = Number(sp.epage ?? "1");
  const eventPage = Number.isFinite(parsedEpage) && parsedEpage >= 1 ? Math.floor(parsedEpage) : 1;
  const data = await loadRun(id);

  if (!data) {
    notFound();
  }

  const { run, events } = data;

  return (
    <section aria-label="AI 実行詳細" className="grid gap-6">
      <header className="grid gap-2">
        <div className="flex items-center gap-2 text-sm">
          <a href="/runs" className="text-accent hover:underline">AI 実行一覧</a>
          <span className="text-muted-foreground">/</span>
          <span className="font-mono text-xs text-muted-foreground">{id.slice(0, 8)}...</span>
        </div>
        <div className="flex items-center gap-4">
          <h1 className="text-3xl font-semibold tracking-normal">AI 実行詳細</h1>
          <AgentRunStatusIndicator status={run.status} blockedReason={run.blocked_reason} />
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
              <dd><AgentRunStatusIndicator status={run.status} blockedReason={run.blocked_reason} /></dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">役割</dt>
              <dd><RoleBadge role={run.role_id} /></dd>
            </div>
            {run.parent_run_id && (
              <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">親実行</dt>
                <dd><a href={`/runs/${run.parent_run_id}`} className="font-mono text-xs text-accent hover:underline">{run.parent_run_id.slice(0, 8)}...</a></dd>
              </div>
            )}
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">作成日時</dt>
              <dd>{run.created_at ? new Date(run.created_at).toLocaleString("ja-JP") : "—"}</dd>
            </div>
            {run.completed_at && (
              <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">完了日時</dt>
                <dd>{new Date(run.completed_at).toLocaleString("ja-JP")}</dd>
              </div>
            )}
          </dl>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-lg font-semibold">コスト・トークン</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">コスト</dt>
              <dd>{run.cost_usd != null && run.cost_usd > 0 ? `$${run.cost_usd.toFixed(4)}` : "未計測"}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">入力トークン</dt>
              <dd>{run.tokens_input?.toLocaleString() ?? "未計測"}</dd>
            </div>
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">出力トークン</dt>
              <dd>{run.tokens_output?.toLocaleString() ?? "未計測"}</dd>
            </div>
            {run.error_code && (
              <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">エラーコード</dt>
                <dd className="font-mono text-xs text-red-600">{run.error_code}</dd>
              </div>
            )}
          </dl>
        </article>
      </div>

      {!["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"].includes(run.status) && (
        <RunCancelButton runId={run.id} />
      )}

      <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
        <h2 className="text-lg font-semibold">イベントタイムライン</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          追記専用。シークレットは表示されません。
        </p>
        {events.length > 0 ? (() => {
          const totalEventPages = Math.max(1, Math.ceil(events.length / EVENTS_PER_PAGE));
          const paginatedEvents = events.slice((eventPage - 1) * EVENTS_PER_PAGE, eventPage * EVENTS_PER_PAGE);
          return (
          <>
          <div className="mt-4 space-y-3">
            {paginatedEvents.map((event, i) => (
              <div key={event.id} className="flex items-start gap-3">
                <div className="relative flex flex-col items-center">
                  <div className="h-3 w-3 rounded-full border-2 border-accent bg-panel" />
                  {i < events.length - 1 && (
                    <div className="absolute top-3 h-full w-0.5 bg-line" />
                  )}
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
                  {event.payload_keys?.length > 0 && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      keys: {event.payload_keys.join(", ")}
                    </p>
                  )}
                </div>
              </div>
            ))}
          </div>
          {totalEventPages > 1 && (
            <nav aria-label="イベントページネーション" className="mt-4 flex items-center justify-center gap-2">
              {eventPage > 1 && (
                <a href={`/runs/${id}?epage=${eventPage - 1}`} className="rounded border border-line px-3 py-1 text-sm hover:bg-slate-50">前へ</a>
              )}
              <span className="text-sm text-muted-foreground">{eventPage} / {totalEventPages}</span>
              {eventPage < totalEventPages && (
                <a href={`/runs/${id}?epage=${eventPage + 1}`} className="rounded border border-line px-3 py-1 text-sm hover:bg-slate-50">次へ</a>
              )}
            </nav>
          )}
          </>
          );
        })() : (
          <p className="mt-4 text-sm text-muted-foreground">イベントはまだ記録されていません</p>
        )}
      </article>
    </section>
  );
}
