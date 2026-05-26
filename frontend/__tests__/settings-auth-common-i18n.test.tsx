import { render, screen, within } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

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

    render(ProjectSettingsPage());

    const region = screen.getByRole("region", { name: "Project Settings" });
    expect(within(region).getByRole("heading", { name: "Project Settings" })).toBeVisible();
    expect(within(region).getByText("allowed_data_class")).toBeVisible();
    expect(within(region).getByRole("heading", { name: "Provider Compliance Matrix" })).toBeVisible();
  });

  it("renders Japanese dashboard labels and backend unavailable state", async () => {
    apiMocks.getBackendHealth.mockRejectedValueOnce(new Error("Backend healthcheck に失敗しました。"));

    await renderAsync(DashboardPage());

    expect(screen.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
    expect(screen.getByRole("region", { name: "サービス状態" })).toBeVisible();
    expect(screen.getByText("利用不可")).toBeVisible();
    expect(screen.getByRole("status")).toHaveTextContent("Backend healthcheck に失敗しました。");
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
