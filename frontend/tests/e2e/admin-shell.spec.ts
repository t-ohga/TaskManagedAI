import { expect, test } from "@playwright/test";

function readDevLoginToken(): string {
  return process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ?? process.env.DEV_LOGIN_TOKEN ?? "dev-login-token";
}

test("login renders the admin dashboard shell and exposes the logout skeleton", async ({ page }) => {
  await page.goto("/login?next=/dashboard");

  await page.getByLabel("Dev login token").fill(readDevLoginToken());
  await page.getByRole("button", { name: "Sign in" }).click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
  await expect(page.getByRole("navigation", { name: "Admin" })).toBeVisible();

  const dashboardLink = page.getByRole("link", { name: "Dashboard" });
  await expect(dashboardLink).toHaveAttribute("aria-current", "page");

  const logoutLink = page.getByRole("link", { name: "Logout" });
  await expect(logoutLink).toBeVisible();
  await expect(logoutLink).toHaveAttribute("href", "/login");

  await logoutLink.click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
});

