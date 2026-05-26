/**
 * SP-009 golden flow E2E: 4-surface acceptance gate.
 *
 * All assertions are mandatory (no skip-by-count). If seed data is
 * missing, the test fails rather than silently passing.
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";
import { assertPageNoSecretCanary } from "./_helpers/secret-canary";

test.describe.serial("SP-009 golden flow", () => {
  test("approval detail shows both approve and reject controls", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/approvals");

    const approvalRegion = page.getByRole("region", {
      name: "承認一覧",
    });
    await expect(approvalRegion).toBeVisible();

    const itemLink = page.locator('a[href*="/approvals/"]').first();
    await expect(
      itemLink,
      "At least one approval item link must exist for golden flow"
    ).toBeVisible({ timeout: 10_000 });

    await itemLink.click();
    await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]+$/u);

    const approveButton = page.getByRole("button", { name: /承認/u });
    const rejectButton = page.getByRole("button", { name: /却下/u });

    await expect(
      approveButton,
      "Approve button must be visible in approval detail"
    ).toBeVisible();
    await expect(
      rejectButton,
      "Reject button must be visible in approval detail"
    ).toBeVisible();

    await assertPageNoSecretCanary(page, "/approvals/[id]");
  });

  test("agent run detail shows events timeline with redacted payload", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/runs");

    const runsRegion = page.getByRole("region", {
      name: "AI 実行一覧",
    });
    await expect(runsRegion).toBeVisible();

    const runItemLink = page.locator('a[href*="/runs/"]').first();
    await expect(
      runItemLink,
      "At least one agent run link must exist for golden flow"
    ).toBeVisible({ timeout: 10_000 });

    await runItemLink.click();
    await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/u);

    const detail = page.getByRole("region", { name: "AI 実行詳細" });
    await expect(detail).toBeVisible();

    const timelineHeading = page.getByRole("heading", {
      name: /AgentRunEvent タイムライン/u,
    });
    await expect(
      timelineHeading,
      "Events timeline heading must be visible in run detail"
    ).toBeVisible();

    const content = await page.content();
    expect(content).not.toContain("payload_values");

    await assertPageNoSecretCanary(page, "/runs/[id]");
  });

  test("audit log shows redacted metadata without raw secrets", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/audit");

    const auditRegion = page.getByRole("region", {
      name: "監査ログ",
    });
    await expect(auditRegion).toBeVisible();

    const rows = auditRegion.getByRole("row");
    await expect(
      rows,
      "Audit log must have at least one data row for golden flow"
    ).toHaveCount(2, { timeout: 10_000 });

    const content = await page.content();
    expect(content).not.toContain("payload_values");
    expect(content).not.toContain("raw_provider_response");

    await assertPageNoSecretCanary(page, "/audit");
  });

  test("4-page navigation runtime DOM secret scan", async ({ page }) => {
    await loginAsDev(page);

    const pages = [
      { path: "/tickets", urlPattern: /\/tickets$/u },
      { path: "/approvals", urlPattern: /\/approvals$/u },
      { path: "/runs", urlPattern: /\/runs$/u },
      { path: "/audit", urlPattern: /\/audit$/u },
    ];

    for (const { path, urlPattern } of pages) {
      await page.goto(path);
      await expect(page).toHaveURL(urlPattern);
      await expect(page.getByRole("heading").first()).toBeVisible();
      await assertPageNoSecretCanary(page, path);
    }
  });
});
