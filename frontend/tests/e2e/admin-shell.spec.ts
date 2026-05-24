import { expect, test } from "@playwright/test";

function readDevLoginToken(): string {
  return process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ?? process.env.DEV_LOGIN_TOKEN ?? "dev-login-token";
}

test("login renders the admin dashboard shell and exposes the logout skeleton", async ({ page }) => {
  await page.goto("/login?next=/dashboard");

  await page.getByLabel("Dev login token").fill(readDevLoginToken());
  await page.getByRole("button", { name: /^(ログイン|Sign in)$/u }).click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "管理ナビゲーション" })).toBeVisible();

  const dashboardLink = page.getByRole("link", { name: "ダッシュボード" });
  await expect(dashboardLink).toHaveAttribute("aria-current", "page");

  const logoutLink = page.getByRole("link", { name: "ログアウト" });
  await expect(logoutLink).toBeVisible();
  await expect(logoutLink).toHaveAttribute("href", "/login");

  await logoutLink.click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
});
