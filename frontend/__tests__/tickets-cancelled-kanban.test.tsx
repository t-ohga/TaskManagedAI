// #7 / ADR-00054: 中止 (cancelled) は backend (pagination 前) で既定除外し、StatusFilter=中止 の時のみ
// 表示する。本 test は page が status/excludeCancelled param を正しく backend へ渡し、応答に従って
// 表示すること、および「中止のみ project」の hint (silent empty 回避) を純粋既定 view に限定すること
// を固定する。mock loadTickets は backend の filter 挙動 (status exact / exclude_cancelled / total_unfiltered)
// を再現する。
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as NextNavigation from "next/navigation";
import type { LoadTicketsOptions } from "@/lib/api/tickets-board";

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

type Item = { id: string; title: string; status: string; priority: string; description: null; due_date: null; created_at: string; tags: [] };

function item(id: string, title: string, status: string): Item {
  return { id, title, status, priority: "medium", description: null, due_date: null, created_at: "2026-05-01T00:00:00Z", tags: [] };
}

const OPEN = item("t-open", "進行中タスク", "open");
const CLOSED = item("t-closed", "完了タスク", "closed");
const CANCELLED = item("t-cancelled", "中止タスク", "cancelled");

// backend (list_tickets_endpoint) の status filter を再現する loadTickets mock factory。
// universe = project の全 ticket。options.status (exact、precedence) > options.excludeCancelled。
function mockLoadTicketsWith(universe: Item[]) {
  apiMocks.loadTickets.mockImplementation(
    async (_pid: string, _tag?: string, options?: LoadTicketsOptions) => {
      const totalUnfiltered = universe.length;
      let items = universe;
      if (options?.status) items = universe.filter((t) => t.status === options.status);
      else if (options?.excludeCancelled) items = universe.filter((t) => t.status !== "cancelled");
      return { items, total: items.length, totalUnfiltered, truncated: false };
    }
  );
}

function renderPage(searchParams: Record<string, string> = {}): Promise<ReactElement> {
  return TicketsKanbanPage({ searchParams: Promise.resolve(searchParams) });
}

beforeEach(() => {
  apiMocks.getCurrentProject.mockReset();
  apiMocks.loadProjects.mockReset();
  apiMocks.loadProjectsAllView.mockReset();
  apiMocks.loadProjectTags.mockReset();
  apiMocks.loadTickets.mockReset();
  apiMocks.fetchDateContext.mockReset();

  apiMocks.getCurrentProject.mockResolvedValue({ ...PROJECT, tenant_id: 1, workspace_id: "w" });
  apiMocks.loadProjectsAllView.mockResolvedValue({ items: [PROJECT], omittedProjects: 0, degraded: false });
  apiMocks.loadProjects.mockResolvedValue([PROJECT]);
  apiMocks.loadProjectTags.mockResolvedValue([]);
  apiMocks.fetchDateContext.mockResolvedValue({ reference_date: "2026-06-02", threshold_days: 7 });
  mockLoadTicketsWith([OPEN, CLOSED, CANCELLED]);
});

describe("TicketsKanbanPage cancelled exclusion (ADR-00054, server-side)", () => {
  it("既定表示は backend へ excludeCancelled を渡し、中止を看板から除外する", async () => {
    render(await renderPage());

    // page は既定で excludeCancelled=true を渡す。
    const call = apiMocks.loadTickets.mock.calls.at(-1);
    expect(call?.[2]).toMatchObject({ excludeCancelled: true });

    expect(screen.getByText("進行中タスク")).toBeInTheDocument();
    expect(screen.getByText("完了タスク")).toBeInTheDocument();
    expect(screen.queryByText("中止タスク")).not.toBeInTheDocument();
  });

  it("StatusFilter=中止 は backend へ status=cancelled を渡し、中止を表示する (証跡 access)", async () => {
    render(await renderPage({ status: "cancelled" }));

    const call = apiMocks.loadTickets.mock.calls.at(-1);
    expect(call?.[2]).toMatchObject({ status: "cancelled" });

    expect(screen.getByText("中止タスク")).toBeInTheDocument();
    expect(screen.queryByText("進行中タスク")).not.toBeInTheDocument();
    expect(screen.queryByText("完了タスク")).not.toBeInTheDocument();
  });

  it("StatusFilter=完了 は status=closed を渡し、中止は混ざらない", async () => {
    render(await renderPage({ status: "closed" }));

    expect(apiMocks.loadTickets.mock.calls.at(-1)?.[2]).toMatchObject({ status: "closed" });
    expect(screen.getByText("完了タスク")).toBeInTheDocument();
    expect(screen.queryByText("中止タスク")).not.toBeInTheDocument();
  });
});

describe("TicketsKanbanPage cancelled-only hint (ADR-00054 R2/R3, 純粋既定 view 限定)", () => {
  it("中止のみ project は純粋既定 view で hint を出し silent empty にしない", async () => {
    mockLoadTicketsWith([CANCELLED]); // 中止のみ → excludeCancelled で items=[], totalUnfiltered=1
    render(await renderPage());

    expect(screen.getByText(/現在の表示条件では中止チケットのみです/)).toBeInTheDocument();
  });

  it("真の空 project では中止のみ hint を出さない", async () => {
    mockLoadTicketsWith([]); // total_unfiltered=0
    render(await renderPage());

    expect(screen.queryByText(/現在の表示条件では中止チケットのみです/)).not.toBeInTheDocument();
  });

  it("status=blocked が 0 件でも中止のみ hint を出さない (status filter は純粋既定 view でない)", async () => {
    mockLoadTicketsWith([OPEN, CLOSED, CANCELLED]); // blocked は 0 件、total_unfiltered=3
    render(await renderPage({ status: "blocked" }));

    // status filter 指定なので cancelled-only hint は出さない (誤誘導しない)。
    expect(screen.queryByText(/現在の表示条件では中止チケットのみです/)).not.toBeInTheDocument();
  });

  it("検索 (q) で 0 件でも中止のみ hint を出さない (client filter は純粋既定 view でない)", async () => {
    mockLoadTicketsWith([CANCELLED]);
    render(await renderPage({ q: "存在しない語" }));

    expect(screen.queryByText(/現在の表示条件では中止チケットのみです/)).not.toBeInTheDocument();
  });

  it("all view で project 取得欠落 (omittedProjects>0) の間は中止のみ hint を出さない (code review fix)", async () => {
    // 読めた project は中止のみだが、読めなかった project に非中止があるかもしれない → 断定しない。
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: [PROJECT], omittedProjects: 1, degraded: false });
    mockLoadTicketsWith([CANCELLED]);
    render(await renderPage());

    expect(screen.queryByText(/現在の表示条件では中止チケットのみです/)).not.toBeInTheDocument();
  });
});

describe("TicketsKanbanPage unknown status URL (code review fix)", () => {
  it("URL の未知 status は backend へ渡さず excludeCancelled 既定として扱う (422 昇格を防ぐ)", async () => {
    mockLoadTicketsWith([OPEN, CLOSED, CANCELLED]);
    render(await renderPage({ status: "bogus_status" }));

    // 未知 status は allowlist で弾かれ、loadTickets には status を渡さず excludeCancelled=true。
    const call = apiMocks.loadTickets.mock.calls.at(-1);
    expect(call?.[2]).toMatchObject({ excludeCancelled: true });
    expect(call?.[2]).not.toHaveProperty("status");
    // 既定表示として中止は隠れ、他 status は表示される (画面は壊れない)。
    expect(screen.getByText("進行中タスク")).toBeInTheDocument();
    expect(screen.queryByText("中止タスク")).not.toBeInTheDocument();
  });
});
