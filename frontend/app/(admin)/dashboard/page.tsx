import { getBackendHealth, fetchBackendRaw } from "@/lib/api/client";
import type { HealthResponse } from "@/lib/api/types";
import { getFrontendHealth } from "@/lib/health";

export const dynamic = "force-dynamic";

type BackendHealthState =
  | { kind: "ok"; health: HealthResponse }
  | { kind: "error"; message: string };

type ProjectSummary = {
  id: string;
  slug: string;
  name: string;
  status: string;
  ticketCount: number;
};

async function readBackendHealth(): Promise<BackendHealthState> {
  try {
    return { kind: "ok", health: await getBackendHealth() };
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : "バックエンドの接続に失敗しました。";
    return { kind: "error", message };
  }
}

async function readProjectSummaries(): Promise<ProjectSummary[]> {
  try {
    const projectsRes = await fetchBackendRaw("/api/v1/me/projects");
    const rawRes = projectsRes as Record<string, unknown> | null;
    const projects = (Array.isArray(rawRes) ? rawRes : ((rawRes as any)?.projects ?? (rawRes as any)?.items ?? [])) as Array<Record<string, string>>;
    if (!Array.isArray(projects)) return [];

    const summaries: ProjectSummary[] = [];
    for (const p of projects.slice(0, 10)) {
      let ticketCount = 0;
      try {
        const pid = (p as any).project_id ?? (p as any).id;
        const ticketsRes = await fetchBackendRaw(`/api/v1/projects/${pid}/tickets`) as Record<string, unknown>;
        ticketCount = (ticketsRes?.total as number) ?? ((ticketsRes?.items as unknown[])?.length ?? 0);
      } catch {
        ticketCount = 0;
      }
      summaries.push({
        id: String((p as any).project_id ?? (p as any).id ?? ''),
        slug: String(p.slug ?? ''),
        name: String(p.name ?? ''),
        status: String(p.status ?? 'active'),
        ticketCount,
      });
    }
    return summaries;
  } catch {
    return [];
  }
}

export default async function DashboardPage() {
  const backendHealth = await readBackendHealth();
  const frontendHealth = getFrontendHealth();
  const projects = await readProjectSummaries();

  return (
    <div className="grid gap-6">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">ダッシュボード</h1>
      </header>

      <section aria-label="サービス状態" className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">フロントエンド</h2>
              <p className="mt-1 text-sm text-muted-foreground">フロントエンドの状態確認</p>
            </div>
            <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
              {frontendHealth.status}
            </span>
          </div>
          <dl className="mt-5 grid gap-3 text-sm">
            <div className="flex justify-between gap-4 border-t border-line pt-3">
              <dt className="text-muted-foreground">エンドポイント</dt>
              <dd className="font-mono">/api/healthz</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-line pt-3">
              <dt className="text-muted-foreground">サービス</dt>
              <dd className="font-mono">{frontendHealth.service}</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-line pt-3">
              <dt className="text-muted-foreground">ランタイム</dt>
              <dd className="font-mono">{frontendHealth.runtime}</dd>
            </div>
            <div className="flex justify-between gap-4 border-t border-line pt-3">
              <dt className="text-muted-foreground">実行環境</dt>
              <dd className="font-mono">{frontendHealth.node_env}</dd>
            </div>
          </dl>
        </article>

        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h2 className="text-base font-semibold">バックエンド</h2>
              <p className="mt-1 text-sm text-muted-foreground">バックエンドの状態確認</p>
            </div>
            {backendHealth.kind === "ok" ? (
              <span className="rounded-md bg-emerald-50 px-2 py-1 text-xs font-semibold text-emerald-700">
                {backendHealth.health.status}
              </span>
            ) : (
              <span className="rounded-md bg-amber-50 px-2 py-1 text-xs font-semibold text-attention">
                利用不可
              </span>
            )}
          </div>

          {backendHealth.kind === "ok" ? (
            <dl className="mt-5 grid gap-3 text-sm">
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted-foreground">サービス</dt>
                <dd className="font-mono">{backendHealth.health.service}</dd>
              </div>
              <div className="flex justify-between gap-4 border-t border-line pt-3">
                <dt className="text-muted-foreground">バージョン</dt>
                <dd className="font-mono">{backendHealth.health.version}</dd>
              </div>
            </dl>
          ) : (
            <p role="status" className="mt-5 border-t border-line pt-3 text-sm text-muted-foreground">
              {backendHealth.message}
            </p>
          )}
        </article>
      </section>

      {projects.length > 0 && (
        <section aria-label="プロジェクト横断サマリー">
          <h2 className="mb-4 text-lg font-semibold">プロジェクト一覧</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <article
                key={p.id}
                className="rounded-lg border border-line bg-panel p-4 shadow-sm transition-colors hover:border-accent/30"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-semibold">{p.name}</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">{p.slug}</p>
                  </div>
                  <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                    {p.status}
                  </span>
                </div>
                <div className="mt-3 border-t border-line pt-3">
                  <p className="text-sm">
                    <span className="font-semibold text-accent">{p.ticketCount}</span>
                    <span className="ml-1 text-muted-foreground">チケット</span>
                  </p>
                </div>
              </article>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
