import { expect, test } from "@playwright/test";

import { revealAdminNav } from "./_helpers/nav";

function readDevLoginToken(): string {
  return process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ?? process.env.DEV_LOGIN_TOKEN ?? "dev-login-token";
}

test("login renders the admin dashboard shell and exposes the logout skeleton", async ({ page }) => {
  await page.goto("/login?next=/dashboard");

  await page.getByLabel("Dev login token").fill(readDevLoginToken());
  await page.getByRole("button", { name: /^(ログイン|Sign in)$/u }).click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
  // モバイル幅では nav はハンバーガーに折りたたまれるため開いてから可視を確認する。
  await revealAdminNav(page);

  // exact 指定なしだと "評価ダッシュボード" にも一致して strict-mode 違反になる。
  const dashboardLink = page.getByRole("link", { name: "ダッシュボード", exact: true });
  await expect(dashboardLink).toHaveAttribute("aria-current", "page");

  const logoutLink = page.getByRole("link", { name: "ログアウト" });
  await expect(logoutLink).toBeVisible();
  await expect(logoutLink).toHaveAttribute("href", "/login");

  await logoutLink.click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
});
