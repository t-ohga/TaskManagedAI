import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditTicketForm } from "../app/(admin)/tickets/[id]/_components/edit-ticket-form";
import type { TicketRead } from "../lib/api/tickets";

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh
  })
}));

afterEach(() => {
  routerMocks.refresh.mockClear();
});

const ticketFixture: TicketRead = {
  id: "00000000-0000-4000-8000-000000099001",
  tenant_id: 1,
  project_id: "00000000-0000-4000-8000-000000000004",
  repository_id: null,
  slug: "sample-ticket",
  title: "Sample ticket",
  description: "Sample description",
  status: "in_progress",
  priority: "high",
  due_date: null,
  assignee_actor_id: null,
  created_by_actor_id: "00000000-0000-4000-8000-000000000001",
  metadata: { rls_ready: true },
  created_at: "2026-05-22T20:00:00+00:00",
  updated_at: "2026-05-22T21:00:00+00:00",
  agent_run_count: 0,
  tags: []
};

describe("ticket form i18n", () => {
  it("renders the edit ticket form with Japanese labels and raw enum values preserved", () => {
    render(
      <EditTicketForm
        // A-6 (ADR-00046): EditTicketForm は EditableTicket (description: string | null) を受け取る。
        ticket={{
          id: ticketFixture.id,
          title: ticketFixture.title,
          description: ticketFixture.description ?? null,
          due_date: ticketFixture.due_date,
          status: ticketFixture.status,
          priority: ticketFixture.priority,
          assignee_actor_id: ticketFixture.assignee_actor_id
        }}
        assignableActors={[]}
        assignableActorsDegraded={false}
      />
    );

    expect(screen.getByText("チケット編集")).toBeVisible();
    expect(screen.getByLabelText("タイトル")).toHaveValue("Sample ticket");
    expect(screen.getByLabelText("説明")).toHaveValue("Sample description");
    expect(screen.getByRole("combobox", { name: "状態" })).toHaveValue("in_progress");
    expect(screen.getByRole("option", { name: "進行中 (in_progress)" })).toHaveValue(
      "in_progress"
    );
    expect(screen.getByRole("option", { name: "完了 (closed)" })).toHaveValue("closed");
    expect(screen.getByRole("combobox", { name: "優先度" })).toHaveValue("high");
    expect(screen.getByRole("option", { name: "高 (high)" })).toHaveValue("high");
    // A-6: 担当者セレクタ (候補なし時は「未割当」のみ)。
    expect(screen.getByRole("combobox", { name: "担当者" })).toHaveValue("");
    expect(screen.getByRole("button", { name: "保存" })).toBeVisible();
  });
});

// A-6 (ADR-00046): 担当者セレクタの挙動 (候補表示 / R1 F-009 現在値保持 / degraded 警告)。
describe("ticket assignee selector", () => {
  const ASSIGNEE_A = "00000000-0000-4000-8000-0000000000a1";
  const ASSIGNEE_OUT = "00000000-0000-4000-8000-0000000000ff";

  function editableTicket(assigneeActorId: string | null) {
    return {
      id: ticketFixture.id,
      title: ticketFixture.title,
      description: ticketFixture.description ?? null,
      due_date: ticketFixture.due_date,
      status: ticketFixture.status,
      priority: ticketFixture.priority,
      assignee_actor_id: assigneeActorId
    };
  }

  it("候補 actor を option に表示し、現 assignee を選択値にする", () => {
    render(
      <EditTicketForm
        ticket={editableTicket(ASSIGNEE_A)}
        assignableActors={[{ id: ASSIGNEE_A, display_name: "Owner" }]}
        assignableActorsDegraded={false}
      />
    );
    const select = screen.getByRole("combobox", { name: "担当者" });
    expect(select).toHaveValue(ASSIGNEE_A);
    expect(screen.getByRole("option", { name: "Owner" })).toHaveValue(ASSIGNEE_A);
    expect(screen.getByRole("option", { name: "未割当" })).toHaveValue("");
  });

  it("現 assignee が候補一覧に無くても option に保持し選択値を失わない (R1 F-009)", () => {
    render(
      <EditTicketForm
        ticket={editableTicket(ASSIGNEE_OUT)}
        assignableActors={[{ id: ASSIGNEE_A, display_name: "Owner" }]}
        assignableActorsDegraded={false}
      />
    );
    const select = screen.getByRole("combobox", { name: "担当者" });
    // 現在値 (一覧外) が option として存在し、selected を維持する。
    expect(select).toHaveValue(ASSIGNEE_OUT);
    expect(screen.getByRole("option", { name: "担当者 (一覧外)" })).toHaveValue(ASSIGNEE_OUT);
  });

  it("候補取得失敗 (degraded) は警告を表示し、現 assignee を保持する (R1 F-009)", () => {
    render(
      <EditTicketForm
        ticket={editableTicket(ASSIGNEE_OUT)}
        assignableActors={[]}
        assignableActorsDegraded={true}
      />
    );
    expect(screen.getByText(/担当者候補を取得できませんでした/)).toBeVisible();
    // degraded でも現在値は option に保持される (silent に未割当へ倒さない)。
    expect(screen.getByRole("combobox", { name: "担当者" })).toHaveValue(ASSIGNEE_OUT);
  });
});
