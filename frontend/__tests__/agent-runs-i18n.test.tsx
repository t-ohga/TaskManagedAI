import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AgentRunsPage from "../app/(admin)/runs/page";

const apiMocks = vi.hoisted(() => ({
  listAgentRuns: vi.fn()
}));

const statuses = [
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

vi.mock("@/lib/api/agent-runs", () => ({
  AgentRunStatusEnum: {
    safeParse(value: unknown) {
      return typeof value === "string" && statuses.includes(value as (typeof statuses)[number])
        ? { success: true, data: value }
        : { success: false };
    }
  },
  listAgentRuns: apiMocks.listAgentRuns
}));

afterEach(() => {
  apiMocks.listAgentRuns.mockReset();
});

describe("AgentRunsPage i18n", () => {
  it("renders Japanese page labels while preserving AgentRun raw state values", async () => {
    apiMocks.listAgentRuns.mockResolvedValue({
      items: [
        {
          id: "00000000-0000-4000-8000-00000000a001",
          tenant_id: 1,
          project_id: "00000000-0000-4000-8000-00000000a002",
          parent_run_id: null,
          status: "blocked",
          blocked_reason: "runtime_blocked",
          error_code: null,
          error_summary: null,
          completed_at: null,
          role_id: "reviewer",
          role_scope: "project",
          orchestrator_lease_expires_at: null,
          last_progress_at: "2026-05-22T00:00:00Z",
          progress_seq: 3,
          created_at: "2026-05-22T00:00:00Z",
          updated_at: "2026-05-22T00:01:00Z"
        }
      ],
      total: 1,
      limit: 50,
      offset: 0
    });

    render(await AgentRunsPage());

    const region = screen.getByRole("region", { name: "AI 実行一覧" });
    expect(within(region).getByRole("heading", { name: "AI 実行" })).toBeVisible();
    expect(within(region).getAllByText("blocked").length).toBeGreaterThanOrEqual(1);
    expect(within(region).getByText("runtime_blocked")).toBeVisible();
    expect(within(region).getByText("project:reviewer")).toBeVisible();
  });
});
