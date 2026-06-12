import { expect, type Page } from "@playwright/test";

/**
 * admin nav landmark (「管理ナビゲーション」) を viewport 非依存で可視化する。
 *
 * モバイル幅 (< md) では nav は MobileNav のハンバーガーに折りたたまれ、menu を開くまで
 * `display:none`。デスクトップ (md+) ではハンバーガー (`md:hidden`) が出ず nav は常時可視。
 * そのため「メニューを開く」ボタンが見えている時だけ開いてから nav の可視を assert する。
 */
export async function revealAdminNav(page: Page): Promise<void> {
  const menuToggle = page.getByRole("button", { name: "メニューを開く" });
  if (await menuToggle.isVisible()) {
    await menuToggle.click();
  }
  await expect(
    page.getByRole("navigation", { name: "管理ナビゲーション" })
  ).toBeVisible();
}
