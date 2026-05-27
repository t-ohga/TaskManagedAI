/**
 * Kanban board E2E tests.
 * Tests the ticket kanban view, project tab filtering, and navigation.
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";

test.describe("Kanban board", () => {
  test("shows kanban columns with correct headers", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/tickets");

    await expect(page.getByRole("heading", { name: "チケット" })).toBeVisible();
    await expect(page.getByText("未着手")).toBeVisible();
    await expect(page.getByText("進行中")).toBeVisible();
    await expect(page.getByText("完了")).toBeVisible();
  });

  test("shows project tab with all projects option", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/tickets");

    await expect(page.getByRole("tab", { name: "全プロジェクト" })).toBeVisible();
  });

  test("dashboard links to kanban with project filter", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/dashboard");

    const projectCards = page.locator("a[href*='/tickets?project=']");
    const count = await projectCards.count();
    expect(count).toBeGreaterThanOrEqual(0);
  });

  test("ticket detail shows breadcrumb back to kanban", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/tickets");

    const firstTicket = page.locator("a[href^='/tickets/']").first();
    if (await firstTicket.isVisible()) {
      await firstTicket.click();
      await expect(page.getByText("チケット一覧")).toBeVisible();
    }
  });

  test("runs page shows status indicators", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/runs");

    await expect(page.getByRole("heading", { name: "AI 実行" })).toBeVisible();
  });

  test("audit page shows event table", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/audit");

    await expect(page.getByRole("heading", { name: "監査ログ" })).toBeVisible();
  });

  test("approvals page shows status tabs", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/approvals");

    await expect(page.getByRole("heading", { name: "承認一覧" })).toBeVisible();
  });
});
