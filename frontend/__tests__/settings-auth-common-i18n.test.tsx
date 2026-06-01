import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type * as NextNavigation from "next/navigation";

import type { HealthResponse } from "@/lib/api/types";

const apiMocks = vi.hoisted(() => ({
  getBackendHealth: vi.fn<() => Promise<HealthResponse>>(),
  getCurrentProject: vi.fn(),
  listCurrentProjects: vi.fn(),
  listNotificationTriage: vi.fn()
}));

vi.mock("@/lib/api/client", () => ({
  getBackendHealth: apiMocks.getBackendHealth
}));

vi.mock("@/lib/api/notifications", () => ({
  listNotificationTriage: apiMocks.listNotificationTriage
}));

vi.mock("@/lib/api/session", () => ({
  getCurrentProject: apiMocks.getCurrentProject,
  listCurrentProjects: apiMocks.listCurrentProjects
}));

// settings / dashboard は useRouter を使う client component (AutoRefresh 等) を含む。
// App Router context のない RTL 環境では useRouter が "app router to be mounted" invariant
// を投げるため、no-op router を mock する。usePathname など他 export は importActual で残す。
vi.mock("next/navigation", async (importActual) => ({
  ...(await importActual<typeof NextNavigation>()),
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() }),
  // dashboard の range selector client component は useSearchParams().get() を呼ぶ。
  // RTL では実 useSearchParams が null を返すため空の URLSearchParams を返す。
  useSearchParams: () => new URLSearchParams()
}));

import DashboardPage from "../app/(admin)/dashboard/page";
import NotificationsPage from "../app/(admin)/notifications/page";
import ProjectSettingsPage from "../app/(admin)/settings/page";
import LoginPage from "../app/(auth)/login/page";
import AppErrorPage from "../app/error";
import Loading from "../app/loading";
import NotFound from "../app/not-found";
import HomePage from "../app/page";

beforeEach(() => {
  apiMocks.getBackendHealth.mockReset();
  apiMocks.getCurrentProject.mockReset();
  apiMocks.listCurrentProjects.mockReset();
  apiMocks.listNotificationTriage.mockReset();
});

async function renderAsync(element: Promise<ReactElement>) {
  render(await element);
}

describe("settings/auth/common i18n", () => {
  it("renders Japanese labels on the settings page while preserving technical identifiers", async () => {
    const currentProject = {
      tenant_id: 1,
      project_id: "00000000-0000-4000-8000-00000000c001",
      workspace_id: "00000000-0000-4000-8000-00000000c002",
      slug: "taskmanagedai",
      name: "TaskManagedAI"
    };
    apiMocks.getCurrentProject.mockResolvedValueOnce(currentProject);
    apiMocks.listCurrentProjects.mockResolvedValueOnce({
      current_project_id: currentProject.project_id,
      projects: [
        {
          ...currentProject,
          status: "active",
          policy_profile: "default",
          autonomy_level: "L0"
        }
      ]
    });

    // ProjectSettingsPage は async Server Component なので await してから render する。
    render(await ProjectSettingsPage());

    // region / heading は i18n で日本語化済 (regionLabel / title="プロジェクト設定")。
    const region = screen.getByRole("region", { name: "プロジェクト設定" });
    expect(within(region).getByRole("heading", { name: "プロジェクト設定" })).toBeVisible();
    // allowed_data_class は canonical な technical identifier として保持する (翻訳しない)。
    expect(within(region).getByText("allowed_data_class")).toBeVisible();
    expect(within(region).getByRole("heading", { name: "プロバイダー準拠マトリクス" })).toBeVisible();
  });

  it("renders Japanese dashboard labels and backend unavailable state", async () => {
    apiMocks.getBackendHealth.mockRejectedValueOnce(new Error("Backend healthcheck に失敗しました。"));

    // DashboardPage は searchParams (range filter) を必須 prop に持つ async Server Component。
    await renderAsync(DashboardPage({ searchParams: Promise.resolve({}) }));

    expect(screen.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
    expect(screen.getByRole("region", { name: "サービス状態" })).toBeVisible();
    expect(screen.getByText("利用不可")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Backend healthcheck に失敗しました。");
    // listCurrentProjects 未 mock → 取得失敗 → project counts は degraded 表示にし、
    // 「真の 0 件」と区別する (Codex adversarial R2)。
    expect(screen.getByText("プロジェクト一覧を取得できませんでした")).toBeVisible();
  });

  it("distinguishes a real-empty project list (0) from a project fetch failure (—)", async () => {
    apiMocks.getBackendHealth.mockRejectedValueOnce(new Error("ignored for this assertion"));
    // validated response が空配列 = 真に 0 件 (取得失敗ではない)。
    apiMocks.listCurrentProjects.mockResolvedValueOnce({
      current_project_id: "00000000-0000-4000-8000-00000000c001",
      projects: []
    });

    await renderAsync(DashboardPage({ searchParams: Promise.resolve({}) }));

    // 「プロジェクト数」card は 0 を表示し、failure 用の degraded メッセージは出さない。
    const projectCountCard = screen.getByText("プロジェクト数").closest("article");
    expect(projectCountCard).not.toBeNull();
    if (projectCountCard) {
      expect(within(projectCountCard).getByText("0")).toBeVisible();
    }
    expect(screen.queryByText("プロジェクト一覧を取得できませんでした")).not.toBeInTheDocument();
  });

  it("shows — (not 0) for a project whose per-project ticket count fetch fails", async () => {
    apiMocks.getBackendHealth.mockRejectedValueOnce(new Error("ignored for this assertion"));
    // listCurrentProjects は成功 (1 project)。ただし per-project /tickets fetch は失敗する
    // (この test では fetchBackendRaw 未 mock → throw → ticketCount=null)。ticket_summary 等の
    // 他経路が非ゼロでも、該当 project の件数は「0」ではなく「—」で degraded 表示にする。
    apiMocks.listCurrentProjects.mockResolvedValueOnce({
      current_project_id: "00000000-0000-4000-8000-00000000c001",
      projects: [
        {
          tenant_id: 1,
          project_id: "00000000-0000-4000-8000-00000000c001",
          workspace_id: "00000000-0000-4000-8000-00000000c002",
          slug: "taskmanagedai",
          name: "TaskManagedAI",
          description: null,
          status: "active",
          policy_profile: "default",
          autonomy_level: "L0"
        }
      ]
    });

    await renderAsync(DashboardPage({ searchParams: Promise.resolve({}) }));

    // プロジェクト一覧 section 内の該当 project card は件数を「—」で表示し、「0」は出さない。
    const projectSection = screen.getByRole("region", { name: "プロジェクト横断サマリー" });
    expect(within(projectSection).getByText("—")).toBeVisible();
    expect(within(projectSection).queryByText("0")).not.toBeInTheDocument();
  });

  it("renders Japanese empty state on notifications", async () => {
    apiMocks.listNotificationTriage.mockResolvedValueOnce([]);

    await renderAsync(NotificationsPage());

    const region = screen.getByRole("region", { name: "通知" });
    expect(within(region).getByRole("heading", { name: "通知" })).toBeVisible();
    expect(within(region).getByText("通知はありません。")).toBeVisible();
  });

  it("renders Japanese login heading and error messages", async () => {
    await renderAsync(
      LoginPage({
        searchParams: Promise.resolve({ error: "invalid-request" })
      })
    );

    expect(screen.getByRole("heading", { name: "Dev ログイン" })).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("ログインリクエストが不正です。");
    expect(screen.getByRole("button", { name: "ログイン" })).toBeVisible();
  });

  it("renders Japanese root page navigation and actions", () => {
    render(<HomePage />);

    expect(screen.getByRole("navigation", { name: "主要ナビゲーション" })).toBeVisible();
    expect(screen.getByRole("link", { name: "ログイン" })).toHaveAttribute("href", "/login");
    expect(screen.getByRole("link", { name: "ダッシュボード" })).toHaveAttribute(
      "href",
      "/dashboard"
    );
    expect(screen.getByRole("link", { name: "ダッシュボードを開く" })).toHaveAttribute(
      "href",
      "/dashboard"
    );
    expect(screen.getByRole("link", { name: "ヘルスチェック" })).toHaveAttribute(
      "href",
      "/api/healthz"
    );
  });

  it("renders Japanese loading, not-found, and error states", () => {
    const loading = render(<Loading />);
    expect(screen.getByRole("status")).toHaveTextContent("読み込み中です...");

    loading.unmount();
    const notFound = render(<NotFound />);
    expect(screen.getByRole("heading", { name: "ページが見つかりません" })).toBeVisible();
    expect(screen.getByRole("link", { name: "ダッシュボードへ戻る" })).toHaveAttribute(
      "href",
      "/dashboard"
    );

    notFound.unmount();
    const reset = vi.fn();
    const error = Object.assign(new Error("boom"), { digest: "digest-123" });
    render(<AppErrorPage error={error} reset={reset} />);
    expect(screen.getByRole("heading", { name: "画面の表示に失敗しました" })).toBeVisible();
    expect(screen.getByText("digest: digest-123")).toBeVisible();
    expect(screen.getByRole("button", { name: "再試行" })).toBeVisible();
  });
});
