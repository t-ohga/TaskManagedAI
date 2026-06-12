import { expect, test, type BrowserContext } from "@playwright/test";

const SESSION_COOKIE_NAME = "taskmanagedai_session";

function readDevLoginToken(): string {
  return process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ?? process.env.DEV_LOGIN_TOKEN ?? "dev-login-token";
}

async function expectBackendIssuedSessionCookie(context: BrowserContext): Promise<void> {
  const cookies = await context.cookies();
  expect(cookies.map((cookie) => cookie.name)).toContain(SESSION_COOKIE_NAME);

  const sessionCookie = cookies.find((cookie) => cookie.name === SESSION_COOKIE_NAME);
  if (!sessionCookie) {
    throw new Error("Backend dev login did not issue a session cookie.");
  }

  expect(sessionCookie.value.split(".")).toHaveLength(2);
  expect(sessionCookie.httpOnly).toBe(true);
  expect(sessionCookie.sameSite).toBe("Lax");
}

test("dev login proxies through the backend and shows the authenticated actor", async ({
  context,
  page
}) => {
  await page.goto("/dashboard");
  await expect(page).toHaveURL(/\/login\?next=%2Fdashboard$/u);

  await page.getByLabel("Dev login token").fill(readDevLoginToken());
  await page.getByRole("button", { name: /^(ログイン|Sign in)$/u }).click();

  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByText("human:default")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "管理ナビゲーション" })).toBeVisible();
  // exact 指定なしだと "評価ダッシュボード" link にも一致して strict-mode 違反になる。
  await expect(
    page.getByRole("link", { name: "ダッシュボード", exact: true })
  ).toHaveAttribute("aria-current", "page");

  await expectBackendIssuedSessionCookie(context);
});
