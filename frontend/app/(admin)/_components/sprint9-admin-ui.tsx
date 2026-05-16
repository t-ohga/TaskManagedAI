import "server-only";

import Link from "next/link";
import type { ReactNode } from "react";

// AdminPageShell / Panel render description content inside <p>. Restricting
// the type to ReactNode|string at the call sites and rendering inside <div>
// here would also work, but for now we use <div> wrappers to keep HTML valid
// when callers pass mixed inline + block content (F-P2R1-012 fix).
type AdminPageShellProps = {
  regionLabel: string;
  eyebrow: string;
  title: string;
  description: ReactNode;
  children: ReactNode;
};

type PanelProps = {
  titleId: string;
  title: string;
  description?: ReactNode;
  aside?: ReactNode;
  children: ReactNode;
};

type KeyboardNavItem = {
  label: string;
  href: string;
  keys: readonly string[];
};

export const AGENT_RUN_STATES_16 = [
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

export const BLOCKED_REASONS_3 = [
  "policy_blocked",
  "budget_blocked",
  "runtime_blocked"
] as const;

type AgentRunState = (typeof AGENT_RUN_STATES_16)[number];
type BlockedReason = (typeof BLOCKED_REASONS_3)[number];

const TERMINAL_STATES: readonly AgentRunState[] = [
  "provider_refused",
  "repair_exhausted",
  "completed",
  "failed",
  "cancelled"
];

const STANDARD_TRANSITION_PATH: readonly AgentRunState[] = [
  "queued",
  "gathering_context",
  "running",
  "generated_artifact",
  "schema_validated",
  "policy_linted",
  "diff_ready",
  "waiting_approval",
  "running",
  "completed"
];

// AgentRun state machine exception transitions, mirrored from
// .claude/rules/agentrun-state-machine.md §4 (cancel / resume / failure paths).
// Keep this list aligned with the rules document so that operators can rely on
// the UI as a complete representation of exception flows (F-P2R1-002 fix).
const EXCEPTION_TRANSITIONS = [
  { from: "running", to: "provider_refused", reason: "provider refusal" },
  { from: "running", to: "provider_incomplete", reason: "retryable incomplete" },
  { from: "running", to: "blocked", reason: "policy / budget / runtime deny" },
  { from: "running", to: "failed", reason: "unrecoverable failure" },
  { from: "running", to: "cancelled", reason: "human cancellation during running" },
  { from: "waiting_approval", to: "cancelled", reason: "human cancellation" },
  { from: "blocked", to: "cancelled", reason: "human cancellation while blocked" },
  { from: "provider_incomplete", to: "cancelled", reason: "human cancellation while incomplete" },
  { from: "generated_artifact", to: "validation_failed", reason: "schema mismatch" },
  { from: "validation_failed", to: "running", reason: "repair retry attempt" },
  { from: "validation_failed", to: "repair_exhausted", reason: "retry limit reached" },
  { from: "policy_linted", to: "blocked", reason: "policy / data class deny" },
  { from: "diff_ready", to: "blocked", reason: "runtime / runner deny" },
  { from: "waiting_approval", to: "blocked", reason: "stale approval invalidated" },
  { from: "blocked", to: "waiting_approval", reason: "resume requires re-approval" },
  { from: "blocked", to: "running", reason: "resume after cause resolved" },
  { from: "blocked", to: "failed", reason: "unresolvable blocker" },
  { from: "provider_incomplete", to: "running", reason: "continuation succeeded" },
  { from: "provider_incomplete", to: "failed", reason: "continuation unavailable" }
] as const satisfies readonly {
  from: AgentRunState;
  to: AgentRunState;
  reason: string;
}[];

const AGENT_RUN_STATE_DESCRIPTIONS: Record<AgentRunState, string> = {
  queued: "Run accepted and waiting for server-owned context resolution.",
  gathering_context: "ContextSnapshot metadata is assembled without raw secrets.",
  running: "Provider or runner work is in progress behind policy gates.",
  generated_artifact: "Structured artifact exists, still untrusted until checks pass.",
  schema_validated: "Output schema validation passed for the generated artifact.",
  policy_linted: "Policy lint completed before diff or runner actions.",
  diff_ready: "Patch is prepared for approval and runner-safe execution.",
  waiting_approval: "Human approval is required; self-approval stays prohibited.",
  blocked: "Single blocked status; reason is one of the three blocked_reason values.",
  provider_refused: "Provider refusal terminal state.",
  provider_incomplete: "Retryable provider incomplete state, not terminal.",
  validation_failed: "Repairable validation failure state.",
  repair_exhausted: "Repair retry budget exhausted terminal state.",
  completed: "Successful terminal state.",
  failed: "Failure terminal state.",
  cancelled: "Cancellation terminal state."
};

const BLOCKED_REASON_DESCRIPTIONS: Record<BlockedReason, string> = {
  policy_blocked: "Policy or data-class preflight denied the transition.",
  budget_blocked: "Cost or quota hard limit stopped execution.",
  runtime_blocked: "Runner gateway denied command, path, resource, or egress."
};

// F-P3R1-003 fix: keep KEYBOARD_NAV_ITEMS as readonly + literal type so that
// `current` consumers cannot pass arbitrary strings (typo would silently lose
// aria-current).
const KEYBOARD_NAV_ITEMS = [
  { label: "Tickets", href: "/tickets", keys: ["g", "t"] },
  { label: "Research", href: "/research", keys: ["g", "e"] },
  { label: "Approval Inbox", href: "/approvals", keys: ["g", "i"] },
  { label: "Agent Runs", href: "/runs", keys: ["g", "r"] },
  { label: "Audit Log", href: "/audit", keys: ["g", "a"] },
  { label: "Project Settings", href: "/settings", keys: ["g", "s"] }
] as const satisfies readonly KeyboardNavItem[];

export type KeyboardNavLabel = (typeof KEYBOARD_NAV_ITEMS)[number]["label"];

const CONTEXT_SNAPSHOT_COLUMNS = [
  {
    key: "prompt_pack_version",
    purpose: "Prompt pack release identifier; displayed as schema metadata only."
  },
  {
    key: "prompt_pack_lock",
    purpose: "Immutable lock reference for the prompt pack, never editable from UI."
  },
  {
    key: "policy_version",
    purpose: "Policy version used for provider preflight and approval binding."
  },
  {
    key: "policy_pack_lock",
    purpose: "Policy pack lock reference used to prevent replay drift."
  },
  {
    key: "repo_state",
    purpose: "Repository state pointer; raw diff content is not expanded here."
  },
  {
    key: "tool_manifest",
    purpose: "Allowed tool manifest reference; caller-supplied tools are ignored."
  },
  {
    key: "evidence_set_hash",
    purpose: "Evidence set hash for citation coverage and claim traceability."
  },
  {
    key: "provider_continuation_ref",
    purpose: "Provider continuation reference pointer without provider raw payload."
  },
  {
    key: "provider_request_fingerprint",
    purpose: "Request fingerprint used for approval binding and audit correlation."
  },
  {
    key: "snapshot_kind",
    purpose: "Snapshot lifecycle kind; append-only and server-owned."
  }
] as const;

// TODO (P0.1+ F-P2R1-003): Replace this hardcoded snapshot with a TypeScript
// module generated from `config/provider_compliance.toml` so that the UI never
// drifts from the canonical Matrix (matrix_version, condition_status,
// region_or_data_transfer, plan_required, last_verified_at) need to be exposed.
// In P0 this skeleton intentionally limits the columns shown.
const PROVIDER_COMPLIANCE_ROWS = [
  {
    provider: "openai",
    api_or_feature: "responses",
    allowed_data_class: "confidential",
    retention: "0d",
    zdr_eligible: "yes",
    training_use: "no"
  },
  {
    provider: "anthropic",
    api_or_feature: "messages",
    allowed_data_class: "confidential",
    retention: "0d",
    zdr_eligible: "yes",
    training_use: "no"
  },
  {
    provider: "anthropic",
    api_or_feature: "batches",
    allowed_data_class: "internal",
    retention: "30d",
    zdr_eligible: "conditional",
    training_use: "no"
  },
  {
    provider: "gemini",
    api_or_feature: "generate_content",
    allowed_data_class: "public",
    retention: "unverified",
    zdr_eligible: "no",
    training_use: "unverified"
  },
  {
    provider: "mock",
    api_or_feature: "mock",
    allowed_data_class: "pii",
    retention: "0d",
    zdr_eligible: "yes",
    training_use: "no"
  }
] as const;

const POLICY_PROFILES = [
  {
    name: "minimal_safe",
    summary:
      "task_write / repo_write / pr_open require approval; secret_access and provider_call fail closed through SecretBroker and Provider Compliance Matrix; merge / deploy remain P0 deny (F-P2R1-004)."
  },
  {
    name: "approval_required",
    summary:
      "Human approval gates every privileged mutation; SecretBroker capability token, Provider Compliance preflight, and runner gateway still verify independently."
  },
  {
    name: "merge_deny",
    summary:
      "Merge and deploy stay denied in P0 even after approvals; RepoProxy Draft PR remains the only allowed write surface."
  }
] as const;

// TODO (P0.1+ F-P2R1-005): Replace this sample timeline with a canonical
// event catalog sourced from the backend AgentRunEvent enum (currently 28
// event types, expanding to 37 in P0.1 per ADR-00014/ADR-00018). The sample
// shown here is intentionally narrowed to the success path for the P0 UI
// skeleton.
// F-P3R1-005 fix: keep status typed as AgentRunState so typos cannot reach
// rendering. F-P3R1-004 fix: React key uses seqNo because event_type may
// repeat across retry / continuation in real timelines.
type AgentRunTimelineEvent = Readonly<{
  seqNo: number;
  event_type: string;
  status: AgentRunState;
  at: string;
  actor_id: string;
  summary: string;
}>;

const AGENT_RUN_EVENT_TIMELINE = [
  {
    seqNo: 1,
    event_type: "run_queued",
    status: "queued",
    at: "2026-05-13T03:00:00Z",
    actor_id: "system/orchestrator",
    summary: "AgentRun was created after session and project context resolution."
  },
  {
    seqNo: 2,
    event_type: "context_gathered",
    status: "gathering_context",
    at: "2026-05-13T03:00:02Z",
    actor_id: "system/context-resolver",
    summary: "ContextSnapshot 10-column metadata was fixed without raw values."
  },
  {
    seqNo: 3,
    event_type: "provider_requested",
    status: "running",
    at: "2026-05-13T03:00:03Z",
    actor_id: "system/provider-adapter",
    summary: "Provider request passed matrix preflight and fingerprint binding."
  },
  {
    seqNo: 4,
    event_type: "provider_responded",
    status: "running",
    at: "2026-05-13T03:00:10Z",
    actor_id: "system/provider-adapter",
    summary: "Provider response was accepted as candidate output, not trusted instruction."
  },
  {
    seqNo: 5,
    event_type: "artifact_generated",
    status: "generated_artifact",
    at: "2026-05-13T03:00:11Z",
    actor_id: "system/output-validator",
    summary: "Structured artifact was generated and queued for schema validation."
  },
  {
    seqNo: 6,
    event_type: "schema_validated",
    status: "schema_validated",
    at: "2026-05-13T03:00:12Z",
    actor_id: "system/output-validator",
    summary: "Schema validation passed."
  },
  {
    seqNo: 7,
    event_type: "policy_linted",
    status: "policy_linted",
    at: "2026-05-13T03:00:12Z",
    actor_id: "system/policy-engine",
    summary: "Policy lint passed with data-class terms kept separate."
  },
  {
    seqNo: 8,
    event_type: "diff_ready",
    status: "diff_ready",
    at: "2026-05-13T03:00:13Z",
    actor_id: "system/repo-proxy",
    summary: "Patch became reviewable; merge and deploy stay denied."
  },
  {
    seqNo: 9,
    event_type: "approval_requested",
    status: "waiting_approval",
    at: "2026-05-13T03:00:13Z",
    actor_id: "system/approval-gate",
    summary: "Approval request was bound to actor, artifact, policy, fingerprint, and action class."
  },
  {
    seqNo: 10,
    event_type: "runner_started",
    status: "running",
    at: "2026-05-13T03:05:00Z",
    actor_id: "system/runner-gateway",
    summary: "Runner started with argv hash and scrubbed environment metadata only."
  },
  {
    seqNo: 11,
    event_type: "runner_completed",
    status: "running",
    at: "2026-05-13T03:05:30Z",
    actor_id: "system/runner-gateway",
    summary: "Runner completed with exit code and byte counts."
  },
  {
    seqNo: 12,
    event_type: "repo_pr_opened",
    status: "running",
    at: "2026-05-13T03:05:32Z",
    actor_id: "system/repo-proxy",
    summary: "Draft PR was opened through RepoProxy."
  },
  {
    seqNo: 13,
    event_type: "run_completed",
    status: "completed",
    at: "2026-05-13T03:05:33Z",
    actor_id: "system/orchestrator",
    summary: "AgentRun reached completed terminal state."
  }
] as const satisfies readonly AgentRunTimelineEvent[];

export function AdminPageShell({
  regionLabel,
  eyebrow,
  title,
  description,
  children
}: AdminPageShellProps) {
  return (
    <section aria-label={regionLabel} className="grid gap-5">
      <header className="max-w-5xl">
        <p className="text-sm font-medium text-accent">{eyebrow}</p>
        <h1 className="text-3xl font-semibold tracking-normal text-ink">{title}</h1>
        <div className="mt-2 max-w-3xl text-sm leading-6 text-muted">{description}</div>
      </header>
      {children}
    </section>
  );
}

export function Panel({ titleId, title, description, aside, children }: PanelProps) {
  return (
    <section
      aria-labelledby={titleId}
      className="rounded-md border border-line bg-panel p-4 shadow-sm"
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-start md:justify-between">
        <div>
          <h2 id={titleId} className="text-lg font-semibold tracking-normal text-ink">
            {title}
          </h2>
          {description === undefined ? null : (
            <div className="mt-1 max-w-3xl text-sm leading-6 text-muted">{description}</div>
          )}
        </div>
        {aside === undefined ? null : <div className="shrink-0">{aside}</div>}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

export function KeyboardReadinessStrip({
  current
}: {
  readonly current: KeyboardNavLabel;
}) {
  return (
    <nav
      aria-label="Keyboard-ready admin navigation"
      className="rounded-md border border-line bg-slate-50 p-3"
    >
      <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <p className="text-sm font-medium text-ink">
          Admin navigation
        </p>
        <ul className="flex flex-wrap gap-2">
          {KEYBOARD_NAV_ITEMS.map((item) => (
            <li key={item.href}>
              <Link
                aria-current={item.label === current ? "page" : undefined}
                aria-label={`Go to ${item.label}`}
                className="inline-flex items-center gap-2 rounded-md border border-line bg-white px-3 py-2 text-xs font-semibold text-ink outline-offset-2 hover:border-accent hover:text-accent focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                href={item.href}
              >
                {/* P0.1+ shortcut hint (planned; no key handler attached yet, F-P2R1-013) */}
                <kbd aria-hidden="true" className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[11px] text-muted">
                  {item.keys.join(" ")}
                </kbd>
                <span>{item.label}</span>
              </Link>
            </li>
          ))}
        </ul>
      </div>
    </nav>
  );
}

export function CodePill({ children }: { children: ReactNode }) {
  return (
    <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-ink">
      {children}
    </code>
  );
}

export function AgentRunStateGraph() {
  return (
    <div className="grid gap-4">
      <div className="rounded-md border border-line bg-slate-50 p-3">
        <h3 className="text-sm font-semibold text-ink">
          Execution graph: 16 fixed states
        </h3>
        <ol
          aria-label="AgentRun 16 state execution graph"
          className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-4"
        >
          {AGENT_RUN_STATES_16.map((state, index) => (
            <li
              key={state}
              className={`rounded-md border p-3 shadow-sm ${stateToneClass(state)}`}
            >
              <div className="flex items-start justify-between gap-3">
                <code className="break-all font-mono text-xs font-semibold">{state}</code>
                <span className="rounded bg-white/70 px-1.5 py-0.5 font-mono text-[11px] text-muted">
                  {String(index + 1).padStart(2, "0")}
                </span>
              </div>
              <p className="mt-2 text-xs leading-5 text-muted">
                {AGENT_RUN_STATE_DESCRIPTIONS[state]}
              </p>
            </li>
          ))}
        </ol>
      </div>

      <div className="grid gap-3 lg:grid-cols-[minmax(0,1.25fr)_minmax(16rem,0.75fr)]">
        <section
          aria-labelledby="canonical-transition-path"
          className="rounded-md border border-line bg-white p-3"
        >
          <h3 id="canonical-transition-path" className="text-sm font-semibold text-ink">
            Canonical transition path
          </h3>
          <ol
            aria-label="Canonical state transition path"
            className="mt-3 flex flex-wrap items-center gap-2"
          >
            {STANDARD_TRANSITION_PATH.map((state, index) => (
              <li key={`${state}-${String(index)}`} className="flex items-center gap-2">
                <CodePill>{state}</CodePill>
                {index === STANDARD_TRANSITION_PATH.length - 1 ? null : (
                  <span aria-hidden="true" className="text-muted">
                    -&gt;
                  </span>
                )}
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="exception-transitions" className="rounded-md border border-line bg-white p-3">
          <h3 id="exception-transitions" className="text-sm font-semibold text-ink">
            Exception transitions
          </h3>
          <ul className="mt-3 grid gap-2">
            {EXCEPTION_TRANSITIONS.map((transition) => (
              <li key={`${transition.from}-${transition.to}`} className="text-xs leading-5 text-muted">
                <CodePill>{transition.from}</CodePill>
                <span aria-hidden="true" className="mx-1">
                  -&gt;
                </span>
                <CodePill>{transition.to}</CodePill>
                <span> {transition.reason}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}

export function BlockedReasonList() {
  return (
    <ul aria-label="blocked_reason fixed sub categories" className="grid gap-2 md:grid-cols-3">
      {BLOCKED_REASONS_3.map((reason) => (
        <li key={reason} className="rounded-md border border-amber-200 bg-amber-50 p-3">
          <code className="font-mono text-xs font-semibold text-attention">{reason}</code>
          <p className="mt-2 text-xs leading-5 text-muted">
            {BLOCKED_REASON_DESCRIPTIONS[reason]}
          </p>
        </li>
      ))}
    </ul>
  );
}

export function AgentRunEventTimeline() {
  return (
    <ol aria-label="Chronological AgentRunEvent timeline" className="grid gap-2">
      {AGENT_RUN_EVENT_TIMELINE.map((event) => (
        <li
          key={`${event.seqNo}-${event.event_type}`}
          className="grid gap-3 rounded-md border border-line bg-white p-3 md:grid-cols-[4rem_minmax(10rem,0.8fr)_minmax(0,1fr)] md:items-start"
        >
          <span className="font-mono text-xs font-semibold text-muted">
            #{String(event.seqNo).padStart(2, "0")}
          </span>
          <div>
            <code className="font-mono text-xs font-semibold text-ink">
              {event.event_type}
            </code>
            <p className="mt-1 text-xs text-muted">
              status: <CodePill>{event.status}</CodePill>
            </p>
          </div>
          <div className="text-xs leading-5 text-muted">
            <time dateTime={event.at}>{event.at}</time>
            <p className="mt-1">
              actor_id: <CodePill>{event.actor_id}</CodePill>
            </p>
            <p className="mt-1">{event.summary}</p>
          </div>
        </li>
      ))}
    </ol>
  );
}

export function ContextSnapshotDefinitionList() {
  return (
    <dl className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
      {CONTEXT_SNAPSHOT_COLUMNS.map((column) => (
        <div key={column.key} className="rounded-md border border-line bg-white p-3">
          <dt>
            <code className="break-all font-mono text-xs font-semibold text-ink">
              {column.key}
            </code>
          </dt>
          <dd className="mt-2 text-xs leading-5 text-muted">{column.purpose}</dd>
        </div>
      ))}
    </dl>
  );
}

export function ProviderComplianceMatrixTable() {
  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">
          Provider Compliance Matrix with provider, api_or_feature, allowed_data_class,
          retention, zdr_eligible, and training_use columns.
        </caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-normal text-muted">
          <tr>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              provider
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              api_or_feature
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              allowed_data_class
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              retention
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              zdr_eligible
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              training_use
            </th>
          </tr>
        </thead>
        <tbody>
          {PROVIDER_COMPLIANCE_ROWS.map((row) => (
            <tr key={`${row.provider}-${row.api_or_feature}`} className="align-top">
              <th scope="row" className="border-b border-line px-3 py-2 font-medium text-ink">
                <code className="font-mono text-xs">{row.provider}</code>
              </th>
              <td className="border-b border-line px-3 py-2">
                <code className="font-mono text-xs text-ink">{row.api_or_feature}</code>
              </td>
              <td className="border-b border-line px-3 py-2">
                <CodePill>{row.allowed_data_class}</CodePill>
              </td>
              <td className="border-b border-line px-3 py-2 text-muted">{row.retention}</td>
              <td className="border-b border-line px-3 py-2 text-muted">{row.zdr_eligible}</td>
              <td className="border-b border-line px-3 py-2 text-muted">{row.training_use}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function PolicyProfileList() {
  return (
    <ul className="grid gap-2 md:grid-cols-3">
      {POLICY_PROFILES.map((profile) => (
        <li key={profile.name} className="rounded-md border border-line bg-white p-3">
          <code className="font-mono text-xs font-semibold text-accent">{profile.name}</code>
          <p className="mt-2 text-xs leading-5 text-muted">{profile.summary}</p>
        </li>
      ))}
    </ul>
  );
}

export function SecretBoundaryNotice({ title = "SecretBroker boundary" }: { title?: string }) {
  return (
    <section aria-label={title} className="rounded-md border border-rose-200 bg-rose-50 p-3">
      <h3 className="text-sm font-semibold text-danger">{title}</h3>
      <p className="mt-2 text-sm leading-6 text-muted">
        raw secret, raw token, provider key, and capability token values are never
        rendered. UI rows show reason_code, pattern_hit, hash references, actor_id,
        and scrubbed_env_keys only.
      </p>
    </section>
  );
}

function stateToneClass(state: AgentRunState): string {
  if (state === "blocked") {
    return "border-amber-200 bg-amber-50";
  }

  if (TERMINAL_STATES.includes(state)) {
    return "border-teal-200 bg-teal-50";
  }

  return "border-line bg-white";
}
