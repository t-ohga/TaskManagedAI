import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AgentRunsPage from "../app/(admin)/runs/page";

describe("AgentRunsPage i18n", () => {
  it("renders Japanese page labels while preserving AgentRun raw state values", () => {
    render(<AgentRunsPage />);

    const region = screen.getByRole("region", { name: "AI 実行" });
    expect(within(region).getByRole("heading", { name: "AI 実行" })).toBeVisible();
    expect(
      within(region).getByRole("navigation", { name: "キーボード対応管理ナビゲーション" })
    ).toBeVisible();
    expect(within(region).getByRole("link", { name: "AI 実行へ移動" })).toHaveAttribute(
      "aria-current",
      "page"
    );

    const stateGraph = within(region).getByRole("list", {
      name: "AgentRun 16 状態実行グラフ"
    });
    expect(within(stateGraph).getByText("queued")).toBeVisible();
    expect(within(stateGraph).getByText("provider_incomplete")).toBeVisible();

    const blockedReasons = within(region).getByRole("list", {
      name: "blocked_reason 固定サブ分類"
    });
    expect(within(blockedReasons).getByText("runtime_blocked")).toBeVisible();

    expect(
      within(region).getByRole("list", { name: "AgentRunEvent 時系列タイムライン" })
    ).toBeVisible();
  });
});
