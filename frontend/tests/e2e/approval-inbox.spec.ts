import { expect, test } from "@playwright/test";

const APPROVAL_RENDER_TEXT =
  /no pending approvals|failed to load approvals|task_write|repo_write|pr_open|secret_access|merge|deploy|provider_call/i;

function readDevLoginToken(): string {
  return process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ?? process.env.DEV_LOGIN_TOKEN ?? "dev-login-token";
}

test.describe("Approval Inbox", () => {
  test("renders Approval Inbox page after login", async ({ page }) => {
    await page.goto("/login?next=/dashboard");

    await page.getByLabel("Dev login token").fill(readDevLoginToken());
    await page.getByRole("button", { name: "Sign in" }).click();

    await expect(page).toHaveURL(/\/dashboard$/u);

    await page.goto("/approvals");
    await expect(page.getByRole("heading", { name: /approval inbox/i })).toBeVisible();
    await expect(page.getByText(APPROVAL_RENDER_TEXT).first()).toBeVisible();
  });
});

