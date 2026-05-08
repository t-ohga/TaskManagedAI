import Link from "next/link";

import { getApprovalDetail, type ApprovalDetail } from "@/lib/api/approvals";

import { ApprovalDecideForm } from "./_components/approval-decide-form";

export const dynamic = "force-dynamic";

type ApprovalDetailPageProps = {
  params: Promise<{
    id: string;
  }>;
};

export default async function ApprovalDetailPage({ params }: ApprovalDetailPageProps) {
  const { id } = await params;

  let approval: ApprovalDetail;
  try {
    approval = await getApprovalDetail(id);
  } catch (error: unknown) {
    return (
      <section aria-label="Approval detail" className="grid gap-4">
        <Link className="text-sm font-semibold text-accent hover:underline" href="/approvals">
          Back to approvals
        </Link>
        <h1 className="text-2xl font-semibold">Approval detail</h1>
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
          Failed to load approval: {error instanceof Error ? error.message : "unknown error"}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="Approval detail" className="grid gap-5">
      <header className="grid gap-2">
        <Link className="text-sm font-semibold text-accent hover:underline" href="/approvals">
          Back to approvals
        </Link>
        <p className="text-sm font-medium text-accent">Approval Inbox</p>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-3xl font-semibold tracking-normal">{approval.action_class}</h1>
            <p className="mt-2 break-all text-sm text-muted">{approval.resource_ref}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className={`rounded-md px-2 py-1 text-xs font-semibold ${statusClass(approval.status)}`}>
              {approval.status}
            </span>
            <span className={`rounded-md px-2 py-1 text-xs font-semibold ${riskClass(approval.risk_level)}`}>
              {approval.risk_level}
            </span>
          </div>
        </div>
      </header>

      <StatusNotice approval={approval} />

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
          <h2 className="text-base font-semibold">Request evidence</h2>
          <dl className="mt-4 grid gap-3 text-sm">
            <DetailRow label="Requested by" value={approval.requested_by_actor_id} mono />
            <DetailRow label="Requested at" value={formatDateTime(approval.requested_at)} />
            <DetailRow label="Policy version" value={approval.policy_version} mono />
            <DetailRow label="Policy pack lock" value={approval.policy_pack_lock ?? "not locked"} mono />
            <DetailRow label="Artifact hash" value={approval.artifact_hash ?? "not provided"} mono />
            <DetailRow label="Diff hash" value={approval.diff_hash ?? "not provided"} mono />
            <DetailRow
              label="Provider fingerprint"
              value={approval.provider_request_fingerprint ?? "not provided"}
              mono
            />
          </dl>
        </article>

        <aside className="grid gap-4">
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="text-base font-semibold">Decision</h2>
            <dl className="mt-4 grid gap-3 text-sm">
              <DetailRow
                label="Decided by"
                value={approval.decided_by_actor_id ?? "not decided"}
                mono={approval.decided_by_actor_id !== null}
              />
              <DetailRow
                label="Decided at"
                value={approval.decided_at ? formatDateTime(approval.decided_at) : "not decided"}
              />
              <DetailRow label="Rationale" value={approval.rationale ?? "not provided"} />
            </dl>
          </article>

          {approval.status === "pending" ? (
            <ApprovalDecideForm approvalId={approval.id} initialStatus={approval.status} />
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function DetailRow({
  label,
  value,
  mono = false
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="border-t border-line pt-3">
      <dt className="text-muted">{label}</dt>
      <dd className={`mt-1 break-all ${mono ? "font-mono text-xs" : ""}`}>{value}</dd>
    </div>
  );
}

function StatusNotice({ approval }: { approval: ApprovalDetail }) {
  if (approval.status === "invalidated") {
    return (
      <p className="rounded-md bg-amber-50 p-3 text-sm text-attention">
        This approval was invalidated by a stale artifact, diff, policy, or provider fingerprint.
      </p>
    );
  }

  if (approval.status === "expired") {
    return (
      <p className="rounded-md bg-slate-100 p-3 text-sm text-muted">
        This approval expired and must be requested again before resume.
      </p>
    );
  }

  if (approval.status === "rejected") {
    return (
      <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
        This approval was rejected. Resume is blocked.
      </p>
    );
  }

  if (approval.status === "approved") {
    return (
      <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
        This approval was approved. Downstream execution must still pass policy.
      </p>
    );
  }

  return (
    <p className="rounded-md bg-teal-50 p-3 text-sm text-accent">
      This approval is pending independent reviewer decision.
    </p>
  );
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en", {
    dateStyle: "medium",
    timeStyle: "short"
  }).format(new Date(value));
}

function riskClass(risk: string): string {
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

function statusClass(status: string): string {
  switch (status) {
    case "pending":
      return "bg-teal-50 text-accent";
    case "approved":
      return "bg-emerald-100 text-emerald-800";
    case "rejected":
      return "bg-rose-100 text-rose-800";
    case "invalidated":
      return "bg-amber-100 text-attention";
    case "expired":
      return "bg-slate-200 text-slate-700";
    default:
      return "bg-slate-100 text-slate-800";
  }
}

