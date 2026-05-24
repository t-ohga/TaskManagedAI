import { expect, test } from "@playwright/test";

const APPROVAL_RENDER_TEXT =
  /承認待ちの項目はありません|承認一覧の取得に失敗しました|task_write|repo_write|pr_open|secret_access|merge|deploy|provider_call/u;

function readDevLoginToken(): string {
  return process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ?? process.env.DEV_LOGIN_TOKEN ?? "dev-login-token";
}

test.describe("Approval Inbox", () => {
  test("renders Approval Inbox page after login", async ({ page }) => {
    await page.goto("/login?next=/dashboard");

    await page.getByLabel("Dev login token").fill(readDevLoginToken());
    await page.getByRole("button", { name: /^(ログイン|Sign in)$/u }).click();

    await expect(page).toHaveURL(/\/dashboard$/u);
    // Server Action redirect (x-action-redirect: /dashboard;push) は RSC payload で URL を
    // 即時 update する一方、Set-Cookie の browser cookie jar への永続化は後追いで完了する。
    // toHaveURL は URL match で resolve するが cookie jar は未確定のため、直後の
    // page.goto("/approvals") が cookie 無しで送信されて middleware に /login redirect される。
    // dashboard の heading が visible になるまで wait することで cookie 永続化を保証する
    // (admin-shell.spec.ts が同 pattern で安定動作している実績の踏襲)。
    await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();

    await page.goto("/approvals");
    await expect(page.getByRole("heading", { name: "承認一覧" })).toBeVisible();
    await expect(page.getByText(APPROVAL_RENDER_TEXT).first()).toBeVisible();
  });
});
