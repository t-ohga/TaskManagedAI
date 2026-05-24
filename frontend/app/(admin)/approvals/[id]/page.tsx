import Link from "next/link";

import { getApprovalDetail, type ApprovalDetail } from "@/lib/api/approvals";
import {
  formatApprovalActionClass,
  formatApprovalStatus,
  formatRiskLevel
} from "@/lib/i18n/approval-labels";

import { ApprovalDecideForm } from "./_components/approval-decide-form";
import { ApprovalRevisionRequestForm } from "./_components/approval-revision-request-form";

export const dynamic = "force-dynamic";

const SHA256_HEX_PATTERN = /^[0-9a-f]{64}$/;

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
      <section aria-label="承認詳細" className="grid gap-4">
        <Link className="text-sm font-semibold text-accent hover:underline" href="/approvals">
          承認一覧へ戻る
        </Link>
        <h1 className="text-2xl font-semibold">承認詳細</h1>
        <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
          承認詳細の取得に失敗しました: {error instanceof Error ? error.message : "不明なエラー"}
        </p>
      </section>
    );
  }

  return (
    <section aria-label="承認詳細" className="grid gap-5">
      <header className="grid gap-2">
        <Link className="text-sm font-semibold text-accent hover:underline" href="/approvals">
          承認一覧へ戻る
        </Link>
        <p className="text-sm font-medium text-accent">承認待ち</p>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h1 className="text-3xl font-semibold tracking-normal">
              {formatApprovalActionClass(approval.action_class)}
            </h1>
            <p className="mt-2 break-all text-sm text-muted">{approval.resource_ref}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <span className={`rounded-md px-2 py-1 text-xs font-semibold ${statusClass(approval.status)}`}>
              {formatApprovalStatus(approval.status)}
            </span>
            <span className={`rounded-md px-2 py-1 text-xs font-semibold ${riskClass(approval.risk_level)}`}>
              {formatRiskLevel(approval.risk_level)}
            </span>
          </div>
        </div>
      </header>

      <StatusNotice approval={approval} />

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <DecisionPacketPanel approval={approval} />

        <aside className="grid gap-4">
          <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
            <h2 className="text-base font-semibold">判定</h2>
            <dl className="mt-4 grid gap-3 text-sm">
              <DetailRow
                label="判定者"
                value={approval.decided_by_actor_id ?? "(未決定)"}
                mono={approval.decided_by_actor_id !== null}
              />
              <DetailRow
                label="判定日時"
                value={approval.decided_at ? formatDateTime(approval.decided_at) : "(未決定)"}
              />
              <DetailRow label="理由" value={approval.rationale ?? "(未提供)"} />
            </dl>
          </article>

          {approval.status === "pending" ? (
            <>
              <ApprovalDecideForm approvalId={approval.id} initialStatus={approval.status} />
              <ApprovalRevisionRequestForm approvalId={approval.id} initialStatus={approval.status} />
            </>
          ) : null}
        </aside>
      </div>
    </section>
  );
}

function DecisionPacketPanel({ approval }: { approval: ApprovalDetail }) {
  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <h2 className="text-base font-semibold">Decision packet</h2>
      <p className="mt-1 text-sm text-muted">
        Hash と policy snapshot のみを表示します。payload / provider request の raw value は表示しません。
      </p>
      <dl className="mt-4 grid gap-3 text-sm">
        <DetailRow label="申請者" value={approval.requested_by_actor_id} mono />
        <DetailRow label="申請日時" value={formatDateTime(approval.requested_at)} />
        <DetailRow label="policy_version" value={approval.policy_version} mono />
        <DetailRow
          label="policy_pack_lock"
          value={formatSha256Value(approval.policy_pack_lock, "(未ロック)")}
          mono
        />
        <DetailRow label="artifact_hash" value={formatSha256Value(approval.artifact_hash)} mono />
        <DetailRow label="diff_hash" value={formatSha256Value(approval.diff_hash)} mono />
        <DetailRow
          label="provider_request_fingerprint"
          value={formatSha256Value(approval.provider_request_fingerprint)}
          mono
        />
        <DetailRow
          label="stale_after_event_seq"
          value={approval.stale_after_event_seq === null ? "(未設定)" : String(approval.stale_after_event_seq)}
          mono={approval.stale_after_event_seq !== null}
        />
      </dl>
    </article>
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

function formatSha256Value(value: string | null, emptyValue = "(未提供)"): string {
  if (value === null || value.trim() === "") {
    return emptyValue;
  }
  if (!SHA256_HEX_PATTERN.test(value)) {
    return "(非 SHA-256 形式のため非表示)";
  }
  return value;
}

function StatusNotice({ approval }: { approval: ApprovalDetail }) {
  if (approval.status === "invalidated") {
    return (
      <p className="rounded-md bg-amber-50 p-3 text-sm text-attention">
        この承認は古い artifact、diff、policy、または provider fingerprint により無効化されています。
      </p>
    );
  }

  if (approval.status === "expired") {
    return (
      <p className="rounded-md bg-slate-100 p-3 text-sm text-muted">
        この承認は期限切れです。再開前に再申請が必要です。
      </p>
    );
  }

  if (approval.status === "rejected") {
    return (
      <p className="rounded-md bg-rose-50 p-3 text-sm text-rose-700">
        この承認は却下されました。再開はブロックされています。
      </p>
    );
  }

  if (approval.status === "approved") {
    return (
      <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
        この承認は承認済みです。後続実行は引き続き policy を通過する必要があります。
      </p>
    );
  }

  return (
    <p className="rounded-md bg-teal-50 p-3 text-sm text-accent">
      この項目は独立レビュアーの判定待ちです。
    </p>
  );
}

function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("ja-JP", {
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
