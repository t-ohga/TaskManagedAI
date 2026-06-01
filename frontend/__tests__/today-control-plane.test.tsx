import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import TodayPage from "@/app/(admin)/today/page";

const apiMocks = vi.hoisted(() => ({
  fetchKpiRollupOrFallback: vi.fn(),
  getCurrentProject: vi.fn(),
  listAgentRuns: vi.fn(),
  listApprovals: vi.fn(),
  listTickets: vi.fn(),
}));

vi.mock("@/lib/api/agent-runs", () => ({
  listAgentRuns: apiMocks.listAgentRuns,
}));

vi.mock("@/lib/api/approvals", () => ({
  listApprovals: apiMocks.listApprovals,
}));

vi.mock("@/lib/api/eval-dashboard", () => ({
  fetchKpiRollupOrFallback: apiMocks.fetchKpiRollupOrFallback,
}));

vi.mock("@/lib/api/session", () => ({
  getCurrentProject: apiMocks.getCurrentProject,
}));

vi.mock("@/lib/api/tickets", () => ({
  listTickets: apiMocks.listTickets,
}));

afterEach(() => {
  apiMocks.fetchKpiRollupOrFallback.mockReset();
  apiMocks.getCurrentProject.mockReset();
  apiMocks.listAgentRuns.mockReset();
  apiMocks.listApprovals.mockReset();
  apiMocks.listTickets.mockReset();
});

describe("TodayPage", () => {
  it("renders Today and Inbox lanes from existing read-only APIs", async () => {
    apiMocks.getCurrentProject.mockResolvedValue({
      tenant_id: 1,
      project_id: "00000000-0000-4000-8000-000000000004",
      workspace_id: "00000000-0000-4000-8000-000000000001",
      slug: "taskmanagedai",
      name: "TaskManagedAI",
    });
    apiMocks.listTickets.mockResolvedValue({
      items: [
        buildTicket({
          id: "00000000-0000-4000-8000-000000095001",
          slug: "critical-work",
          title: "Critical open work",
          priority: "critical",
          status: "open",
          assignee_actor_id: "00000000-0000-4000-8000-000000095901",
        }),
        buildTicket({
          id: "00000000-0000-4000-8000-000000095002",
          slug: "inbox-work",
          title: "Unassigned inbox work",
          priority: "high",
          status: "blocked",
          assignee_actor_id: null,
        }),
        buildTicket({
          id: "00000000-0000-4000-8000-000000095003",
          slug: "done-work",
          title: "Closed work",
          priority: "low",
          status: "closed",
          assignee_actor_id: null,
        }),
      ],
      total: 3,
      limit: 120,
      offset: 0,
    });
    apiMocks.listAgentRuns.mockResolvedValue({
      items: [
        buildRun({
          id: "00000000-0000-4000-8000-000000096001",
          status: "running",
          role_id: "orchestrator",
        }),
        buildRun({
          id: "00000000-0000-4000-8000-000000096002",
          status: "queued",
          role_id: null,
        }),
        buildRun({
          id: "00000000-0000-4000-8000-000000096003",
          status: "completed",
          role_id: "reviewer",
        }),
      ],
      total: 3,
      limit: 80,
      offset: 0,
    });
    apiMocks.listApprovals.mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000097001",
        action_class: "repo_write",
        resource_ref: "repo:TaskManagedAI:docs/sprints/SP-009.md",
        risk_level: "high",
        status: "pending",
        requested_by_actor_id: "00000000-0000-4000-8000-000000097901",
        requested_at: "2026-05-24T00:10:00Z",
      },
    ]);
    apiMocks.fetchKpiRollupOrFallback.mockResolvedValue({
      source: "live",
      data: {
        kpi_count: 5,
        met_count: 4,
        failed_count: 1,
        p0_accept: true,
        fail_tolerance: 1,
        entries: [],
        corpus_loads: [],
      },
    });

    render(await TodayPage());

    const region = screen.getByRole("region", { name: "Today control plane" });
    expect(within(region).getByRole("heading", { name: "Today / Inbox" })).toBeVisible();

    const kpiStrip = within(region).getByLabelText("Today KPI strip");
    expect(within(kpiStrip).getByText("未完了チケット")).toBeVisible();
    expect(within(kpiStrip).getByText("2")).toBeVisible();
    expect(within(kpiStrip).getByText("4/5")).toBeVisible();

    // Lane component は aria-label={`${title} lane`} を出す。i18n で lane title が
    // 日本語化済 ("今日の概要" / "受信箱") のため region 名も日本語 + " lane"。
    const todayLane = within(region).getByRole("region", { name: "今日の概要 lane" });
    expect(within(todayLane).getByText("Critical open work")).toBeVisible();
    expect(within(todayLane).getByText("Unassigned inbox work")).toBeVisible();
    expect(within(todayLane).getByText("リポジトリ書込 (repo_write)")).toBeVisible();
    expect(within(todayLane).getByText("running")).toBeVisible();

    const inboxLane = within(region).getByRole("region", { name: "受信箱 lane" });
    expect(within(inboxLane).getByText("Unassigned inbox work")).toBeVisible();
    expect(within(inboxLane).getByText("queued")).toBeVisible();
    expect(within(region).queryByText("Closed work")).not.toBeInTheDocument();

    expect(apiMocks.listApprovals).toHaveBeenCalledWith({ status: "pending" });
  });

  it("renders partial source errors without hiding available sources", async () => {
    apiMocks.getCurrentProject.mockRejectedValue(new Error("do not expose raw detail"));
    apiMocks.listAgentRuns.mockResolvedValue({
      items: [buildRun({ status: "queued" })],
      total: 1,
      limit: 80,
      offset: 0,
    });
    apiMocks.listApprovals.mockResolvedValue([]);
    apiMocks.fetchKpiRollupOrFallback.mockRejectedValue(new Error("backend unavailable"));

    render(await TodayPage());

    expect(screen.getByRole("status")).toHaveTextContent("tickets: チケットを取得できません");
    expect(screen.getByRole("status")).toHaveTextContent("kpi: KPI を取得できません");
    expect(screen.queryByText("do not expose raw detail")).not.toBeInTheDocument();
    expect(screen.getAllByText("queued").length).toBeGreaterThanOrEqual(1);
  });
});

function buildTicket(overrides: Record<string, unknown>) {
  return {
    id: "00000000-0000-4000-8000-000000095000",
    tenant_id: 1,
    project_id: "00000000-0000-4000-8000-000000000004",
    repository_id: null,
    slug: "ticket",
    title: "Ticket",
    description: null,
    status: "open",
    priority: "medium",
    assignee_actor_id: null,
    created_by_actor_id: "00000000-0000-4000-8000-000000095900",
    metadata: {},
    created_at: "2026-05-24T00:00:00Z",
    updated_at: "2026-05-24T00:01:00Z",
    ...overrides,
  };
}

function buildRun(overrides: Record<string, unknown>) {
  return {
    id: "00000000-0000-4000-8000-000000096000",
    tenant_id: 1,
    project_id: "00000000-0000-4000-8000-000000000004",
    parent_run_id: null,
    status: "queued",
    blocked_reason: null,
    error_code: null,
    error_summary: null,
    completed_at: null,
    role_id: null,
    role_scope: null,
    orchestrator_lease_expires_at: null,
    last_progress_at: "2026-05-24T00:00:00Z",
    progress_seq: 1,
    created_at: "2026-05-24T00:00:00Z",
    updated_at: "2026-05-24T00:01:00Z",
    ...overrides,
  };
}
