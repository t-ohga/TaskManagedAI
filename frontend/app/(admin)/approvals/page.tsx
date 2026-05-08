import Link from "next/link";

import { listPendingApprovals } from "@/lib/api/approvals";

export const dynamic = "force-dynamic";

export default async function ApprovalInboxPage() {
  let approvals;
  try {
    approvals = await listPendingApprovals();
  } catch (error: unknown) {
    return (
      <section aria-label="Approval Inbox" className="grid gap-4">
        <h1 className="text-2xl font-semibold">Approval Inbox</h1>
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
          Failed to load approvals: {error instanceof Error ? error.message : "unknown error"}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Approval Inbox" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Approval Inbox</h1>
        <p className="mt-2 text-sm text-muted">Pending approvals require reviewer decision.</p>
      </header>

      {approvals.length === 0 ? (
        <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
          No pending approvals.
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
                  <p className="text-sm font-semibold">{approval.action_class}</p>
                  <p className="mt-1 break-all text-sm text-muted">{approval.resource_ref}</p>
                  <p className="mt-1 break-all font-mono text-xs text-muted">
                    requested by {approval.requested_by_actor_id}
                  </p>
                </div>
                <div className="flex shrink-0 flex-col items-end gap-2">
                  <span
                    className={`rounded-md px-2 py-1 text-xs font-semibold ${riskBadgeClass(
                      approval.risk_level
                    )}`}
                  >
                    {approval.risk_level}
                  </span>
                  <Link
                    href={`/approvals/${approval.id}`}
                    className="text-sm font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                    data-testid={`approval-link-${approval.id}`}
                  >
                    Review
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

