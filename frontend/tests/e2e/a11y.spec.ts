/**
 * Sprint 11.5 batch 4 (BL-0110a): a11y axe-core integration test.
 *
 * 主要 P0 UI page で WCAG 2.1 AA 違反 0 を verify。Sprint 11.5 Sprint Pack
 * の AC-KPI-03 (Sprint 9 carry-over) trace + axe_violation_detected event
 * trigger 条件。
 *
 * 検証 page (Sprint 9 BL-0103/0104/0105/0106/0107/0108 / login):
 * - /login (auth flow root)
 * - /dashboard
 * - /tickets
 * - /approvals
 * - /runs
 * - /audit
 * - /settings
 *
 * 違反 rule set: wcag2a / wcag2aa / wcag21a / wcag21aa。
 * Critical / serious / moderate / minor を一律 `violations.length === 0`
 * で reject (Sprint Pack の "WCAG 2.1 AA 違反 0")。
 */

import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";

const A11Y_TAGS = ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"] as const;

const PROTECTED_ROUTES = [
  { path: "/dashboard", label: "ダッシュボード" },
  { path: "/tickets", label: "チケット一覧" },
  { path: "/approvals", label: "承認待ち" },
  { path: "/runs", label: "AI 実行" },
  { path: "/audit", label: "監査ログ" },
  { path: "/settings", label: "設定" }
] as const;

test("a11y BL-0110a: /login satisfies WCAG 2.1 AA (no violations)", async ({
  page
}) => {
  await page.goto("/login?next=/dashboard");
  await expect(page.getByLabel("Dev login token")).toBeVisible();

  const results = await new AxeBuilder({ page })
    .withTags([...A11Y_TAGS])
    .analyze();

  // BL-0110a: 違反 0 invariant。発見時は full payload を expect.fail で出して
  // root cause を最短で特定できるようにする (Codex / reviewer 採否判定材料)。
  expect(
    results.violations,
    `axe violations: ${JSON.stringify(results.violations, null, 2)}`
  ).toEqual([]);
});

for (const route of PROTECTED_ROUTES) {
  test(`a11y BL-0110a: ${route.label} (${route.path}) satisfies WCAG 2.1 AA`, async ({
    page
  }) => {
    await loginAsDev(page);
    await page.goto(route.path);

    // ページ render 完了待ち (主要 region / heading が出るまで)
    await expect(page.locator("main")).toBeVisible();

    const results = await new AxeBuilder({ page })
      .withTags([...A11Y_TAGS])
      .analyze();

    expect(
      results.violations,
      `axe violations on ${route.path}: ${JSON.stringify(
        results.violations,
        null,
        2
      )}`
    ).toEqual([]);
  });
}
