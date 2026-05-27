import { getBackendHealth, fetchBackendRaw } from "@/lib/api/client";
import type { HealthResponse } from "@/lib/api/types";
import { getFrontendHealth } from "@/lib/health";
import { StatusDonutChart } from "@/components/status-donut-chart";
import { ProgressBar } from "@/components/progress-bar";

export const dynamic = "force-dynamic";

type BackendHealthState =
  | { kind: "ok"; health: HealthResponse }
  | { kind: "error"; message: string };

type TicketStatusCounts = {
  open: number;
  in_progress: number;
  closed: number;
  cancelled: number;
};

type ProjectSummary = {
  id: string;
  slug: string;
  name: string;
  status: string;
  ticketCount: number;
  statusCounts: TicketStatusCounts;
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
      const statusCounts: TicketStatusCounts = { open: 0, in_progress: 0, closed: 0, cancelled: 0 };
      try {
        const pid = (p as any).project_id ?? (p as any).id;
        const ticketsRes = await fetchBackendRaw(`/api/v1/projects/${pid}/tickets?limit=500`) as Record<string, unknown>;
        const items = (ticketsRes?.items ?? []) as Array<{ status: string }>;
        ticketCount = (ticketsRes?.total as number) ?? items.length;
        for (const t of items) {
          if (t.status === "open") statusCounts.open++;
          else if (t.status === "in_progress" || t.status === "blocked" || t.status === "review") statusCounts.in_progress++;
          else if (t.status === "closed") statusCounts.closed++;
          else if (t.status === "cancelled") statusCounts.cancelled++;
          else statusCounts.open++;
        }
      } catch {
        ticketCount = 0;
      }
      summaries.push({
        id: String((p as any).project_id ?? (p as any).id ?? ''),
        slug: String(p.slug ?? ''),
        name: String(p.name ?? ''),
        status: String(p.status ?? 'active'),
        ticketCount,
        statusCounts,
      });
    }
    return summaries;
  } catch {
    return [];
  }
}

export default async function DashboardPage() {
  const [backendHealth, projects] = await Promise.all([
    readBackendHealth(),
    readProjectSummaries(),
  ]);
  const frontendHealth = getFrontendHealth();

  const aggCounts = projects.reduce(
    (acc, p) => ({
      open: acc.open + p.statusCounts.open,
      in_progress: acc.in_progress + p.statusCounts.in_progress,
      closed: acc.closed + p.statusCounts.closed,
      cancelled: acc.cancelled + p.statusCounts.cancelled,
    }),
    { open: 0, in_progress: 0, closed: 0, cancelled: 0 }
  );
  const ticketStatusCounts = [
    { label: "未着手", count: aggCounts.open, color: "#3b82f6" },
    { label: "進行中", count: aggCounts.in_progress, color: "#f59e0b" },
    { label: "完了", count: aggCounts.closed, color: "#10b981" },
    { label: "中止", count: aggCounts.cancelled, color: "#6b7280" },
  ];
  const totalTickets = projects.reduce((s, p) => s + p.ticketCount, 0);
  const closedTickets = aggCounts.closed;

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

            <section aria-label="全体サマリー" className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <article className="rounded-lg border border-line bg-panel p-4 shadow-sm">
          <p className="text-xs text-muted-foreground">総チケット数</p>
          <p className="mt-1 text-2xl font-bold text-ink">{projects.reduce((s: number, p: any) => s + p.ticketCount, 0)}</p>
        </article>
        <article className="rounded-lg border border-line bg-panel p-4 shadow-sm">
          <p className="text-xs text-muted-foreground">プロジェクト数</p>
          <p className="mt-1 text-2xl font-bold text-ink">{projects.length}</p>
        </article>
        <article className="rounded-lg border border-blue-200 bg-blue-50 p-4 shadow-sm">
          <p className="text-xs text-blue-600">表示中チケット</p>
          <p className="mt-1 text-2xl font-bold text-blue-700">{projects.reduce((s: number, p: any) => s + p.ticketCount, 0)}</p>
        </article>
        <article className="rounded-lg border border-emerald-200 bg-emerald-50 p-4 shadow-sm">
          <p className="text-xs text-emerald-600">稼働中プロジェクト</p>
          <p className="mt-1 text-2xl font-bold text-emerald-700">{projects.filter((p: any) => String(p.status ?? "active") === "active").length}</p>
        </article>
      </section>

      {totalTickets > 0 && (
        <section aria-label="チケット分析" className="grid gap-4 md:grid-cols-2">
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="mb-4 text-base font-semibold">ステータス分布</h2>
            <StatusDonutChart data={ticketStatusCounts} />
          </article>
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="mb-4 text-base font-semibold">完了率</h2>
            <ProgressBar value={closedTickets} max={totalTickets} label="チケット完了率" />
            <div className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-muted-foreground">完了</p>
                <p className="text-lg font-bold text-emerald-600">{closedTickets}</p>
              </div>
              <div>
                <p className="text-muted-foreground">残り</p>
                <p className="text-lg font-bold text-amber-600">{totalTickets - closedTickets}</p>
              </div>
            </div>
          </article>
        </section>
      )}

      {projects.length > 0 && (
        <section aria-label="プロジェクト横断サマリー">
          <h2 className="mb-4 text-lg font-semibold">プロジェクト一覧</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {projects.map((p) => (
              <a
                key={p.id}
                href={`/tickets?project=${p.slug}`}
                className="block rounded-lg border border-line bg-panel p-4 shadow-sm transition-all hover:border-accent/40 hover:shadow-md"
              >
                <div className="flex items-start justify-between">
                  <div>
                    <h3 className="font-semibold">{p.name}</h3>
                    <p className="mt-0.5 text-xs text-muted-foreground">{p.slug}</p>
                  </div>
                  <span className="rounded bg-emerald-50 px-2 py-0.5 text-xs font-medium text-emerald-700">
                    {p.status === "active" ? "稼働中" : p.status}
                  </span>
                </div>
                <div className="mt-3 border-t border-line pt-3">
                  <p className="text-sm">
                    <span className="font-semibold text-accent">{p.ticketCount}</span>
                    <span className="ml-1 text-muted-foreground">チケット</span>
                  </p>
                </div>
              </a>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
