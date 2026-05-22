import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as ResearchApiModule_ from "@/lib/api/research";
type ResearchApiModule = typeof ResearchApiModule_;


import ResearchListPage from "@/app/(admin)/research/page";

const apiMocks = vi.hoisted(() => ({
  getAdminResearchProjectId: vi.fn(() => "00000000-0000-4000-8000-000000000004"),
  listResearchTasks: vi.fn()
}));

vi.mock("@/lib/api/research", async (importOriginal) => {
  const actual = await importOriginal<ResearchApiModule>();
  return {
    ...actual,
    getAdminResearchProjectId: apiMocks.getAdminResearchProjectId,
    listResearchTasks: apiMocks.listResearchTasks
  };
});

afterEach(() => {
  apiMocks.getAdminResearchProjectId.mockClear();
  apiMocks.listResearchTasks.mockReset();
});

describe("ResearchListPage", () => {
  it("renders research task headers correctly", async () => {
    apiMocks.listResearchTasks.mockResolvedValue({
      items: [
        {
          id: "00000000-0000-4000-8000-000000041001",
          tenant_id: 1,
          project_id: "00000000-0000-4000-8000-000000000004",
          title: "Investigate evidence adapter drift",
          status: "completed",
          created_by_actor_id: "00000000-0000-4000-8000-000000041002",
          created_at: "2026-05-16T00:00:00Z",
          updated_at: "2026-05-16T00:01:00Z",
          metadata: { rls_ready: true }
        }
      ],
      total: 1,
      limit: 50,
      offset: 0
    });

    render(await ResearchListPage());

    expect(screen.getByRole("heading", { name: "リサーチ" })).toBeVisible();
    expect(screen.getByText("Investigate evidence adapter drift")).toBeVisible();
    expect(screen.getByText("完了 (completed)")).toBeVisible();
    expect(screen.getByRole("link", { name: "Investigate evidence adapter drift" })).toHaveAttribute(
      "href",
      "/research/00000000-0000-4000-8000-000000041001"
    );
    expect(screen.getByText("合計 1")).toBeVisible();
  });

  it("renders an empty state", async () => {
    apiMocks.listResearchTasks.mockResolvedValue({
      items: [],
      total: 0,
      limit: 50,
      offset: 0
    });

    render(await ResearchListPage());

    expect(screen.getByText("リサーチ task はまだありません。")).toBeVisible();
    expect(screen.getByText("合計 0")).toBeVisible();
  });
});
