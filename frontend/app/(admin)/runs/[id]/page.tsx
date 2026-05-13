/**
 * Sprint 9 BL-0106 (詳細): Agent Run 詳細 (P0 UI skeleton)。
 *
 * AgentRunEvent timeline 表示。runner_started / runner_completed /
 * runner_blocked (Sprint 7 で予約済 event_type) を含む 22 種 event の
 * append-only sequence を視覚化。
 */

import { notFound } from "next/navigation";

export const dynamic = "force-dynamic";

interface AgentRunDetailPageProps {
  params: Promise<{ id: string }>;
}

const SAMPLE_EVENT_TIMELINE = [
  { type: "run_queued", at: "2026-05-13T03:00:00Z" },
  { type: "context_gathered", at: "2026-05-13T03:00:02Z" },
  { type: "provider_requested", at: "2026-05-13T03:00:03Z" },
  { type: "provider_responded", at: "2026-05-13T03:00:10Z" },
  { type: "artifact_generated", at: "2026-05-13T03:00:11Z" },
  { type: "schema_validated", at: "2026-05-13T03:00:12Z" },
  { type: "policy_linted", at: "2026-05-13T03:00:12Z" },
  { type: "diff_ready", at: "2026-05-13T03:00:13Z" },
  { type: "approval_requested", at: "2026-05-13T03:00:13Z" },
  { type: "runner_started", at: "2026-05-13T03:05:00Z" },
  { type: "runner_completed", at: "2026-05-13T03:05:30Z" },
  { type: "repo_pr_opened", at: "2026-05-13T03:05:32Z" },
  { type: "run_completed", at: "2026-05-13T03:05:33Z" }
] as const;

export default async function AgentRunDetailPage({
  params
}: AgentRunDetailPageProps) {
  const { id } = await params;

  if (!id) {
    notFound();
  }

  return (
    <section aria-label="Agent Run detail" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin / AgentRun</p>
        <h1 className="text-3xl font-semibold tracking-normal">
          AgentRun {id}
        </h1>
        <p className="mt-2 text-sm text-muted">
          Sprint 9 BL-0106 skeleton — AgentRunEvent timeline (append-only) +
          ContextSnapshot kind transition + Sprint 7 runner_* event 表示。
        </p>
      </header>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Event Timeline (skeleton sample)</h2>
        <ol className="mt-2 space-y-1 text-sm text-muted">
          {SAMPLE_EVENT_TIMELINE.map((event, idx) => (
            <li
              key={event.type}
              className="flex items-center justify-between rounded bg-muted/10 px-2 py-1"
            >
              <span className="text-xs">
                <span className="mr-2 inline-block w-6 text-right text-muted">
                  {String(idx + 1).padStart(2, "0")}
                </span>
                <code>{event.type}</code>
              </span>
              <span className="text-xs text-muted">{event.at}</span>
            </li>
          ))}
        </ol>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Sprint 7 runner_* event 統合</h2>
        <p className="mt-2 text-sm text-muted">
          runner_started: workspace_id / argv_basename / argv_hash (raw argv なし)
          <br />
          runner_completed: exit_code / stdout_bytes / stderr_bytes /
          output_cap_exceeded / scrubbed_env_keys
          <br />
          runner_blocked: deny_category (dangerous_command / forbidden_path /
          resource_cap / network_egress) + reason_code (raw 値なし)
        </p>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">No raw secret invariant (AC-HARD-02)</h2>
        <p className="mt-2 text-sm text-muted">
          AgentRunEvent payload に raw secret / raw token / raw provider response
          を含めない。secret 系の audit は key 名のみ (scrubbed_env_keys)。
        </p>
      </article>
    </section>
  );
}
