/**
 * Ticket 作成 → 詳細遷移 E2E flow (Mac local docker compose 経由).
 *
 * 検証 flow (現行 UI、UI 監査 G-5 + wrong-project gating 反映):
 * 1. dev login + Tickets list page (見出し「チケット」) 表示確認
 * 2. project tab を順に試し、作成 CTA「+ チケットを作成」が出る current project を選ぶ
 *    (gating: 作成ダイアログは表示中 project == session current_project のときだけ出る)
 * 3. ダイアログで title を入力 → 作成
 * 4. 作成後、作成した ticket 詳細 (/tickets/{id}) へ自動遷移し title が表示される (G-5)
 *
 * 前提:
 * - Mac local docker compose stack 起動済 (api + frontend + postgres + redis + worker)
 * - dogfooding seed apply 済
 *
 * NOTE: 本 spec は現行の ticket 作成ダイアログ + wrong-project gating + G-5 redirect に
 *   合わせて再作成した (旧 spec は SP-012 旧ダイアログの slug/status/testid 前提で drift
 *   していた)。selector は kanban-board.spec.ts の proven pattern と ticket-create-dialog.tsx
 *   の実 markup に基づくが、gating の current-project 探索を含むため、CI 反映前に local
 *   Playwright で 1 度 green を確認すること。
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";

const UNIQUE_TITLE = `E2E Test Ticket ${new Date().toISOString().slice(0, 19)}`;

test.describe("Ticket 作成 → 詳細遷移 (G-5)", () => {
  test("作成後に作成した ticket 詳細へ自動遷移する", async ({ page }) => {
    // 1. login + Tickets list
    await loginAsDev(page);
    await page.goto("/tickets");
    await expect(page.getByRole("heading", { name: "チケット" })).toBeVisible();

    // 2. current project を探す。作成 CTA は current_project を表示中のときだけ出る (gating)。
    const createButton = page.getByRole("button", { name: "+ チケットを作成" });
    const tabs = page.getByRole("tab");
    const tabCount = await tabs.count();

    let openedCurrentProject = false;
    for (let i = 0; i < tabCount; i++) {
      const tab = tabs.nth(i);
      const label = (await tab.textContent())?.trim() ?? "";
      if (label === "全プロジェクト") continue;
      await tab.click();
      await page.waitForURL(/[?&]project=/u, { timeout: 10_000 });
      try {
        await expect(createButton).toBeVisible({ timeout: 3_000 });
        openedCurrentProject = true;
        break;
      } catch {
        // current_project ではない project tab → 作成 CTA は出ず amber notice が出る。
      }
    }
    expect(
      openedCurrentProject,
      "current project tab を選ぶと作成 CTA が表示される (gating)"
    ).toBe(true);

    // 3. ダイアログを開いて title を入力 → 作成
    await createButton.click();
    await page.getByLabel(/タイトル/u).fill(UNIQUE_TITLE);
    await page.getByRole("button", { name: "作成" }).click();

    // 4. G-5: 作成後 /tickets/{id} 詳細へ自動遷移し、作成した title が表示される
    await page.waitForURL(/\/tickets\/[0-9a-f-]+$/u, { timeout: 10_000 });
    await expect(page.getByRole("heading", { name: UNIQUE_TITLE })).toBeVisible();
  });
});
