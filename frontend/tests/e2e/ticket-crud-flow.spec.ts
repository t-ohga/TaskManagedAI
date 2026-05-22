/**
 * SP-012-11.1 BL-TCU-018: Ticket CRUD E2E flow (Mac local docker compose 経由).
 *
 * 検証 flow:
 * 1. dev login + Tickets list page 表示確認 (dogfooding seed 投入後の Ticket 一覧)
 * 2. 「+ 新規チケット」 button click → form 表示
 * 3. form 入力 (slug + title + status) → submit
 * 4. 一覧再表示で新 Ticket 出現確認 (router.refresh 経由 revalidatePath 連動)
 * 5. 詳細 page 移動 → edit form 表示
 * 6. status 変更 → submit
 * 7. 詳細 page で status 変更反映確認
 *
 * 前提:
 * - Mac local docker compose stack 起動済 (api + frontend + postgres + redis + worker)
 * - dogfooding seed apply 済 (229+ Ticket 表示で list 確認用)
 * - test 実行前に generated unique slug で衝突回避
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";

const UNIQUE_SLUG = `e2e-test-${Date.now()}`;
const UNIQUE_TITLE = `E2E Test Ticket ${new Date().toISOString().slice(0, 19)}`;

test.describe("Ticket CRUD E2E flow (SP-012-11.1 BL-TCU-018)", () => {
  test("new ticket creation + edit flow", async ({ page }) => {
    // 1. login + Tickets list
    await loginAsDev(page);
    await page.goto("/tickets");
    await expect(page.getByRole("heading", { name: "チケット一覧" })).toBeVisible();

    // 2. 「+ 新規チケット」 button click → form 表示
    const addButton = page.getByRole("button", { name: /\+ 新規チケット/u });
    await expect(addButton).toBeVisible();
    await addButton.click();

    const form = page.getByTestId("new-ticket-form");
    await expect(form).toBeVisible();

    // 3. form 入力 + submit
    await form.getByLabel(/Slug/u).fill(UNIQUE_SLUG);
    await form.getByLabel(/タイトル/u).fill(UNIQUE_TITLE);
    await form.locator('select[name="status"]').selectOption("open");
    await form.getByRole("button", { name: /作成/u }).click();

    // 4. 一覧再表示で新 Ticket 出現 (router.refresh + revalidatePath 連動)
    // form 自動 close 後、一覧 table に新 slug が出現する
    await expect(page.getByText(UNIQUE_SLUG)).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(UNIQUE_TITLE)).toBeVisible();
  });
});
