import { getBackendHealth, fetchBackendRaw } from "@/lib/api/client";
import { listCurrentProjects } from "@/lib/api/session";
import { fetchTicketSummary, foldTicketDisplayCounts, fetchActivityTimeseries, buildActivityTrendSeries } from "@/lib/api/dashboard";
import type { HealthResponse } from "@/lib/api/types";
import { getFrontendHealth } from "@/lib/health";
import { StatusDonutChart } from "@/components/status-donut-chart";
import { ProgressBar } from "@/components/progress-bar";
import { DateRangeFilter } from "@/components/date-range-filter";
import { BarChart } from "@/components/bar-chart";
import { WelcomeBanner } from "@/components/welcome-banner";
import { RecentTicketsList } from "@/components/recent-tickets";
// ExportButton は Tier 4 (設計承認後) に有効化

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

// D-5 (Codex review R2 fix): project-count card は全 project list の status から正確に出せる
// (ticket fetch 不要)。ticket-level 集計だけ先頭 10 project に bound する (pre-existing、
// 完全な ticket 総数は backend aggregate endpoint が必要 = follow-up)。
async function readProjectSummaries(): Promise<
  | { ok: true; summaries: ProjectSummary[]; projectTotal: number; activeProjectTotal: number }
  | { ok: false }
> {
  try {
    // /api/v1/me/projects は zod-backed な listCurrentProjects() で取得する (raw fetch +
    // unchecked cast を避ける)。schema drift / malformed response では fetchBackendJson が
    // throw し、下の catch で degraded 空状態に倒れる (fail-closed)。
    const { projects } = await listCurrentProjects();
    const projectTotal = projects.length;
    const activeProjectTotal = projects.filter((p) => p.status === "active").length;
    // H-2 (UI 監査 fix): 各 project の tickets fetch を逐次 await から Promise.all 並列化 (N+1 解消)。
    const summaries: ProjectSummary[] = await Promise.all(
      projects.slice(0, 10).map(async (p): Promise<ProjectSummary> => {
        // per-project ticketCount は BarChart / project card 表示用 (total は accurate)。
        // status 別母数は ticket_summary endpoint (全 project SQL 集計) に移譲済 (D-5)。
        let ticketCount = 0;
        try {
          const ticketsRes = await fetchBackendRaw(`/api/v1/projects/${p.project_id}/tickets?limit=1`) as Record<string, unknown>;
          const items = (ticketsRes?.items ?? []) as { status: string }[];
          ticketCount = typeof ticketsRes?.total === "number" ? (ticketsRes.total as number) : items.length;
        } catch {
          ticketCount = 0;
        }
        return {
          id: p.project_id,
          slug: p.slug,
          name: p.name,
          status: p.status,
          ticketCount,
        };
      })
    );
    return { ok: true, summaries, projectTotal, activeProjectTotal };
  } catch {
    // 取得失敗 (auth 失効 / schema drift / backend down) を空配列 + 0 として返すと「真の 0 件」と
    // 区別できないため、ok:false を返して render 側で degraded (—) 表示にする (Codex R2、ticket
    // summary 側と同じ ok/error 方針)。
    return { ok: false };
  }
}

type DashboardProps = {
  searchParams: Promise<{ range?: string }>;
};

export default async function DashboardPage({ searchParams }: DashboardProps) {
  const params = await searchParams;
  const rangeFilter = params.range ?? "";
  const [backendHealth, projectData, ticketSummaryResult, activityResult] = await Promise.all([
    readBackendHealth(),
    readProjectSummaries(),
    // D-5 (ADR-00039): status 別母数は backend SQL 集計 (limit 非依存)。
    // Codex R1-2: 失敗 (404/500/auth/schema drift) を ticket_total=0 の有効データに変換すると
    // 「0 件」と「集計失敗」を混同するため、ok/error を区別して degraded 表示にする。
    fetchTicketSummary()
      .then((summary) => ({ ok: true as const, summary }))
      .catch(() => ({ ok: false as const })),
    // D-3/D-4 (ADR-00040): AI 実行アクティビティ + コスト時系列。失敗は degraded 表示。
    fetchActivityTimeseries("day", "month")
      .then((timeseries) => ({ ok: true as const, timeseries }))
      .catch(() => ({ ok: false as const })),
  ]);
  // 取得失敗時は null にして count cards を「—」表示にする (失敗を真の 0 件と誤認させない)。
  const projectDataOk = projectData.ok;
  const projects = projectDataOk ? projectData.summaries : [];
  const projectTotal = projectDataOk ? projectData.projectTotal : null;
  const activeProjectTotal = projectDataOk ? projectData.activeProjectTotal : null;
  const frontendHealth = getFrontendHealth();

  // D-5 (ADR-00039 R2): backend の raw status_counts を表示 4 bucket に折り畳む
  // (in_progress = in_progress+blocked+review)。4 bucket 合計 == ticket_total。
  const ticketSummaryOk = ticketSummaryResult.ok;
  const aggCounts = ticketSummaryOk
    ? foldTicketDisplayCounts(ticketSummaryResult.summary.status_counts)
    : { open: 0, in_progress: 0, closed: 0, cancelled: 0 };
  const ticketStatusCounts = [
    { label: "未着手", count: aggCounts.open, color: "#3b82f6" },
    { label: "進行中", count: aggCounts.in_progress, color: "#f59e0b" },
    { label: "完了", count: aggCounts.closed, color: "#10b981" },
    { label: "中止", count: aggCounts.cancelled, color: "#6b7280" },
  ];
  // 集計失敗時は 0 を「真の 0 件」として描画しない (donut/bar は totalTickets>0 guard で非表示)。
  const totalTickets = ticketSummaryOk ? ticketSummaryResult.summary.ticket_total : 0;
  const closedTickets = aggCounts.closed;

  // D-3/D-4 (ADR-00040): bucket_start を UTC で MM/DD ラベル化し 2 系列を BarChart 用に整形。
  // sparse series (active bucket のみ)。cost 系列は cost_usd=null (未計測) bucket を 0 に丸めず除外。
  const activityOk = activityResult.ok;
  const activityBuckets = activityOk ? activityResult.timeseries.buckets : [];
  const { activity: activityTrendData, cost: costTrendData } =
    buildActivityTrendSeries(activityBuckets);

  return (
    <div className="grid gap-6">
      <WelcomeBanner />
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">ダッシュボード</h1>
        <div className="flex items-center gap-2">
          <DateRangeFilter />
          {rangeFilter ? <span className="text-xs text-muted-foreground">
              ※ 期間フィルターはチケット一覧ページで適用されます
            </span> : null}
        </div>
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
          {/* 集計失敗時は 0 ではなく「—」を表示し、失敗を真の 0 件と誤認させない (Codex R1-2)。 */}
          <p className="mt-1 text-2xl font-bold text-ink">{ticketSummaryOk ? totalTickets : "—"}</p>
          {ticketSummaryOk ? null : (
            <p className="mt-1 text-xs text-danger">集計を取得できませんでした</p>
          )}
        </article>
        <article className="rounded-lg border border-line bg-panel p-4 shadow-sm">
          <p className="text-xs text-muted-foreground">プロジェクト数</p>
          {/* 取得失敗時は 0 ではなく「—」を表示し、失敗を真の 0 件と誤認させない (Codex R2)。 */}
          <p className="mt-1 text-2xl font-bold text-ink">{projectTotal ?? "—"}</p>
          {projectDataOk ? null : (
            <p className="mt-1 text-xs text-danger">プロジェクト一覧を取得できませんでした</p>
          )}
        </article>
        {/* D-5 (UI 監査 fix): 旧「表示中チケット」は「総チケット数」と同一式の重複だった。完了チケット
            (statusCounts) は 200 件 client 集計で総数と不整合のため、全 project list の status から正確に
            出せる active/archived に分ける (Codex review R1#2/R2: project-count は ticket fetch 不要)。 */}
        <article className="rounded-lg border border-blue-200 bg-blue-50 p-4 shadow-sm">
          <p className="text-xs text-blue-600">稼働中プロジェクト</p>
          <p className="mt-1 text-2xl font-bold text-blue-700">{activeProjectTotal ?? "—"}</p>
        </article>
        <article className="rounded-lg border border-amber-200 bg-amber-50 p-4 shadow-sm">
          <p className="text-xs text-amber-600">アーカイブ済プロジェクト</p>
          <p className="mt-1 text-2xl font-bold text-amber-700">
            {projectTotal != null && activeProjectTotal != null ? projectTotal - activeProjectTotal : "—"}
          </p>
        </article>
      </section>

      {totalTickets > 0 ? <section aria-label="チケット分析" className="grid gap-4 md:grid-cols-2">
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
        </section> : null}

      {totalTickets > 0 ? <section aria-label="トレンド" className="grid gap-4 md:grid-cols-2">
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="mb-4 text-base font-semibold">プロジェクト別チケット数</h2>
            <BarChart data={projects.map((p) => ({ label: p.slug.slice(0, 8), value: p.ticketCount }))} />
          </article>
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="text-base font-semibold">ステータス別集計</h2>
            <BarChart data={ticketStatusCounts.filter((d) => d.count > 0).map((d) => ({ label: d.label, value: d.count }))} />
          </article>
        </section> : null}

      {/* D-3/D-4 (ADR-00040): AI 実行アクティビティ + コスト推移 (日次、直近 1 ヶ月、sparse)。 */}
      <section aria-label="AI 実行トレンド" className="grid gap-4 md:grid-cols-2">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">AI 実行アクティビティ (日次)</h2>
          {activityOk ? (
            activityTrendData.length > 0 ? (
              <BarChart data={activityTrendData} />
            ) : (
              <p className="text-sm text-muted-foreground">直近 1 ヶ月の AI 実行はありません</p>
            )
          ) : (
            <p className="text-sm text-danger">トレンドを取得できませんでした</p>
          )}
        </article>
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="mb-4 text-base font-semibold">コスト推移 (日次, USD)</h2>
          {activityOk ? (
            costTrendData.length > 0 ? (
              <BarChart data={costTrendData} />
            ) : (
              <p className="text-sm text-muted-foreground">計測済みのコストデータがありません</p>
            )
          ) : (
            <p className="text-sm text-danger">トレンドを取得できませんでした</p>
          )}
        </article>
      </section>

      {projects.length > 0 ? <section aria-label="プロジェクト横断サマリー">
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
                  <span
                    className={`rounded px-2 py-0.5 text-xs font-medium ${
                      p.status === "active"
                        ? "bg-emerald-50 text-emerald-700"
                        : "bg-amber-50 text-amber-700"
                    }`}
                  >
                    {/* K-3 (UI 監査 fix): archived 等の英語 fallback を日本語化 */}
                    {p.status === "active"
                      ? "稼働中"
                      : p.status === "archived"
                        ? "アーカイブ済"
                        : p.status}
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
        </section> : null}
      <aside className="rounded-lg border border-line bg-panel p-5 shadow-sm">
        <h2 className="text-base font-semibold">最近のチケット</h2>
        <div className="mt-3">
          <RecentTicketsList />
        </div>
      </aside>
    </div>
  );
}
