import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as NextNavigation from "next/navigation";

// A-7 (ADR-00045 R9 F-001): date_context (期限の基準日) 取得失敗時、一覧/Kanban は期限強調を
// neutral に倒すが degraded warning を **可視化** する (silent に dashboard reminder と乖離させない)。

const apiMocks = vi.hoisted(() => ({
  getCurrentProject: vi.fn(),
  loadProjects: vi.fn(),
  loadProjectsAllView: vi.fn(),
  loadProjectTags: vi.fn(),
  loadTickets: vi.fn(),
  fetchDateContext: vi.fn()
}));

vi.mock("@/lib/api/session", () => ({
  getCurrentProject: apiMocks.getCurrentProject
}));

vi.mock("@/lib/api/tickets-board", () => ({
  loadProjects: apiMocks.loadProjects,
  loadProjectsAllView: apiMocks.loadProjectsAllView,
  loadProjectTags: apiMocks.loadProjectTags,
  loadTickets: apiMocks.loadTickets,
  TICKET_BOARD_PAGE_LIMIT: 200
}));

vi.mock("@/lib/api/reminders", () => ({
  fetchDateContext: apiMocks.fetchDateContext
}));

vi.mock("next/navigation", async (importActual) => ({
  ...(await importActual<typeof NextNavigation>()),
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/tickets",
  useSearchParams: () => new URLSearchParams(),
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  }
}));

import TicketsKanbanPage from "../app/(admin)/tickets/page";

const PROJECT = {
  project_id: "00000000-0000-4000-8000-0000000000a1",
  slug: "alpha",
  name: "Alpha",
  status: "active"
};

function overdueOpenTicket() {
  return {
    id: "t-1",
    title: "超過チケット",
    status: "open",
    priority: "high",
    description: null,
    due_date: "2026-05-01",
    created_at: "2026-05-01T00:00:00Z",
    tags: []
  };
}

async function renderPage(): Promise<ReactElement> {
  // all view (project 未指定) で render。
  return TicketsKanbanPage({ searchParams: Promise.resolve({}) });
}

beforeEach(() => {
  apiMocks.getCurrentProject.mockReset();
  apiMocks.loadProjects.mockReset();
  apiMocks.loadProjectsAllView.mockReset();
  apiMocks.loadProjectTags.mockReset();
  apiMocks.loadTickets.mockReset();
  apiMocks.fetchDateContext.mockReset();

  apiMocks.getCurrentProject.mockResolvedValue({ ...PROJECT, tenant_id: 1, workspace_id: "w" });
  apiMocks.loadProjectsAllView.mockResolvedValue({ items: [PROJECT], omittedProjects: 0 });
  apiMocks.loadProjects.mockResolvedValue([PROJECT]);
  apiMocks.loadProjectTags.mockResolvedValue([]);
  apiMocks.loadTickets.mockResolvedValue({
    items: [overdueOpenTicket()],
    total: 1,
    truncated: false
  });
});

describe("TicketsKanbanPage date_context degraded warning (R9 F-001)", () => {
  it("date_context 成功時は warning を出さず、超過 ticket を『超過』強調する", async () => {
    apiMocks.fetchDateContext.mockResolvedValue({ reference_date: "2026-06-02", threshold_days: 7 });
    render(await renderPage());

    expect(
      screen.queryByText(/期限の基準日を取得できなかった/)
    ).not.toBeInTheDocument();
    // open + 超過 + active project + 基準日あり → 「超過」強調が出る。
    expect(screen.getByText(/超過 5\/1/)).toBeInTheDocument();
  });

  it("date_context 失敗時は degraded warning を可視化し、強調は neutral (超過を出さない)", async () => {
    apiMocks.fetchDateContext.mockRejectedValue(new Error("date_context unavailable"));
    render(await renderPage());

    // 失敗を silent neutral にせず警告する (dashboard reminder と silent に乖離させない)。
    expect(screen.getByText(/期限の基準日を取得できなかった/)).toBeInTheDocument();
    // 期限の chip は neutral「期限 5/1」で表示され、「超過 5/1」赤強調は出さない (誤分類しない neutral)。
    // (warning 文言にも「超過」は含まれるため、chip の "超過 5/1" 表記で判定する。)
    expect(screen.queryByText(/超過 5\/1/)).not.toBeInTheDocument();
    expect(screen.getByText(/期限 5\/1/)).toBeInTheDocument();
  });
});
