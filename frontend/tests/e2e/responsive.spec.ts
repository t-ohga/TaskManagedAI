/**
 * Sprint 11.5 batch 4 (BL-0109a): responsive mobile-first viewport test.
 *
 * Sprint Pack の "Tailwind grid + 768/1024/1440px Playwright viewport test"
 * 受け入れ条件 trace。layout / navigation / 主要 region が各 viewport で
 * accessibility 名前付きで render されることを verify。
 *
 * Tailwind の標準 breakpoint:
 * - sm: 640px (mobile landscape)
 * - md: 768px (tablet portrait) — SP-011-5 batch 4 minimum
 * - lg: 1024px (desktop small)
 * - xl: 1280px
 * - 2xl: 1536px (desktop large、~1440 で cover)
 *
 * Sprint 11.5 batch 4 では `lg` 以上の navigation horizontal flex を
 * mobile/tablet で base layout が破綻しないかも確認する (navigation 自体は
 * `lg:flex-row` の base flex-col)。
 *
 * Note: < 768px (smaller viewport) は Sprint Pack の defer 範囲 (SP-022 へ)。
 */

import { expect, test, type Page } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";

const VIEWPORTS = [
  { name: "tablet portrait", width: 768, height: 1024 },
  { name: "desktop small", width: 1024, height: 768 },
  { name: "desktop large", width: 1440, height: 900 }
] as const;

const PROTECTED_ROUTES = [
  { path: "/dashboard", label: "ダッシュボード" },
  { path: "/onboarding", label: "初回導線" },
  { path: "/tickets", label: "チケット" },
  { path: "/approvals", label: "承認待ち" },
  { path: "/runs", label: "AI 実行" },
  { path: "/audit", label: "監査ログ" },
  { path: "/settings", label: "設定" }
] as const;

async function expectMainAndNavigationVisible(page: Page): Promise<void> {
  await expect(page.locator("main")).toBeVisible();
  await expect(page.getByRole("navigation", { name: "管理ナビゲーション" })).toBeVisible();
}

async function expectNoHorizontalOverflow(page: Page): Promise<void> {
  // overflow は **settled (hydration / client data load 完了後) のページ** で測定する。
  // 主要ページの load 直後はデータ取得に伴う一時的レイアウトシフトで数 px の transient overflow が
  // 出ることがあり (settled では解消)、それを responsive 破綻と誤検出しないよう networkidle を待つ。
  // 永続的な overflow は settled 後も残るため引き続き検出できる。
  await page.waitForLoadState("networkidle").catch(() => {
    // networkidle に到達しない (長時間 polling 等) 場合も overflow 測定は続行する。
  });
  // window.innerWidth と document.documentElement.scrollWidth がほぼ同等
  // (≤ 1px、scrollbar / sub-pixel 誤差) であることを verify。
  // 横スクロールが発生していれば overflow と判断 (responsive 破綻)。
  const overflow = await page.evaluate(() => {
    const root = document.documentElement;
    return {
      scroll: root.scrollWidth,
      inner: window.innerWidth
    };
  });
  expect(
    overflow.scroll - overflow.inner,
    `horizontal overflow detected: scroll=${overflow.scroll} inner=${overflow.inner}`
  ).toBeLessThanOrEqual(1);
}

for (const viewport of VIEWPORTS) {
  test.describe(`responsive BL-0109a: viewport ${viewport.name} (${viewport.width}x${viewport.height})`, () => {
    test.use({ viewport: { width: viewport.width, height: viewport.height } });

    test("login page renders without horizontal overflow", async ({ page }) => {
      await page.goto("/login?next=/dashboard");
      await expect(page.getByLabel("Dev login token")).toBeVisible();
      await expectNoHorizontalOverflow(page);
    });

    for (const route of PROTECTED_ROUTES) {
      test(`${route.label} (${route.path}) renders navigation + main without overflow`, async ({
        page
      }) => {
        await loginAsDev(page);
        await page.goto(route.path);
        await expectMainAndNavigationVisible(page);
        await expectNoHorizontalOverflow(page);
      });
    }
  });
}
