// A-3 (board 体感改善): board ページの独立 fetch を並列化したことを固定する。逐次 await への退行を
// 捕捉するため、各 fetch を in-flight counter でラップし「同時に in-flight になった最大数」を観測する。
//  - Wave 1: 互いに独立な top-level fetch (projects / currentProject / dateContext / assignableActors)
//    が 1 波で並列に走る (maxInFlight === 4)。逐次なら maxInFlight === 1。
//  - Wave 2: all view の project ごとの loadTickets が並列に走る (maxInFlight === project 数)。
// 並列化しても各 fetch の error 方針 (per-project fail-soft omission / 集約の決定性) を保持することも
// 併せて固定する。
import { render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as NextNavigation from "next/navigation";

const apiMocks = vi.hoisted(() => ({
  getCurrentProject: vi.fn(),
  loadProjects: vi.fn(),
  loadProjectsAllView: vi.fn(),
  loadProjectTags: vi.fn(),
  loadTickets: vi.fn(),
  fetchDateContext: vi.fn(),
  fetchAssignableActors: vi.fn()
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

vi.mock("@/lib/api/actors", () => ({
  fetchAssignableActors: apiMocks.fetchAssignableActors
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

type Item = {
  id: string;
  title: string;
  status: string;
  priority: string;
  description: null;
  due_date: null;
  created_at: string;
  tags: [];
};

function item(id: string, title: string): Item {
  return {
    id,
    title,
    status: "open",
    priority: "medium",
    description: null,
    due_date: null,
    created_at: "2026-05-01T00:00:00Z",
    tags: []
  };
}

function project(suffix: string, slug: string, name: string) {
  return {
    project_id: `00000000-0000-4000-8000-0000000000${suffix}`,
    slug,
    name,
    status: "active"
  };
}

// in-flight 同時実行数の最大値を観測する tracker。各 fetch mock を wrap し、5ms の重なり窓で
// 「逐次 (max=1) / 並列 (max=N)」を決定的に判別する。逐次なら次呼び出し前に inFlight が 0 に戻る。
function makeInFlightTracker() {
  let inFlight = 0;
  let max = 0;
  return {
    get max() {
      return max;
    },
    async run<T>(value: T): Promise<T> {
      inFlight += 1;
      max = Math.max(max, inFlight);
      await new Promise((resolve) => setTimeout(resolve, 5));
      inFlight -= 1;
      return value;
    }
  };
}

function board(items: Item[], totalUnfiltered = items.length) {
  return { items, total: items.length, totalUnfiltered, truncated: false };
}

function renderPage(searchParams: Record<string, string> = {}): Promise<ReactElement> {
  return TicketsKanbanPage({ searchParams: Promise.resolve(searchParams) });
}

beforeEach(() => {
  for (const m of Object.values(apiMocks)) m.mockReset();
  // 既定: all view で 1 project + 候補/基準日は成功。各 test で上書きする。
  apiMocks.getCurrentProject.mockResolvedValue({
    ...project("a1", "alpha", "Alpha"),
    tenant_id: 1,
    workspace_id: "w"
  });
  apiMocks.loadProjectsAllView.mockResolvedValue({
    items: [project("a1", "alpha", "Alpha")],
    omittedProjects: 0,
    degraded: false
  });
  apiMocks.loadProjects.mockResolvedValue([project("a1", "alpha", "Alpha")]);
  apiMocks.loadProjectTags.mockResolvedValue([]);
  apiMocks.fetchDateContext.mockResolvedValue({ reference_date: "2026-06-02", threshold_days: 7 });
  apiMocks.fetchAssignableActors.mockResolvedValue({ actors: [], truncated: false });
  apiMocks.loadTickets.mockResolvedValue(board([item("t1", "タスク1")]));
});

describe("TicketsKanbanPage Wave 1 並列 fetch (A-3)", () => {
  it("独立した top-level fetch (projects/currentProject/dateContext/assignableActors) が並列に走る", async () => {
    const tracker = makeInFlightTracker();
    apiMocks.loadProjectsAllView.mockImplementation(() =>
      tracker.run({ items: [project("a1", "alpha", "Alpha")], omittedProjects: 0, degraded: false })
    );
    apiMocks.getCurrentProject.mockImplementation(() =>
      tracker.run({ ...project("a1", "alpha", "Alpha"), tenant_id: 1, workspace_id: "w" })
    );
    apiMocks.fetchDateContext.mockImplementation(() =>
      tracker.run({ reference_date: "2026-06-02", threshold_days: 7 })
    );
    apiMocks.fetchAssignableActors.mockImplementation(() => tracker.run({ actors: [], truncated: false }));

    render(await renderPage());

    // 4 fetch が同時に in-flight = 並列化されている (逐次なら 1)。
    expect(tracker.max).toBe(4);
  });
});

describe("TicketsKanbanPage Wave 1 fail-closed orchestration (A-3 / R3 無駄打ち防止)", () => {
  it("fail-closed (具体 project) で projects fetch が reject すると optional fetch を起動しない", async () => {
    // 具体 project 指定 = fail-closed。loadProjects は reject しうる (auth/backend/schema 障害)。
    apiMocks.loadProjects.mockRejectedValue(new Error("projects auth failed"));

    await expect(renderPage({ project: "alpha" })).rejects.toThrow("projects auth failed");

    // projects 失敗 (→ error boundary) 時、結果に使えない optional fetch を投げて pool を圧迫しない。
    expect(apiMocks.getCurrentProject).not.toHaveBeenCalled();
    expect(apiMocks.fetchDateContext).not.toHaveBeenCalled();
    expect(apiMocks.fetchAssignableActors).not.toHaveBeenCalled();
    // 後続 (tags / tickets) も当然起動しない。
    expect(apiMocks.loadProjectTags).not.toHaveBeenCalled();
    expect(apiMocks.loadTickets).not.toHaveBeenCalled();
  });

  it("fail-closed (具体 project) で projects 成功後は optional fetch を起動する", async () => {
    render(await renderPage({ project: "alpha" }));

    // projects 成功 → optional fetch は描画に必要なので起動される (2 波目)。
    expect(apiMocks.loadProjects).toHaveBeenCalledTimes(1);
    expect(apiMocks.getCurrentProject).toHaveBeenCalled();
    expect(apiMocks.fetchDateContext).toHaveBeenCalled();
    expect(apiMocks.fetchAssignableActors).toHaveBeenCalled();
  });

  it("all-view で loadProjectsAllView が degraded でも optional fetch は起動する (reject しない経路)", async () => {
    // all-view は reject しない (degraded に倒れる)。optional は degraded でも描画に使うため起動する。
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: [], omittedProjects: 0, degraded: true });

    render(await renderPage());

    expect(apiMocks.getCurrentProject).toHaveBeenCalled();
    expect(apiMocks.fetchDateContext).toHaveBeenCalled();
    expect(apiMocks.fetchAssignableActors).toHaveBeenCalled();
    // degraded 警告が出る (silent empty にしない)。
    expect(
      screen.getByText(/プロジェクト一覧を取得できなかったため/)
    ).toBeInTheDocument();
  });
});

describe("TicketsKanbanPage Wave 2 all view 並列 ticket fetch (A-3)", () => {
  it("project ごとの loadTickets が並列に走る (逐次退行を捕捉)", async () => {
    const projects = [
      project("a1", "alpha", "Alpha"),
      project("a2", "beta", "Beta"),
      project("a3", "gamma", "Gamma")
    ];
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: projects, omittedProjects: 0, degraded: false });

    const tracker = makeInFlightTracker();
    apiMocks.loadTickets.mockImplementation(async (pid: string) =>
      tracker.run(board([item(`t-${pid.slice(-2)}`, `タスク-${pid.slice(-2)}`)]))
    );

    render(await renderPage());

    // 3 project の loadTickets が同時 in-flight = 並列 (逐次なら 1)。
    expect(tracker.max).toBe(3);
    expect(apiMocks.loadTickets).toHaveBeenCalledTimes(3);
  });

  it("project 数が上限超でも同時実行数を BOARD_FETCH_CONCURRENCY (=3) で bound する (無制限 fan-out 防止)", async () => {
    // page.tsx の BOARD_FETCH_CONCURRENCY=3 と一致 (backend DB pool=10 の十分下に抑える)。
    // 8 project でも同時 fetch は 3 で頭打ち。
    const projects = Array.from({ length: 8 }, (_, i) =>
      project(`b${i}`, `proj-${i}`, `Proj ${i}`)
    );
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: projects, omittedProjects: 0, degraded: false });

    const tracker = makeInFlightTracker();
    apiMocks.loadTickets.mockImplementation(async (pid: string) =>
      tracker.run(board([item(`t-${pid.slice(-2)}`, `タスク-${pid.slice(-2)}`)]))
    );

    render(await renderPage());

    // 8 project すべて fetch されるが、同時 in-flight は 3 で bound (無制限 fan-out しない)。
    expect(apiMocks.loadTickets).toHaveBeenCalledTimes(8);
    expect(tracker.max).toBe(3);
  });

  it("並列でも全 project の ticket を projects 順に集約する", async () => {
    const projects = [
      project("a1", "alpha", "Alpha"),
      project("a2", "beta", "Beta")
    ];
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: projects, omittedProjects: 0, degraded: false });
    apiMocks.loadTickets.mockImplementation(async (pid: string) => {
      if (pid.endsWith("a1")) return board([item("t-alpha", "アルファ課題")]);
      return board([item("t-beta", "ベータ課題")]);
    });

    render(await renderPage());

    expect(screen.getByText("アルファ課題")).toBeInTheDocument();
    expect(screen.getByText("ベータ課題")).toBeInTheDocument();
  });

  it("並列でも 1 project の障害は per-project omission に留め、他 project は表示する (fail-soft 維持)", async () => {
    const projects = [
      project("a1", "alpha", "Alpha"),
      project("a2", "beta", "Beta")
    ];
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: projects, omittedProjects: 0, degraded: false });
    apiMocks.loadTickets.mockImplementation(async (pid: string) => {
      if (pid.endsWith("a2")) throw new Error("backend down for beta");
      return board([item("t-alpha", "アルファ課題")]);
    });

    render(await renderPage());

    // 生存 project は表示、欠落 project は warning で可視化 (1 件)。
    expect(screen.getByText("アルファ課題")).toBeInTheDocument();
    expect(
      screen.getByText(/1 件のプロジェクトのチケットを取得できなかったため/)
    ).toBeInTheDocument();
  });

  it("pid 欠落 project は omission に数えず skip する (現状の continue と同値)", async () => {
    const projects = [
      project("a1", "alpha", "Alpha"),
      { slug: "broken", name: "Broken", status: "active" } // project_id / id 欠落
    ];
    apiMocks.loadProjectsAllView.mockResolvedValue({ items: projects, omittedProjects: 0, degraded: false });
    apiMocks.loadTickets.mockImplementation(async () => board([item("t-alpha", "アルファ課題")]));

    render(await renderPage());

    // pid 欠落 project は loadTickets を呼ばず (continue 相当)、omission warning も出さない。
    expect(apiMocks.loadTickets).toHaveBeenCalledTimes(1);
    expect(
      screen.queryByText(/件のプロジェクトのチケットを取得できなかったため/)
    ).not.toBeInTheDocument();
    expect(screen.getByText("アルファ課題")).toBeInTheDocument();
  });
});
