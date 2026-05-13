/**
 * Sprint 9 BL-0104: Ticket 詳細 (P0 UI skeleton)。
 *
 * Acceptance Criteria + Evidence + AgentRun mapping + ContextSnapshot 10
 * column を表示。AI 生成案は採用前 (waiting_approval) でも表示するが、
 * trusted_instruction への昇格は approval flow で別経路。
 */

import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

interface TicketDetailPageProps {
  params: Promise<{ id: string }>;
}

export default async function TicketDetailPage({ params }: TicketDetailPageProps) {
  const { id } = await params;

  if (!id) {
    notFound();
  }

  return (
    <section aria-label="Ticket detail" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin / Ticket</p>
        <h1 className="text-3xl font-semibold tracking-normal">Ticket {id}</h1>
        <p className="mt-2 text-sm text-muted">
          Sprint 9 BL-0104 skeleton — Ticket 詳細 (Acceptance Criteria +
          Evidence + AgentRun mapping + ContextSnapshot 10 column 表示)。
        </p>
      </header>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Acceptance Criteria</h2>
        <p className="mt-2 text-sm text-muted">
          AC list (numbered) + EvalResult mapping (Sprint 11 eval_harness 連動)
        </p>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Evidence / Claim / Citation</h2>
        <p className="mt-2 text-sm text-muted">
          claim_id / source_id / URL / PROV bundle hash (evidence_set_hash で
          ContextSnapshot に固定、AC-KPI-04 citation_coverage 計測元)
        </p>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">AgentRun Mapping (server-owned)</h2>
        <p className="mt-2 text-sm text-muted">
          Ticket と AgentRun は project 境界内で 1:N。AgentRun status 16 状態 +
          blocked_reason 3 種 を分離表示。
        </p>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">ContextSnapshot 10 column</h2>
        <ul className="mt-2 grid grid-cols-2 gap-1 text-xs text-muted md:grid-cols-3">
          {[
            "prompt_pack_version",
            "prompt_pack_lock",
            "policy_version",
            "policy_pack_lock",
            "repo_state",
            "tool_manifest",
            "evidence_set_hash",
            "provider_continuation_ref",
            "provider_request_fingerprint",
            "snapshot_kind"
          ].map((col) => (
            <li key={col} className="rounded bg-muted/10 px-2 py-1">
              <code className="text-xs">{col}</code>
            </li>
          ))}
        </ul>
      </article>
    </section>
  );
}
