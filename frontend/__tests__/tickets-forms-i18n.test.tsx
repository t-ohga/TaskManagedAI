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
  assignee_actor_id: null,
  created_by_actor_id: "00000000-0000-4000-8000-000000000001",
  metadata: { rls_ready: true },
  created_at: "2026-05-22T20:00:00+00:00",
  updated_at: "2026-05-22T21:00:00+00:00",
  agent_run_count: 0
};

describe("ticket form i18n", () => {
  it("renders the edit ticket form with Japanese labels and raw enum values preserved", () => {
    render(<EditTicketForm ticket={ticketFixture} />);

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
    expect(screen.getByRole("button", { name: "保存" })).toBeVisible();
  });
});
