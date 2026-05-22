import Link from "next/link";
import { notFound } from "next/navigation";

import { BackendApiError } from "@/lib/api/client";
import { getAgentRun, type AgentRunDetail } from "@/lib/api/agent-runs";

import { UUID_V1_TO_V5_PATTERN } from "../../_lib/route-id";

export const dynamic = "force-dynamic";

type AgentRunDetailPageProps = {
  params: Promise<{ id: string }>;
};

type DetailState =
  | { kind: "ok"; run: AgentRunDetail }
  | { kind: "not-found" }
  | { kind: "error"; message: string };

async function readRun(id: string): Promise<DetailState> {
  try {
    const run = await getAgentRun(id);
    return { kind: "ok", run };
  } catch (error: unknown) {
    if (error instanceof BackendApiError && error.status === 404) {
      return { kind: "not-found" };
    }
    if (error instanceof BackendApiError) {
      return {
        kind: "error",
        message: `バックエンドが ${error.status} を返しました: ${error.message}`
      };
    }
    const message =
      error instanceof Error ? error.message : "AI 実行詳細の取得に失敗しました。";
    return { kind: "error", message };
  }
}

export default async function AgentRunDetailPage({ params }: AgentRunDetailPageProps) {
  const { id } = await params;

  if (!id || !UUID_V1_TO_V5_PATTERN.test(id)) {
    notFound();
  }

  const state = await readRun(id);
  if (state.kind === "not-found") {
    notFound();
  }

  return (
    <section aria-label="AI 実行詳細" className="grid gap-5">
      <header className="grid gap-2">
        <Link className="text-sm font-semibold text-accent hover:underline" href="/runs">
          AI 実行一覧へ戻る
        </Link>
        <p className="text-sm font-medium text-accent">管理 / AI 実行</p>
        <h1 className="text-3xl font-semibold tracking-normal">AI 実行詳細</h1>
        <p className="break-all font-mono text-xs text-muted">{id}</p>
      </header>

      {state.kind === "error" ? (
        <article role="status" className="rounded-md border border-attention bg-amber-50 p-4">
          <h2 className="text-base font-semibold text-attention">AI 実行を表示できません</h2>
          <p className="mt-1 text-sm text-muted">{state.message}</p>
        </article>
      ) : (
        <>
          <RunSummary run={state.run} />
          <RunEvents run={state.run} />
          <ContextSnapshotPanel run={state.run} />
        </>
      )}
    </section>
  );
}

function RunSummary({ run }: { run: AgentRunDetail }) {
  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">実行状態</h2>
          <p className="mt-1 text-sm text-muted">
            status と blocked_reason は別 dimension として表示しています。
          </p>
        </div>
        <span className={`rounded-md px-2 py-1 text-xs font-semibold ${statusClass(run.status)}`}>
          {formatToken(run.status)}
        </span>
      </div>
      <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
        <DetailRow label="project_id" value={run.project_id} mono />
        <DetailRow label="parent_run_id" value={run.parent_run_id ?? "—"} mono />
        <DetailRow label="blocked_reason" value={run.blocked_reason ?? "—"} mono />
        <DetailRow label="role" value={run.role_id ? `${run.role_scope}:${run.role_id}` : "未設定"} />
        <DetailRow label="progress_seq" value={String(run.progress_seq)} mono />
        <DetailRow
          label="last_progress_at"
          value={run.last_progress_at ? formatDate(run.last_progress_at) : "—"}
          mono
        />
        <DetailRow
          label="orchestrator_lease_expires_at"
          value={run.orchestrator_lease_expires_at ? formatDate(run.orchestrator_lease_expires_at) : "—"}
          mono
        />
        <DetailRow label="updated_at" value={formatDate(run.updated_at)} mono />
        <DetailRow label="error_code" value={run.error_code ?? "—"} mono />
        <DetailRow label="error_summary" value={run.error_summary ?? "—"} />
      </dl>
    </article>
  );
}

function RunEvents({ run }: { run: AgentRunDetail }) {
  return (
    <article className="overflow-x-auto rounded-lg border border-line bg-panel shadow-sm">
      <div className="border-b border-line p-5">
        <h2 className="text-lg font-semibold">AgentRunEvent タイムライン</h2>
        <p className="mt-1 text-sm text-muted">
          payload は raw JSON ではなく key 名だけを表示します。
        </p>
      </div>
      {run.events.length === 0 ? (
        <p className="p-5 text-sm text-muted">event はまだありません。</p>
      ) : (
        <table className="min-w-full divide-y divide-line text-sm">
          <thead className="bg-panel-muted text-xs uppercase tracking-wide text-muted">
            <tr>
              <th scope="col" className="px-4 py-3 text-left font-medium">seq</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">event_type</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">payload_keys</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">redaction</th>
              <th scope="col" className="px-4 py-3 text-left font-medium">created_at</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-line">
            {run.events.map((event) => (
              <tr key={event.id} className="align-top hover:bg-panel-muted">
                <td className="px-4 py-3 font-mono text-xs">{event.seq_no}</td>
                <td className="px-4 py-3 font-mono text-xs">{event.event_type}</td>
                <td className="px-4 py-3 text-xs text-muted">
                  {event.payload_keys.length > 0 ? event.payload_keys.join(", ") : "—"}
                </td>
                <td className="px-4 py-3 text-xs text-muted">
                  {event.payload_redaction_status}
                </td>
                <td className="whitespace-nowrap px-4 py-3 font-mono text-xs text-muted">
                  {formatDate(event.created_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </article>
  );
}

function ContextSnapshotPanel({ run }: { run: AgentRunDetail }) {
  const snapshot = run.context_snapshot;
  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <h2 className="text-lg font-semibold">ContextSnapshot 10 カラム</h2>
      <p className="mt-1 text-sm text-muted">
        repo_state / tool_manifest / provider fingerprint は key 名のみ表示します。
      </p>
      {snapshot === null ? (
        <p className="mt-4 text-sm text-muted">ContextSnapshot はまだありません。</p>
      ) : (
        <dl className="mt-4 grid gap-3 text-sm md:grid-cols-2">
          <DetailRow label="snapshot_kind" value={snapshot.snapshot_kind} mono />
          <DetailRow label="prompt_pack_version" value={snapshot.prompt_pack_version} mono />
          <DetailRow label="prompt_pack_lock" value={snapshot.prompt_pack_lock} mono />
          <DetailRow label="policy_version" value={snapshot.policy_version} mono />
          <DetailRow label="policy_pack_lock" value={snapshot.policy_pack_lock} mono />
          <DetailRow label="evidence_set_hash" value={snapshot.evidence_set_hash} mono />
          <DetailRow
            label="repo_state keys"
            value={snapshot.repo_state_keys.length > 0 ? snapshot.repo_state_keys.join(", ") : "—"}
          />
          <DetailRow
            label="tool_manifest keys"
            value={snapshot.tool_manifest_keys.length > 0 ? snapshot.tool_manifest_keys.join(", ") : "—"}
          />
          <DetailRow
            label="provider_continuation_ref"
            value={snapshot.has_provider_continuation_ref ? "あり" : "なし"}
          />
          <DetailRow
            label="provider_request_fingerprint keys"
            value={
              snapshot.provider_request_fingerprint_keys.length > 0
                ? snapshot.provider_request_fingerprint_keys.join(", ")
                : "—"
            }
          />
        </dl>
      )}
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

function formatDate(iso: string): string {
  try {
    return new Date(iso).toISOString().slice(0, 16).replace("T", " ");
  } catch {
    return iso;
  }
}

function formatToken(value: string): string {
  return value.replaceAll("_", " ");
}

function statusClass(status: string): string {
  switch (status) {
    case "blocked":
    case "failed":
    case "provider_refused":
    case "repair_exhausted":
      return "bg-rose-100 text-rose-800";
    case "waiting_approval":
    case "provider_incomplete":
      return "bg-amber-100 text-attention";
    case "completed":
      return "bg-emerald-100 text-emerald-800";
    case "running":
    case "gathering_context":
      return "bg-teal-50 text-accent";
    default:
      return "bg-slate-100 text-slate-800";
  }
}
