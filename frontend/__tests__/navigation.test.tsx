import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type * as NextNavigation from "next/navigation";

import { Navigation } from "../components/navigation";

vi.mock("@/components/notification-badge", () => ({
  NotificationBadge: () => (
    <a data-testid="notification-badge-link" href="/notifications">
      通知
    </a>
  )
}));

// NavLink は usePathname() で active link を判定する (aria-current="page")。RTL には
// App Router の pathname context がないため、dashboard を現在地として mock する。
vi.mock("next/navigation", async (importActual) => ({
  ...(await importActual<typeof NextNavigation>()),
  usePathname: () => "/dashboard"
}));

describe("Navigation", () => {
  it("renders Japanese admin navigation labels with stable routes", () => {
    render(<Navigation actorLabel="human:default" />);

    const nav = screen.getByRole("navigation", { name: "管理ナビゲーション" });
    const navItems = [
      ["ダッシュボード", "/dashboard"],
      ["導入", "/onboarding"],
      ["Today", "/today"],
      ["実行ログ", "/timeline"],
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
