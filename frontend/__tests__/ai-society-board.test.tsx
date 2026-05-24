import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AiSocietyBoardPage from "@/app/(admin)/orchestrator/board/page";

const apiMocks = vi.hoisted(() => ({
  getAgentRun: vi.fn(),
  listAgentRuns: vi.fn()
}));

vi.mock("@/lib/api/agent-runs", () => ({
  getAgentRun: apiMocks.getAgentRun,
  listAgentRuns: apiMocks.listAgentRuns
}));

afterEach(() => {
  apiMocks.getAgentRun.mockReset();
  apiMocks.listAgentRuns.mockReset();
});

describe("AiSocietyBoardPage", () => {
  it("renders role summaries and inter-agent ref timeline without raw message keys", async () => {
    apiMocks.listAgentRuns.mockResolvedValue({
      items: [
        buildRun({
          id: "00000000-0000-4000-8000-000000017001",
          role_id: "orchestrator",
          role_scope: "project",
          status: "running"
        }),
        buildRun({
          id: "00000000-0000-4000-8000-000000017002",
          role_id: "reviewer",
          role_scope: "project",
          status: "completed"
        }),
        buildRun({
          id: "00000000-0000-4000-8000-000000017003",
          role_id: "custom_agent",
          role_scope: "tenant",
          status: "blocked"
        })
      ],
      total: 3,
      limit: 80,
      offset: 0
    });
    apiMocks.getAgentRun.mockResolvedValueOnce(
      buildRunDetail({
        id: "00000000-0000-4000-8000-000000017001",
        role_id: "orchestrator",
        status: "running",
        events: [
          {
            id: "00000000-0000-4000-8000-000000017101",
            run_id: "00000000-0000-4000-8000-000000017001",
            seq_no: 4,
            event_type: "inter_agent_message_sent_ref",
            actor_id: "00000000-0000-4000-8000-000000017901",
            payload_keys: ["message_id", "payload_hash", "raw_message_body", "token"],
            payload_redaction_status: "keys_only",
            created_at: "2026-05-24T00:04:00Z"
          }
        ]
      })
    );
    apiMocks.getAgentRun.mockResolvedValueOnce(
      buildRunDetail({
        id: "00000000-0000-4000-8000-000000017002",
        role_id: "reviewer",
        status: "completed",
        events: [
          {
            id: "00000000-0000-4000-8000-000000017102",
            run_id: "00000000-0000-4000-8000-000000017002",
            seq_no: 2,
            event_type: "run_completed",
            actor_id: "00000000-0000-4000-8000-000000017902",
            payload_keys: ["artifact_id"],
            payload_redaction_status: "keys_only",
            created_at: "2026-05-24T00:03:00Z"
          }
        ]
      })
    );
    apiMocks.getAgentRun.mockResolvedValueOnce(
      buildRunDetail({
        id: "00000000-0000-4000-8000-000000017003",
        role_id: "custom_agent",
        status: "blocked",
        events: []
      })
    );

    render(await AiSocietyBoardPage());

    const region = screen.getByRole("region", { name: "AI 組織ボード" });
    expect(within(region).getByRole("heading", { name: "AI 組織ボード" })).toBeVisible();
    expect(within(region).getByRole("heading", { name: "role catalog" })).toBeVisible();
    expect(within(region).getByLabelText("司令塔 orchestrator")).toHaveTextContent("running");
    expect(within(region).getByLabelText("レビュー reviewer")).toHaveTextContent("completed");
    expect(within(region).getByText("custom_agent")).toBeVisible();

    const timeline = within(region).getByRole("table", {
      name: "inter-agent event_type、payload_keys、run_id"
    });
    expect(within(timeline).getByText("inter_agent_message_sent_ref")).toBeVisible();
    expect(within(timeline).getByText("message_id, payload_hash")).toBeVisible();
    expect(within(timeline).getByText("hidden_non_ref_keys:2")).toBeVisible();
    expect(within(timeline).queryByText("raw_message_body")).not.toBeInTheDocument();
    expect(within(timeline).queryByText("token")).not.toBeInTheDocument();
    expect(apiMocks.getAgentRun).toHaveBeenCalledTimes(3);
  });

  it("renders a fail-closed error state when the AgentRun list API fails", async () => {
    apiMocks.listAgentRuns.mockRejectedValue(new Error("backend unavailable"));

    render(await AiSocietyBoardPage());

    expect(screen.getByRole("status")).toHaveTextContent("AI 組織ボードを表示できません");
    expect(screen.getByText("backend unavailable")).toBeVisible();
    expect(apiMocks.getAgentRun).not.toHaveBeenCalled();
  });
});

function buildRun(overrides: Record<string, unknown>) {
  return {
    id: "00000000-0000-4000-8000-000000017000",
    tenant_id: 1,
    project_id: "00000000-0000-4000-8000-000000017999",
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
    ...overrides
  };
}

function buildRunDetail({
  events,
  ...overrides
}: Record<string, unknown> & { events: unknown[] }) {
  return {
    ...buildRun(overrides),
    events,
    context_snapshot: null
  };
}
