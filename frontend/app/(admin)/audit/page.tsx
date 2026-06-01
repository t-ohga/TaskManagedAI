import { fetchBackendRaw } from "@/lib/api/client";

export const dynamic = "force-dynamic";

type AuditEvent = {
  id: string;
  event_type: string;
  actor_id: string | null;
  reason_code: string | null;
  payload_keys: string[];
  payload_redaction_status: string | null;
  created_at: string | null;
};

type AuditResponse = {
  items: AuditEvent[];
  total: number;
};

async function loadAuditEvents(params: {
  eventType?: string | undefined;
  limit: number;
  offset: number;
}): Promise<AuditResponse> {
  try {
    const query = new URLSearchParams();
    query.set("limit", String(params.limit));
    query.set("offset", String(params.offset));
    if (params.eventType) query.set("event_type", params.eventType);
    const res = await fetchBackendRaw(`/api/v1/audit_events?${query}` as `/${string}`);
    const raw = res as Record<string, unknown>;
    const items = (raw?.items ?? raw?.events ?? []) as AuditEvent[];
    const total = typeof raw?.total === "number" ? raw.total : items.length;
    return { items, total };
  } catch {
    return { items: [], total: 0 };
  }
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  run_queued: "実行待機",
  context_gathered: "情報収集完了",
  provider_requested: "プロバイダ要求",
  provider_responded: "プロバイダ応答",
  artifact_generated: "成果物生成",
  schema_validated: "スキーマ検証",
  validation_failed: "検証失敗",
  repair_retry_scheduled: "修復リトライ",
  repair_exhausted: "修復上限到達",
  policy_linted: "ポリシーLint",
  policy_blocked: "ポリシーブロック",
  policy_decision_created: "ポリシー判定",
  budget_blocked: "予算ブロック",
  budget_created: "予算作成",
  budget_limits_updated: "予算上限更新",
  budget_active_flag_updated: "予算有効化更新",
  budget_soft_threshold_warning: "予算警告",
  runtime_blocked: "ランタイムブロック",
  diff_ready: "差分準備完了",
  approval_requested: "承認要求",
  approval_decided: "承認決定",
  approval_pending: "承認待ち",
  approval_revision_requested: "承認修正要求",
  runner_started: "ランナー開始",
  runner_completed: "ランナー完了",
  runner_blocked: "ランナーブロック",
  repo_pr_opened: "PR 作成",
  run_completed: "実行完了",
  run_failed: "実行失敗",
  run_cancelled: "実行キャンセル",
  provider_blocked: "プロバイダブロック",
  secret_canary_detected: "シークレット検出",
  secret_capability_issued: "シークレット発行",
  secret_capability_redeemed: "シークレット使用",
  secret_capability_denied: "シークレット拒否",
  secret_rotation_issue_new: "シークレットローテーション新規",
  secret_rotation_promote: "シークレットローテーション昇格",
  secret_rotation_revoke: "シークレットローテーション無効化",
  secret_rotation_rollback: "シークレットローテーション巻戻し",
  config_changed: "設定変更",
  ticket_created: "チケット作成",
  ticket_comment: "チケットコメント",
  claim_created: "クレーム作成",
  evidence_item_attached: "エビデンス添付",
  notification_resolved: "通知解決",
  notification_snoozed: "通知スヌーズ",
  orchestrator_dispatched: "オーケストレータ配信",
  orchestrator_lease_renewed: "リース更新",
  orchestrator_lease_expired: "リース期限切れ",
  orchestrator_failover_triggered: "フェイルオーバー",
  orchestrator_kill_engaged: "キル実行",
  inter_agent_message_sent: "エージェント間送信",
  inter_agent_message_consumed: "エージェント間受信",
  inter_agent_message_denied: "エージェント間拒否",
  api_capability_token_issued: "APIトークン発行",
  api_capability_token_denied: "APIトークン拒否",
  api_capability_token_revoked: "APIトークン無効化",
  api_capability_token_scope_mismatch: "APIトークン権限不一致",
};

function eventTypeBadge(eventType: string) {
  const label = EVENT_TYPE_LABELS[eventType] ?? eventType;
  const colors: Record<string, string> = {
    policy_decision_created: "bg-blue-50 text-blue-700",
    secret_canary_detected: "bg-red-50 text-red-700",
    runner_blocked: "bg-orange-50 text-orange-700",
    repo_pr_opened: "bg-emerald-50 text-emerald-700",
    approval_requested: "bg-purple-50 text-purple-700",
    approval_decided: "bg-purple-50 text-purple-700",
    run_completed: "bg-emerald-50 text-emerald-700",
    run_failed: "bg-red-50 text-red-700",
  };
  return (
    <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${colors[eventType] ?? "bg-gray-100 text-gray-600"}`}>
      {label}
    </span>
  );
}

type AuditPageProps = {
  searchParams: Promise<{ type?: string; page?: string }>;
};

const PAGE_SIZE = 50;

export default async function AuditPage({ searchParams }: AuditPageProps) {
  const params = await searchParams;
  const typeFilter = params.type ?? "";
  const parsedPage = Number(params.page ?? "1");
  const pageNum = Number.isFinite(parsedPage) && parsedPage >= 1 ? Math.floor(parsedPage) : 1;
  const { items: events, total } = await loadAuditEvents({
    eventType: typeFilter || undefined,
    limit: PAGE_SIZE,
    offset: (pageNum - 1) * PAGE_SIZE,
  });
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const eventTypes = Object.keys(EVENT_TYPE_LABELS);

  return (
    <section aria-label="監査ログ" className="grid gap-6">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">監査ログ</h1>
        <p className="text-sm text-muted-foreground">
          追記専用の監査イベント ({total} 件)。シークレットやトークンの値は表示されません。
        </p>
      </header>

      {/* S-1: 印刷時は filter 操作子を隠すが、印刷された証跡が「全ログ」に誤読されないよう、
          有効なイベント種別フィルタとページ番号を print 専用サマリで残す (Codex App P2)。 */}
      <p className="print-only text-sm text-ink">
        フィルタ: イベント種別 = {typeFilter ? (EVENT_TYPE_LABELS[typeFilter] ?? typeFilter) : "すべて"}
        {" ・ "}ページ {pageNum} / {totalPages}
      </p>
      {/* S-1: 監査ログは証跡として印刷価値が高い。絞り込み / ページ移動の操作子は印刷物に出さず、
          ヘッダー / マスク注意 / テーブル本体だけを残す (.no-print)。チップは画面では 44px tap target。 */}
      <div className="no-print flex flex-wrap items-center gap-3">
        {/* a11y: フィルタチップ群のグループラベル。単一 control 用の <label> ではなく
            role="group" + aria-labelledby でラベル付けする (jsx-a11y/label-has-associated-control)。 */}
        <span className="text-xs text-muted-foreground" id="audit-event-type-filter-label">
          イベント種別:
        </span>
        <div
          className="flex flex-wrap gap-1"
          role="group"
          aria-labelledby="audit-event-type-filter-label"
        >
          <a
            href="/audit"
            className={`inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium transition-colors ${!typeFilter ? "bg-accent text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
          >
            すべて
          </a>
          {eventTypes.map((t) => (
            <a
              key={t}
              href={`/audit?type=${t}`}
              className={`inline-flex items-center justify-center rounded-full px-3 py-1 text-xs font-medium transition-colors ${typeFilter === t ? "bg-accent text-white" : "bg-gray-100 text-gray-600 hover:bg-gray-200"}`}
            >
              {EVENT_TYPE_LABELS[t] ?? t}
            </a>
          ))}
        </div>
      </div>

      <div className="rounded-lg border border-red-200 bg-red-50 px-4 py-3">
        <p className="text-sm font-medium text-red-700">AC-HARD-02 監査マスク</p>
        <p className="mt-1 text-xs text-red-600">
          生のシークレット、トークン、プロバイダーキーは表示されません。reason_code、パターン検出、ハッシュ参照のみ。
        </p>
      </div>

      {events.length > 0 ? (
        <div className="overflow-x-auto rounded-lg border border-line">
          <table className="min-w-full text-left text-sm">
            <thead className="border-b border-line bg-slate-50">
              <tr>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground">イベント種別</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground">アクター</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground">理由コード</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground">ペイロード</th>
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground">日時</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-line">
              {events.map((e) => (
                <tr key={e.id} className="hover:bg-slate-50">
                  <td className="px-4 py-3">{eventTypeBadge(e.event_type)}</td>
                  <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                    {e.actor_id ? e.actor_id.slice(0, 8) + "..." : "—"}
                  </td>
                  <td className="px-4 py-3 text-xs">{e.reason_code ?? "—"}</td>
                  <td className="px-4 py-3 text-xs">{e.payload_keys?.length ? e.payload_keys.join(", ") : "—"}</td>
                  <td className="px-4 py-3 text-xs text-muted-foreground">
                    {e.created_at ? new Date(e.created_at).toLocaleString("ja-JP") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : (
        <div className="rounded-lg border border-line bg-panel p-8 text-center">
          <p className="text-muted-foreground">監査イベントはまだありません</p>
          <p className="mt-2 text-xs text-muted-foreground">
            チケット操作や AI 実行を行うと、ここにイベントが記録されます
          </p>
        </div>
      )}

      {totalPages > 1 && (
        <nav aria-label="ページネーション" className="no-print flex items-center justify-center gap-2">
          {pageNum > 1 && (
            <a href={`/audit?${typeFilter ? `type=${typeFilter}&` : ""}page=${pageNum - 1}`} className="inline-flex items-center justify-center rounded border border-line px-3 py-1 text-sm hover:bg-slate-50">
              前へ
            </a>
          )}
          <span className="text-sm text-muted-foreground">{pageNum} / {totalPages}</span>
          {pageNum < totalPages && (
            <a href={`/audit?${typeFilter ? `type=${typeFilter}&` : ""}page=${pageNum + 1}`} className="inline-flex items-center justify-center rounded border border-line px-3 py-1 text-sm hover:bg-slate-50">
              次へ
            </a>
          )}
        </nav>
      )}
    </section>
  );
}
