/**
 * Sprint 11.5 batch 4 (BL-0109a / BL-0110a): shared E2E login helper.
 *
 * Sprint 9 sprint9-pages.spec.ts と同じ pattern。dev-login token を投入し
 * session cookie が persist されるまで待機する。a11y / responsive test で
 * 重複させないよう module 化。
 */

import { expect, type Page } from "@playwright/test";

import { DEV_SESSION_COOKIE_NAME } from "@/lib/auth/dev-login";

export const SESSION_COOKIE_NAME = DEV_SESSION_COOKIE_NAME;

export function readDevLoginToken(): string {
  return (
    process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ??
    process.env.DEV_LOGIN_TOKEN ??
    "dev-login-token"
  );
}

async function waitForDevSessionCookie(page: Page): Promise<void> {
  await expect
    .poll(
      async () => {
        const cookies = await page.context().cookies();
        return cookies.some(
          (cookie) =>
            cookie.name === SESSION_COOKIE_NAME && cookie.value.length > 0
        );
      },
      {
        message:
          "Dev session cookie should be persisted before protected route navigation.",
        timeout: 10_000
      }
    )
    .toBe(true);
}

export async function loginAsDev(page: Page): Promise<void> {
  await page.goto("/login?next=/dashboard");
  await page.getByLabel("Dev login token").fill(readDevLoginToken());
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
  await waitForDevSessionCookie(page);
}
