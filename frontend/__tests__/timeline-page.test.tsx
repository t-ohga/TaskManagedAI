import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TimelinePage from "@/app/(admin)/timeline/page";

const apiMocks = vi.hoisted(() => ({
  fetchKpiRollupOrFallback: vi.fn(),
  getAgentRun: vi.fn(),
  listAgentRuns: vi.fn(),
  listApprovals: vi.fn(),
  listAuditEvents: vi.fn(),
}));

vi.mock("@/lib/api/agent-runs", () => ({
  getAgentRun: apiMocks.getAgentRun,
  listAgentRuns: apiMocks.listAgentRuns,
}));

vi.mock("@/lib/api/approvals", () => ({
  listApprovals: apiMocks.listApprovals,
}));

vi.mock("@/lib/api/audit", () => ({
  listAuditEvents: apiMocks.listAuditEvents,
}));

vi.mock("@/lib/api/eval-dashboard", () => ({
  fetchKpiRollupOrFallback: apiMocks.fetchKpiRollupOrFallback,
}));

afterEach(() => {
  apiMocks.fetchKpiRollupOrFallback.mockReset();
  apiMocks.getAgentRun.mockReset();
  apiMocks.listAgentRuns.mockReset();
  apiMocks.listApprovals.mockReset();
  apiMocks.listAuditEvents.mockReset();
});

describe("TimelinePage", () => {
  it("renders AgentRunEvent, AuditEvent, and Approval rows without sensitive payload keys", async () => {
    apiMocks.listAgentRuns.mockResolvedValue({
      items: [buildRun({ id: "00000000-0000-4000-8000-000000098001" })],
      total: 1,
      limit: 12,
      offset: 0,
    });
    apiMocks.getAgentRun.mockResolvedValue(
      buildRunDetail({
        id: "00000000-0000-4000-8000-000000098001",
        events: [
          {
            id: "00000000-0000-4000-8000-000000098101",
            run_id: "00000000-0000-4000-8000-000000098001",
            seq_no: 3,
            event_type: "provider_requested",
            actor_id: "00000000-0000-4000-8000-000000098901",
            payload_keys: ["request_id", "raw_prompt", "token"],
            payload_redaction_status: "keys_only",
            created_at: "2026-05-24T00:03:00Z",
          },
        ],
      })
    );
    apiMocks.listAuditEvents.mockResolvedValue({
      events: [
        {
          id: "00000000-0000-4000-8000-000000098201",
          event_type: "budget_blocked",
          actor_id: "00000000-0000-4000-8000-000000098902",
          principal_id: null,
          tenant_id: 1,
          trace_id: "trace-1",
          correlation_id: "corr-1",
          reason_code: "budget_limit",
          payload_keys: ["budget_id", "secret_value"],
          payload_redaction_status: "keys_only",
          created_at: "2026-05-24T00:02:00Z",
        },
      ],
      total: 1,
      limit: 40,
      offset: 0,
    });
    apiMocks.listApprovals.mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000098301",
        action_class: "repo_write",
        resource_ref: "repo:TaskManagedAI:timeline",
        risk_level: "high",
        status: "pending",
        requested_by_actor_id: "00000000-0000-4000-8000-000000098903",
        requested_at: "2026-05-24T00:01:00Z",
      },
    ]);
    apiMocks.fetchKpiRollupOrFallback.mockResolvedValue({
      source: "live",
      data: {
        kpi_count: 5,
        met_count: 3,
        failed_count: 2,
        p0_accept: false,
        fail_tolerance: 1,
        entries: [],
        corpus_loads: [],
      },
    });

    render(await TimelinePage());

    const region = screen.getByRole("region", { name: "Execution timeline" });
    expect(within(region).getByRole("heading", { name: "実行タイムライン" })).toBeVisible();
    expect(within(region).getByLabelText("Timeline summary")).toHaveTextContent("3/5");

    const rows = within(region).getByRole("region", { name: "Unified event rows" });
    expect(within(rows).getByText("provider_requested")).toBeVisible();
    expect(within(rows).getByText("budget_blocked")).toBeVisible();
    expect(within(rows).getByText("リポジトリ書込 (repo_write)")).toBeVisible();
    expect(within(rows).getByText("keys:request_id / hidden_keys:2")).toBeVisible();
    expect(within(rows).getByText("keys:budget_id / hidden_keys:1")).toBeVisible();
    expect(within(rows).queryByText("raw_prompt")).not.toBeInTheDocument();
    expect(within(rows).queryByText("token")).not.toBeInTheDocument();
    expect(within(rows).queryByText("secret_value")).not.toBeInTheDocument();
  });

  it("renders partial source errors while preserving available timeline rows", async () => {
    apiMocks.listAgentRuns.mockRejectedValue(new Error("raw backend detail"));
    apiMocks.listAuditEvents.mockResolvedValue({
      events: [
        {
          id: "00000000-0000-4000-8000-000000098202",
          event_type: "runner_completed",
          actor_id: null,
          principal_id: null,
          tenant_id: 1,
          trace_id: null,
          correlation_id: null,
          reason_code: null,
          payload_keys: ["artifact_id"],
          payload_redaction_status: "keys_only",
          created_at: "2026-05-24T00:04:00Z",
        },
      ],
      total: 1,
      limit: 40,
      offset: 0,
    });
    apiMocks.listApprovals.mockResolvedValue([]);
    apiMocks.fetchKpiRollupOrFallback.mockRejectedValue(new Error("kpi raw detail"));

    render(await TimelinePage());

    expect(screen.getByRole("status")).toHaveTextContent(
      "agent_events: AI 実行イベントを取得できません"
    );
    expect(screen.getByRole("status")).toHaveTextContent("kpi: KPI を取得できません");
    expect(screen.queryByText("raw backend detail")).not.toBeInTheDocument();
    expect(screen.queryByText("kpi raw detail")).not.toBeInTheDocument();
    expect(screen.getByText("runner_completed")).toBeVisible();
  });
});

function buildRun(overrides: Record<string, unknown>) {
  return {
    id: "00000000-0000-4000-8000-000000098000",
    tenant_id: 1,
    project_id: "00000000-0000-4000-8000-000000000004",
    parent_run_id: null,
    status: "running",
    blocked_reason: null,
    error_code: null,
    error_summary: null,
    completed_at: null,
    role_id: "orchestrator",
    role_scope: "project",
    orchestrator_lease_expires_at: null,
    last_progress_at: "2026-05-24T00:00:00Z",
    progress_seq: 1,
    created_at: "2026-05-24T00:00:00Z",
    updated_at: "2026-05-24T00:01:00Z",
    ...overrides,
  };
}

function buildRunDetail({
  events,
  ...overrides
}: Record<string, unknown> & { events: unknown[] }) {
  return {
    ...buildRun(overrides),
    events,
    context_snapshot: null,
  };
}
