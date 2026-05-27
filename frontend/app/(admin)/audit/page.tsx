import { fetchBackendRaw } from "@/lib/api/client";

export const dynamic = "force-dynamic";

type AuditEvent = {
  id: string;
  event_type: string;
  actor_id: string | null;
  reason_code: string | null;
  blocked_reason: string | null;
  payload_data_class: string | null;
  allowed_data_class: string | null;
  created_at: string | null;
};

async function loadAuditEvents(): Promise<AuditEvent[]> {
  try {
    const res = await fetchBackendRaw("/api/v1/audit_events" as `/${string}`);
    const raw = res as Record<string, unknown>;
    return ((raw?.items ?? raw?.events ?? []) as AuditEvent[]);
  } catch (e) {
    console.error("Audit API error:", e);
    return [];
  }
}

const EVENT_TYPE_LABELS: Record<string, string> = {
  policy_decision_created: "ポリシー判定",
  secret_canary_detected: "シークレット検出",
  runner_blocked: "ランナーブロック",
  repo_pr_opened: "PR 作成",
  approval_requested: "承認要求",
  approval_decided: "承認決定",
  run_completed: "実行完了",
  run_failed: "実行失敗",
  run_cancelled: "実行キャンセル",
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

export default async function AuditPage() {
  const events = await loadAuditEvents();

  return (
    <section aria-label="監査ログ" className="grid gap-6">
      <header className="grid gap-2">
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">監査ログ</h1>
        <p className="text-sm text-muted-foreground">
          追記専用の監査イベント ({events.length} 件)。シークレットやトークンの値は表示されません。
        </p>
      </header>

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
                <th className="px-4 py-3 text-xs font-semibold text-muted-foreground">データクラス</th>
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
                  <td className="px-4 py-3 text-xs">{e.payload_data_class ?? "—"}</td>
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
        </div>
      )}
    </section>
  );
}
