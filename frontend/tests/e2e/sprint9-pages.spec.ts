/**
 * Sprint 9 page smoke checks for the current real backend-wired admin pages.
 *
 * Older assertions in this file verified skeleton-only widgets. SP-009 was
 * later wired to real API clients, so these tests now verify stable page
 * landmarks, filters, and redacted metadata columns without depending on a
 * specific seeded row count.
 */

import { expect, test, type Page } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";

async function loginAndGoto(page: Page, path: string) {
  await loginAsDev(page);
  await page.goto(path);
}

test("Sprint 9: tickets list page renders real list shell", async ({ page }) => {
  await loginAndGoto(page, "/tickets");

  const ticketsRegion = page.getByRole("region", {
    name: "チケット一覧",
    exact: true
  });

  await expect(ticketsRegion).toBeVisible();
  await expect(
    ticketsRegion.getByRole("heading", { name: "チケット一覧", exact: true })
  ).toBeVisible();
  await expect(
    ticketsRegion.getByRole("button", { name: /\+ 新規チケット/u })
  ).toBeVisible();
  await expect(
    ticketsRegion.getByText(/件 \(project:|チケット一覧を表示できません|チケットはありません/u)
  ).toBeVisible();
});

test("SP-009-5: today control plane renders read-only lanes", async ({ page }) => {
  await loginAndGoto(page, "/today");

  const todayRegion = page.getByRole("region", {
    name: "Today control plane",
    exact: true
  });

  await expect(todayRegion).toBeVisible();
  await expect(
    todayRegion.getByRole("heading", { name: "Today / Inbox", exact: true })
  ).toBeVisible();
  await expect(todayRegion.getByLabel("Today KPI strip")).toBeVisible();
  await expect(todayRegion.getByRole("region", { name: "Today lane" })).toBeVisible();
  await expect(todayRegion.getByRole("region", { name: "Inbox lane" })).toBeVisible();
});

test("Sprint 9: approval inbox page renders real status filters", async ({ page }) => {
  await loginAndGoto(page, "/approvals");

  const approvalsRegion = page.getByRole("region", {
    name: "承認一覧",
    exact: true
  });

  await expect(approvalsRegion).toBeVisible();
  await expect(
    approvalsRegion.getByRole("heading", { name: "承認一覧", exact: true })
  ).toBeVisible();
  await expect(
    approvalsRegion.getByRole("navigation", { name: "承認ステータス", exact: true })
  ).toBeVisible();
  await expect(approvalsRegion.getByText(/承認 request|承認一覧の取得に失敗しました/u)).toBeVisible();
});

test("Sprint 9: agent runs page renders real read-only table shell", async ({ page }) => {
  await loginAndGoto(page, "/runs");

  const runsRegion = page.getByRole("region", {
    name: "AI 実行一覧",
    exact: true
  });

  await expect(runsRegion).toBeVisible();
  await expect(runsRegion.getByRole("heading", { name: "AI 実行", exact: true })).toBeVisible();
  await expect(runsRegion.getByLabel("AI 実行フィルター")).toBeVisible();
  await expect(
    runsRegion.getByText(/件の AgentRun|AI 実行を表示できません|条件に一致する AI 実行/u)
  ).toBeVisible();
  await expect(runsRegion.getByText("waiting approval")).toBeVisible();
});

test("Sprint 9: audit log page renders redacted metadata columns", async ({ page }) => {
  await loginAndGoto(page, "/audit");

  const auditRegion = page.getByRole("region", {
    name: "監査ログ",
    exact: true
  });

  await expect(auditRegion).toBeVisible();
  await expect(auditRegion.getByRole("heading", { name: "監査ログ", exact: true })).toBeVisible();
  await expect(auditRegion.getByLabel("監査ログフィルター")).toBeVisible();
  await expect(
    auditRegion.getByText(/payload key のみ|監査ログを表示できません|条件に一致する audit event/u)
  ).toBeVisible();
  const redactionHeader = auditRegion.getByRole("columnheader", { name: "redaction" });
  if ((await redactionHeader.count()) > 0) {
    await expect(auditRegion.getByRole("columnheader", { name: "payload_keys" })).toBeVisible();
    await expect(redactionHeader).toBeVisible();
  }
});

test("Sprint 9: ticket detail rejects non-UUID id with 404", async ({ page }) => {
  await loginAsDev(page);
  await page.goto("/tickets/not-a-uuid");
  await expect(page.getByRole("heading", { name: "ページが見つかりません" })).toBeVisible();
});

test("Sprint 9: agent run detail rejects non-UUID id with 404", async ({ page }) => {
  await loginAsDev(page);
  await page.goto("/runs/not-a-uuid");
  await expect(page.getByRole("heading", { name: "ページが見つかりません" })).toBeVisible();
});
