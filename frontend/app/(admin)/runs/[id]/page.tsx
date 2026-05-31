import { notFound } from "next/navigation";

import { fetchBackendRaw } from "@/lib/api/client";
import { RunCancelButton } from "@/components/run-cancel-button";
import { AgentRunStatusIndicator } from "@/components/agent-run-status-indicator-v2";
import { RoleBadge } from "@/components/role-badge";
import { Breadcrumb } from "@/components/breadcrumb";
import { RunLiveTimeline } from "./run-live-timeline";

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
  seq_no: number;
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

type Props = {
  params: Promise<{ id: string }>;
};

export default async function RunDetailPage({ params }: Props) {
  const { id } = await params;
  const data = await loadRun(id);

  if (!data) {
    notFound();
  }

  const { run, events } = data;

  return (
    <section aria-label="AI 実行詳細" className="grid gap-6">
      <header className="grid gap-2">
        <Breadcrumb items={[
          { label: "ダッシュボード", href: "/dashboard" },
          { label: "AI 実行", href: "/runs" },
          { label: id.slice(0, 8) + "..." },
        ]} />
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
            {run.parent_run_id ? <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">親実行</dt>
                <dd><a href={`/runs/${run.parent_run_id}`} className="font-mono text-xs text-accent hover:underline">{run.parent_run_id.slice(0, 8)}...</a></dd>
              </div> : null}
            <div className="flex justify-between border-t border-line pt-3">
              <dt className="text-muted-foreground">作成日時</dt>
              <dd>{run.created_at ? new Date(run.created_at).toLocaleString("ja-JP") : "—"}</dd>
            </div>
            {run.completed_at ? <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">完了日時</dt>
                <dd>{new Date(run.completed_at).toLocaleString("ja-JP")}</dd>
              </div> : null}
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
            {run.error_code ? <div className="flex justify-between border-t border-line pt-3">
                <dt className="text-muted-foreground">エラーコード</dt>
                <dd className="font-mono text-xs text-red-600">{run.error_code}</dd>
              </div> : null}
          </dl>
        </article>
      </div>

      {!["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"].includes(run.status) ? <RunCancelButton runId={run.id} /> : null}

      <RunLiveTimeline
        runId={run.id}
        initialStatus={run.status}
        initialBlockedReason={run.blocked_reason}
        initialEvents={events.map((event) => ({
          id: event.id,
          event_type: event.event_type,
          seq_no: event.seq_no,
          payload_keys: event.payload_keys,
          created_at: event.created_at,
        }))}
      />
    </section>
  );
}
