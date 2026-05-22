import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EditTicketForm } from "../app/(admin)/tickets/[id]/_components/edit-ticket-form";
import { NewTicketForm } from "../app/(admin)/tickets/_components/new-ticket-form";
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
  updated_at: "2026-05-22T21:00:00+00:00"
};

describe("ticket form i18n", () => {
  it("opens the new ticket form with Japanese labels and raw enum values preserved", async () => {
    const user = userEvent.setup();
    render(<NewTicketForm />);

    await user.click(screen.getByRole("button", { name: "+ 新規チケット" }));

    expect(screen.getByText("新規チケット作成")).toBeVisible();
    expect(screen.getByLabelText("Slug (kebab-case)")).toHaveAttribute("name", "slug");
    expect(screen.getByLabelText("タイトル")).toHaveAttribute("name", "title");
    expect(screen.getByPlaceholderText("チケットのタイトル")).toBeVisible();
    expect(screen.getByLabelText("説明 (任意)")).toHaveAttribute("name", "description");
    expect(screen.getByPlaceholderText("チケットの説明")).toBeVisible();
    expect(screen.getByRole("combobox", { name: "状態" })).toHaveValue("open");
    expect(screen.getByRole("option", { name: "未着手 (open)" })).toHaveValue("open");
    expect(screen.getByRole("option", { name: "レビュー中 (review)" })).toHaveValue("review");
    expect(screen.getByRole("combobox", { name: "優先度 (任意)" })).toHaveValue("");
    expect(screen.getByRole("option", { name: "緊急 (critical)" })).toHaveValue("critical");
  });

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
