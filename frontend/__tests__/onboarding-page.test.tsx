import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import OnboardingPage from "@/app/(admin)/onboarding/page";

const apiMocks = vi.hoisted(() => ({
  getCurrentProject: vi.fn(),
  listCurrentProjects: vi.fn()
}));

vi.mock("@/lib/api/session", () => ({
  getCurrentProject: apiMocks.getCurrentProject,
  listCurrentProjects: apiMocks.listCurrentProjects
}));

afterEach(() => {
  apiMocks.getCurrentProject.mockReset();
  apiMocks.listCurrentProjects.mockReset();
});

describe("OnboardingPage", () => {
  it("renders a read-only first-use path from existing project APIs", async () => {
    const project = buildProject();
    apiMocks.getCurrentProject.mockResolvedValue(project);
    apiMocks.listCurrentProjects.mockResolvedValue({
      current_project_id: project.project_id,
      projects: [project]
    });

    render(await OnboardingPage());

    const region = screen.getByRole("region", { name: "初回導線" });
    expect(within(region).getByRole("heading", { name: "初回導線" })).toBeVisible();

    const readiness = within(region).getByRole("region", { name: "初回チェック" });
    expect(within(readiness).getByText("TaskManagedAI")).toBeVisible();
    expect(within(readiness).getByText("L0")).toBeVisible();
    expect(within(readiness).getByText("policy_profile: default")).toBeVisible();
    expect(within(readiness).getByText("human_required")).toBeVisible();
    expect(within(readiness).getByText("dry-run only")).toBeVisible();

    const choices = within(region).getByRole("region", { name: "安全な最初の選択" });
    expect(within(choices).getByText("AI に調査だけさせる")).toBeVisible();
    expect(within(choices).getByText("計画だけ作らせる")).toBeVisible();
    expect(within(choices).getByText("Draft PR まで作るが承認必須")).toBeVisible();
    expect(within(choices).getAllByText("実行なし")).toHaveLength(2);
    expect(within(choices).getByText("承認必須")).toBeVisible();

    const links = within(region).getByRole("region", { name: "次の確認先" });
    expect(within(links).getByRole("link", { name: "設定を確認" })).toHaveAttribute(
      "href",
      "/settings"
    );
    expect(within(links).getByRole("link", { name: "Today を開く" })).toHaveAttribute(
      "href",
      "/today"
    );
    expect(within(links).getByRole("link", { name: "実行ログを確認" })).toHaveAttribute(
      "href",
      "/timeline"
    );

    expect(screen.getByText("tm run plan --dry-run")).toBeVisible();
    expect(document.body).not.toHaveTextContent("tmai");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("renders a sanitized error state when project context cannot be read", async () => {
    apiMocks.getCurrentProject.mockRejectedValue(new Error("raw stack detail"));
    apiMocks.listCurrentProjects.mockResolvedValue({
      current_project_id: "00000000-0000-4000-8000-00000000c001",
      projects: []
    });

    render(await OnboardingPage());

    const status = screen.getByRole("status");
    expect(status).toHaveTextContent("Project context を確認できません");
    expect(status).toHaveTextContent("プロジェクト情報を取得できません。");
    expect(screen.queryByText("raw stack detail")).not.toBeInTheDocument();
    expect(screen.getByRole("region", { name: "安全な最初の選択" })).toBeVisible();
    expect(screen.getByText("tm run plan --dry-run")).toBeVisible();
    expect(within(status).getByRole("link", { name: "設定を確認" })).toHaveAttribute(
      "href",
      "/settings"
    );
  });
});

function buildProject() {
  return {
    tenant_id: 1,
    project_id: "00000000-0000-4000-8000-00000000c001",
    workspace_id: "00000000-0000-4000-8000-00000000c002",
    slug: "taskmanagedai",
    name: "TaskManagedAI",
    status: "active",
    policy_profile: "default",
    autonomy_level: "L0"
  };
}
