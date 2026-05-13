/**
 * Sprint 9 BL-0107: Audit Log (P0 UI skeleton)。
 *
 * append-only event を表示。raw secret / raw token / raw provider response
 * を含めず、reason_code / hash / pattern hit 種別 / actor_id / run_id /
 * trace_id / correlation_id のみ表示する (AC-HARD-02 invariant)。
 */

export const dynamic = "force-dynamic";

const AUDIT_EVENT_TYPES = [
  "policy_decision_created",
  "approval_requested",
  "approval_decided",
  "provider_blocked",
  "secret_capability_issued",
  "secret_capability_redeemed",
  "secret_capability_denied",
  "secret_canary_detected",
  "runner_started",
  "runner_completed",
  "runner_blocked",
  "repo_pr_opened",
  "webhook_hmac_failed",
  "orchestrator_failover"
] as const;

export default function AuditLogPage() {
  return (
    <section aria-label="Audit Log" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Audit Log</h1>
        <p className="mt-2 text-sm text-muted">
          Sprint 9 BL-0107 skeleton — append-only audit event 表示。raw secret /
          raw token は含めない (AC-HARD-02 invariant)。
        </p>
      </header>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">audit_event types (P0 主要)</h2>
        <ul className="mt-2 grid grid-cols-1 gap-1 text-sm text-muted md:grid-cols-2">
          {AUDIT_EVENT_TYPES.map((event) => (
            <li key={event} className="rounded bg-muted/10 px-2 py-1">
              <code className="text-xs">{event}</code>
            </li>
          ))}
        </ul>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">必須 payload key (raw secret なし)</h2>
        <p className="mt-2 text-sm text-muted">
          event_type / actor_id / run_id / tenant_id / project_id / trace_id /
          correlation_id / reason_code / payload_data_class /
          allowed_data_class / provider_compliance_matrix_version /
          policy_version / provider_request_fingerprint_hash / timestamp。
        </p>
      </article>
    </section>
  );
}
