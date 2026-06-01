import Link from "next/link";

import { fetchBackendRaw } from "@/lib/api/client";
import { getCostSummary, type CostSummaryResponse } from "@/lib/api/agent-runs";
import { fetchRoleFacet, type RoleFacet } from "@/lib/api/dashboard";
import { AgentRunStatusIndicator } from "@/components/agent-run-status-indicator-v2";
import { RoleBadge } from "@/components/role-badge";
import { AutoRefresh } from "@/components/auto-refresh";
import { BarChart } from "@/components/bar-chart";

export const dynamic = "force-dynamic";

type AgentRunItem = {
  id: string;
  status: string;
  blocked_reason: string | null;
  role_id: string | null;
  created_at: string | null;
  project_id: string;
};

type RunsResponse = {
  items: AgentRunItem[];
  total: number;
};

async function loadRuns(params?: {
  status?: string | undefined;
  role?: string | undefined;
  limit?: number;
  offset?: number;
}): Promise<RunsResponse> {
  try {
    const query = new URLSearchParams();
    query.set("limit", String(params?.limit ?? 200));
    if (params?.offset) query.set("offset", String(params.offset));
    if (params?.status) query.set("status", params.status);
    if (params?.role) query.set("role", params.role);
    const res = await fetchBackendRaw(`/api/v1/agent_runs?${query}` as `/${string}`);
    const raw = res as Record<string, unknown>;
    const items = (raw?.items ?? []) as AgentRunItem[];
    const total = typeof raw?.total === "number" ? raw.total : items.length;
    return { items, total };
  } catch {
    return { items: [], total: 0 };
  }
}

function groupByStatus(runs: AgentRunItem[]) {
  const active = runs.filter((r) => !["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"].includes(r.status));
  const terminal = runs.filter((r) => ["completed", "failed", "cancelled", "provider_refused", "repair_exhausted"].includes(r.status));
  return { active, terminal };
}

type RunsPageProps = {
  searchParams: Promise<{ status?: string; role?: string; page?: string }>;
};

// C-4 (UI 監査 fix): AI実行一覧は limit=200 固定でページネーション無しだった。
const RUNS_PER_PAGE = 50;

const STATUS_LABELS: Record<string, string> = {
  queued: "待機中",
  gathering_context: "情報収集中",
  running: "実行中",
  generated_artifact: "成果物生成",
  schema_validated: "スキーマ検証済",
  policy_linted: "ポリシーLint済",
  diff_ready: "差分準備完了",
  waiting_approval: "承認待ち",
  blocked: "ブロック",
  provider_refused: "プロバイダ拒否",
  provider_incomplete: "プロバイダ未完了",
  validation_failed: "検証失敗",
  repair_exhausted: "修復上限",
  completed: "完了",
  failed: "失敗",
  cancelled: "キャンセル",
};

export default async function RunsPage({ searchParams }: RunsPageProps) {
  const params = await searchParams;
  const statusFilter = params.status ?? "";
  const roleFilter = params.role ?? "";
  const parsedPage = Number(params.page ?? "1");
  const page = Number.isFinite(parsedPage) && parsedPage >= 1 ? Math.floor(parsedPage) : 1;
  const [filteredResult, allResult, roleFacetResult, costSummary] = await Promise.all([
    loadRuns({
      status: statusFilter || undefined,
      role: roleFilter || undefined,
      limit: RUNS_PER_PAGE,
      offset: (page - 1) * RUNS_PER_PAGE,
    }),
    (statusFilter || roleFilter) ? loadRuns() : Promise.resolve(null),
    // C-4 (ADR-00039): role 候補は backend role_facet endpoint (SQL distinct、limit 非依存) から作る。
    // status scoped (list と同じ status predicate) なので選択中 status に存在しない role chip を
    // クリックして空一覧になる facet drift が起きない。失敗時は空 facet に倒す。
    fetchRoleFacet(statusFilter || undefined).catch((): RoleFacet => ({ roles: [], status: null })),
    getCostSummary("all").catch((): CostSummaryResponse | null => null),
  ]);
  const filteredRuns = filteredResult.items;
  const totalRuns = filteredResult.total;
  const totalAllRuns = allResult ? allResult.total : totalRuns;

  const { active, terminal } = groupByStatus(filteredRuns);
  const statuses = Object.keys(STATUS_LABELS);
  const roleSet = new Set(roleFacetResult.roles.map((r) => r.role_id).filter(Boolean));
  if (roleFilter) roleSet.add(roleFilter); // 選択中ロールは facet に無くても chip に保持
  const roles = [...roleSet].sort();
  const totalPages = Math.max(1, Math.ceil(totalRuns / RUNS_PER_PAGE));
  const runsPageHref = (targetPage: number): string => {
    const q = new URLSearchParams();
    if (statusFilter) q.set("status", statusFilter);
    if (roleFilter) q.set("role", roleFilter);
    if (targetPage > 1) q.set("page", String(targetPage));
    const qs = q.toString();
    return qs ? `/runs?${qs}` : "/runs";
  };

  return (
    <section aria-label="AI 実行一覧" className="grid gap-6">
      <AutoRefresh intervalMs={30000} enabled={active.length > 0} />
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">AI 実行</h1>
        <div className="flex items-center gap-3 text-sm text-muted-foreground">
          <span>全 {filteredRuns.length} 実行</span>
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

      {/* S-1: 印刷時は filter 操作子を隠すが、印刷された一覧が「全件」に誤読されないよう、
          有効な status / role フィルタとページ番号を print 専用サマリで残す (Codex App P2)。 */}
      <p className="print-only text-sm text-ink">
        フィルタ: ステータス = {statusFilter ? (STATUS_LABELS[statusFilter] ?? statusFilter) : "すべて"}
        {" ・ "}ロール = {roleFilter || "すべて"}
        {" ・ "}ページ {page} / {totalPages}
      </p>
      {/* S-1: フィルタ操作子は印刷物に出さない (.no-print)。チップは画面では 44px tap target (I-3)。 */}
      <div className="no-print flex flex-wrap items-center gap-3">
        <div className="flex flex-wrap gap-1">
          <Link href="/runs" className={`inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium ${!statusFilter ? "bg-accent text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
            すべて
          </Link>
          {statuses.map((s) => (
            <a key={s} href={`/runs?status=${s}${roleFilter ? `&role=${roleFilter}` : ""}`} className={`inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium ${statusFilter === s ? "bg-accent text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
              {STATUS_LABELS[s] ?? s}
            </a>
          ))}
        </div>
        {roles.length > 0 ? <div className="flex flex-wrap gap-1">
            <span className="text-xs text-muted-foreground">ロール:</span>
            {roles.map((r) => (
              <a key={r} href={`/runs?${statusFilter ? `status=${statusFilter}&` : ""}role=${r}`} className={`inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium ${roleFilter === r ? "bg-accent text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}>
                {r}
              </a>
            ))}
          </div> : null}
      </div>

      {costSummary && costSummary.run_count > 0 ? <section aria-label="コスト集計" className="grid gap-4 md:grid-cols-2">
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="text-base font-semibold">コスト・トークン集計</h2>
            <dl className="mt-4 grid grid-cols-2 gap-3 text-sm">
              <div>
                <dt className="text-xs text-muted-foreground">総コスト</dt>
                <dd className="text-lg font-bold text-accent">
                  {costSummary.total_cost_usd != null ? `$${costSummary.total_cost_usd.toFixed(4)}` : "未計測"}
                </dd>
                {costSummary.unmeasured_run_count > 0 ? <p className="text-[10px] text-muted-foreground">
                    {costSummary.measured_run_count}/{costSummary.run_count} 件計測済
                  </p> : null}
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">実行数</dt>
                <dd className="text-lg font-bold">{costSummary.run_count}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">入力トークン</dt>
                <dd className="font-semibold">{costSummary.total_tokens_input.toLocaleString()}</dd>
              </div>
              <div>
                <dt className="text-xs text-muted-foreground">出力トークン</dt>
                <dd className="font-semibold">{costSummary.total_tokens_output.toLocaleString()}</dd>
              </div>
            </dl>
          </article>
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="mb-4 text-base font-semibold">ステータス別コスト</h2>
            <BarChart
              data={costSummary.by_status
                .filter((s) => s.cost_usd > 0)
                .map((s) => ({ label: STATUS_LABELS[s.status] ?? s.status, value: Math.round(s.cost_usd * 10000) / 10000 }))}
            />
          </article>
        </section> : null}

      {active.length > 0 ? <div>
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
        </div> : null}

      {terminal.length > 0 ? <div>
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
        </div> : null}

      {totalAllRuns === 0 ? <div className="rounded-lg border border-line bg-panel p-8 text-center">
          <p className="text-muted-foreground">AI 実行はまだありません</p>
          <p className="mt-2 text-xs text-muted-foreground">
            MCP 経由で run_create を実行するか、Superintendent から dispatch して AI 実行を開始できます。
          </p>
          <a href="/dashboard" className="mt-3 inline-block rounded-md bg-accent px-4 py-2 text-sm font-medium text-white hover:bg-accent/90">
            ダッシュボードへ
          </a>
        </div> : null}

      {totalAllRuns > 0 && filteredRuns.length === 0 ? <div className="rounded-lg border border-line bg-panel p-8 text-center">
          <p className="text-muted-foreground">条件に一致する実行がありません</p>
          <p className="mt-2 text-xs text-muted-foreground">
            フィルターを変更するか、すべて表示に切り替えてください。
          </p>
          <Link href="/runs" className="mt-3 inline-block rounded-md border border-line px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-slate-50">
            フィルターをリセット
          </Link>
        </div> : null}

      {totalRuns > RUNS_PER_PAGE ? <nav aria-label="ページネーション" className="no-print flex items-center justify-center gap-2">
          {page > 1 ? (
            <a href={runsPageHref(page - 1)} className="inline-flex items-center justify-center rounded border border-line px-3 py-1 text-sm hover:bg-slate-50">
              前へ
            </a>
          ) : null}
          <span className="text-sm text-muted-foreground">{page} / {totalPages}</span>
          {page < totalPages ? (
            <a href={runsPageHref(page + 1)} className="inline-flex items-center justify-center rounded border border-line px-3 py-1 text-sm hover:bg-slate-50">
              次へ
            </a>
          ) : null}
        </nav> : null}
    </section>
  );
}
