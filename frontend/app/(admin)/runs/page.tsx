/**
 * Sprint 9 BL-0106: Agent Runs timeline (P0 UI skeleton)。
 *
 * AgentRun 16 状態 + blocked_reason 3 種 を status と分離表示。
 * ContextSnapshot 10 column + AgentRunEvent timeline (Sprint 7 で
 * runner_started / runner_completed / runner_blocked event 予約済) を
 * 表示する。
 */

export const dynamic = "force-dynamic";

const AGENT_RUN_STATES_16 = [
  "queued",
  "gathering_context",
  "running",
  "generated_artifact",
  "schema_validated",
  "policy_linted",
  "diff_ready",
  "waiting_approval",
  "blocked",
  "provider_refused",
  "provider_incomplete",
  "validation_failed",
  "repair_exhausted",
  "completed",
  "failed",
  "cancelled"
] as const;

const BLOCKED_REASONS_3 = ["policy_blocked", "budget_blocked", "runtime_blocked"] as const;

export default function AgentRunsPage() {
  return (
    <section aria-label="Agent Runs" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Agent Runs</h1>
        <p className="mt-2 text-sm text-muted">
          Sprint 9 BL-0106 skeleton — AgentRun 16 状態 + blocked_reason 3 種 +
          AgentRunEvent timeline 表示。
        </p>
      </header>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">AgentRun 16 状態 (P0 contract)</h2>
        <ul className="mt-2 grid grid-cols-2 gap-1 text-sm text-muted md:grid-cols-3">
          {AGENT_RUN_STATES_16.map((state) => (
            <li key={state} className="rounded bg-muted/10 px-2 py-1">
              <code className="text-xs">{state}</code>
            </li>
          ))}
        </ul>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">blocked_reason (3 種)</h2>
        <p className="mt-2 text-sm text-muted">
          status=blocked のときのみ表示、status enum と混同しない。
        </p>
        <ul className="mt-2 flex gap-2 text-sm">
          {BLOCKED_REASONS_3.map((reason) => (
            <li key={reason} className="rounded bg-orange-50 px-2 py-1 text-orange-700">
              <code className="text-xs">{reason}</code>
            </li>
          ))}
        </ul>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">terminal state (5 種)</h2>
        <p className="mt-2 text-sm text-muted">
          completed / failed / cancelled / provider_refused / repair_exhausted。
          provider_incomplete / blocked は retry / resume 可、terminal ではない。
        </p>
      </article>
    </section>
  );
}
