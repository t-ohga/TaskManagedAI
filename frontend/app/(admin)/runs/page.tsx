import Link from "next/link";

import { fetchBackendRaw } from "@/lib/api/client";
import { AgentRunStatusIndicator } from "@/components/agent-run-status-indicator-v2";
import { RoleBadge } from "@/components/role-badge";

export const dynamic = "force-dynamic";

type AgentRunItem = {
  id: string;
  status: string;
  blocked_reason: string | null;
  role_id: string | null;
  created_at: string | null;
  project_id: string;
};

async function loadRuns(): Promise<AgentRunItem[]> {
  try {
    const res = await fetchBackendRaw("/api/v1/agent_runs?limit=200" as `/${string}`);
    const raw = res as Record<string, unknown>;
    return ((raw?.items ?? []) as AgentRunItem[]);
  } catch (e) {
    // AgentRun API error — display empty state
    return [];
  }
}

function groupByStatus(runs: AgentRunItem[]) {
  const active = runs.filter((r) => !["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"].includes(r.status));
  const terminal = runs.filter((r) => ["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"].includes(r.status));
  return { active, terminal };
}

export default async function RunsPage() {
  const runs = await loadRuns();
  const { active, terminal } = groupByStatus(runs);

  return (
    <section aria-label="AI 実行一覧" className="grid gap-6">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">AI 実行</h1>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>全 {runs.length} 実行</span>
          <span className="text-muted-foreground/50">|</span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-amber-500" />
            アクティブ {active.length}
          </span>
          <span className="flex items-center gap-1">
            <span className="inline-block h-2 w-2 rounded-full bg-emerald-500" />
            完了 {terminal.length}
          </span>
        </div>
      </header>

      {active.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">アクティブな実行</h2>
          <div className="grid gap-2">
            {active.map((run) => (
              <Link
                key={run.id}
                href={`/runs/${run.id}` as never}
                className="flex items-center justify-between rounded-lg border border-line bg-panel px-4 py-3 shadow-sm transition-all hover:border-accent/40 hover:shadow-md"
              >
                <div className="flex items-center gap-3">
                  <AgentRunStatusIndicator status={run.status} blockedReason={run.blocked_reason} />
                  <RoleBadge role={run.role_id} />
                  <span className="font-mono text-xs text-muted-foreground">{run.id.slice(0, 8)}...</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {run.created_at ? new Date(run.created_at).toLocaleString("ja-JP") : ""}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {terminal.length > 0 && (
        <div>
          <h2 className="mb-3 text-lg font-semibold">完了した実行</h2>
          <div className="grid gap-2">
            {terminal.map((run) => (
              <Link
                key={run.id}
                href={`/runs/${run.id}` as never}
                className="flex items-center justify-between rounded-lg border border-line bg-panel px-4 py-3 opacity-70 transition-all hover:opacity-100"
              >
                <div className="flex items-center gap-3">
                  <AgentRunStatusIndicator status={run.status} blockedReason={run.blocked_reason} />
                  <RoleBadge role={run.role_id} />
                  <span className="font-mono text-xs text-muted-foreground">{run.id.slice(0, 8)}...</span>
                </div>
                <span className="text-xs text-muted-foreground">
                  {run.created_at ? new Date(run.created_at).toLocaleString("ja-JP") : ""}
                </span>
              </Link>
            ))}
          </div>
        </div>
      )}

      {runs.length === 0 && (
        <div className="rounded-lg border border-line bg-panel p-8 text-center">
          <p className="text-muted-foreground">AI 実行はまだありません</p>
          <p className="mt-2 text-xs text-muted-foreground">
            MCP 経由で run_create を実行するか、Superintendent から dispatch して AI 実行を開始できます。
          </p>
          <a href="/dashboard" className="mt-3 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90">
            ダッシュボードへ
          </a>
        </div>
      )}
    </section>
  );
}
