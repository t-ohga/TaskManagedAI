import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { Navigation } from "../components/navigation";

vi.mock("@/components/notification-badge", () => ({
  NotificationBadge: () => (
    <a data-testid="notification-badge-link" href="/notifications">
      通知
    </a>
  )
}));

describe("Navigation", () => {
  it("renders Japanese admin navigation labels with stable routes", () => {
    render(<Navigation actorLabel="human:default" />);

    const nav = screen.getByRole("navigation", { name: "管理ナビゲーション" });
    const navItems = [
      ["ダッシュボード", "/dashboard"],
      ["Today", "/today"],
      ["チケット", "/tickets"],
      ["評価ダッシュボード", "/eval-dashboard"],
      ["承認待ち", "/approvals"],
      ["AI 実行", "/runs"],
      ["AI 組織", "/orchestrator/board"],
      ["監査ログ", "/audit"],
      ["設定", "/settings"],
      ["ログアウト", "/login"]
    ] as const;

    for (const [name, href] of navItems) {
      expect(within(nav).getByRole("link", { name })).toHaveAttribute("href", href);
    }

    expect(within(nav).getByRole("link", { name: "ダッシュボード" })).toHaveAttribute(
      "aria-current",
      "page"
    );
    expect(screen.getByText("human:default")).toBeVisible();
    expect(screen.getByRole("link", { name: "通知" })).toHaveAttribute(
      "href",
      "/notifications"
    );
  });
});
