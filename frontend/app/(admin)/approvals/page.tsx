import Link from "next/link";

import {
  listApprovals,
  type ApprovalListItem,
  type ApprovalStatus
} from "@/lib/api/approvals";
import {
  formatApprovalActionClass,
  formatApprovalStatus,
  formatRiskLevel
} from "@/lib/i18n/approval-labels";

export const dynamic = "force-dynamic";

type ApprovalInboxPageProps = {
  searchParams?: Promise<{ status?: string }>;
};

const APPROVAL_STATUSES: readonly ApprovalStatus[] = [
  "pending",
  "approved",
  "rejected",
  "expired",
  "invalidated"
];

function parseStatus(value: string | undefined): ApprovalStatus {
  return APPROVAL_STATUSES.includes(value as ApprovalStatus)
    ? (value as ApprovalStatus)
    : "pending";
}

export default async function ApprovalInboxPage({
  searchParams
}: ApprovalInboxPageProps = {}) {
  const { status } = searchParams ? await searchParams : {};
  const selectedStatus = parseStatus(status);
  let approvals: ApprovalListItem[];
  try {
    approvals = await listApprovals({ status: selectedStatus });
  } catch (error: unknown) {
    return (
      <section aria-label="承認一覧" className="grid gap-4">
        <h1 className="text-2xl font-semibold">承認一覧</h1>
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
          承認一覧の取得に失敗しました: {error instanceof Error ? error.message : "不明なエラー"}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="承認一覧" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">管理</p>
        <h1 className="text-3xl font-semibold tracking-normal">承認一覧</h1>
        <p className="mt-2 text-sm text-muted">
          {formatApprovalStatus(selectedStatus)} の承認 request を表示しています。
        </p>
      </header>

      <nav aria-label="承認ステータス" className="flex flex-wrap gap-2">
        {APPROVAL_STATUSES.map((statusValue) => {
          const isActive = statusValue === selectedStatus;
          return (
            <Link
              key={statusValue}
              aria-current={isActive ? "page" : undefined}
              className={
                isActive
                  ? "rounded-md bg-teal-50 px-3 py-2 text-sm font-semibold text-accent"
                  : "rounded-md border border-line px-3 py-2 text-sm font-medium text-muted hover:bg-panel-muted"
              }
              href={`/approvals?status=${statusValue}`}
            >
              {formatApprovalStatus(statusValue)}
            </Link>
          );
        })}
      </nav>

      {approvals.length === 0 ? (
        <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
          {formatApprovalStatus(selectedStatus)} の承認 request はありません。
        </p>
      ) : (
        <ul className="grid gap-3" data-testid="approval-pending-list">
          {approvals.map((approval) => (
            <li
              key={approval.id}
              className="rounded-lg border border-line bg-panel p-4 shadow-sm"
              data-testid={`approval-item-${approval.id}`}
            >
              <div className="flex items-start justify-between gap-4">
                <div className="min-w-0">
                  <p className="text-sm font-semibold">
                    {formatApprovalActionClass(approval.action_class)}
                  </p>
                  <p className="mt-1 break-all text-sm text-muted">{approval.resource_ref}</p>
                  <p className="mt-1 break-all font-mono text-xs text-muted">
                    申請者: {approval.requested_by_actor_id}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <span className="rounded-md bg-panel-muted px-2 py-1 text-xs font-semibold text-muted">
                    {formatApprovalStatus(approval.status)}
                  </span>
                  <span
                    className={`rounded-md px-2 py-1 text-xs font-semibold ${riskBadgeClass(
                      approval.risk_level
                    )}`}
                  >
                    {formatRiskLevel(approval.risk_level)}
                  </span>
                  <Link
                    href={`/approvals/${approval.id}`}
                    className="text-sm font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                    data-testid={`approval-link-${approval.id}`}
                  >
                    レビュー
                  </Link>
                </div>
              </div>
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}

function riskBadgeClass(risk: string): string {
  switch (risk) {
    case "critical":
      return "bg-rose-100 text-rose-800";
    case "high":
      return "bg-orange-100 text-orange-800";
    case "medium":
      return "bg-yellow-100 text-yellow-800";
    case "low":
      return "bg-emerald-100 text-emerald-800";
    default:
      return "bg-slate-100 text-slate-800";
  }
}
