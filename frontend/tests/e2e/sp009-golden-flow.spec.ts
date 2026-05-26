/**
 * SP-009 golden flow E2E: 4-surface acceptance gate.
 *
 * Tests approval detail + approve/reject, agent run events timeline
 * redaction, audit log redacted metadata, and 4-page runtime DOM
 * secret canary scan.
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";
import { assertPageNoSecretCanary } from "./_helpers/secret-canary";

test.describe.serial("SP-009 golden flow", () => {
  test("approval detail shows approve/reject controls", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/approvals");

    const approvalRegion = page.getByRole("region", {
      name: "承認一覧",
    });
    await expect(approvalRegion).toBeVisible();

    const approvalItemLink = approvalRegion.getByRole("link", {
      name: /approvals\/[0-9a-f-]/u,
    });

    if ((await approvalItemLink.count()) === 0) {
      const itemLink = page.locator('a[href*="/approvals/"]').first();
      if ((await itemLink.count()) > 0) {
        await itemLink.click();
        await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]+$/u);
      }
    } else {
      await approvalItemLink.first().click();
      await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]+$/u);
    }

    if (/\/approvals\/[0-9a-f-]+$/.test(page.url())) {
      const approveButton = page.getByRole("button", { name: /承認/u });
      const rejectButton = page.getByRole("button", { name: /却下/u });

      const hasControls =
        (await approveButton.count()) > 0 ||
        (await rejectButton.count()) > 0;

      expect(
        hasControls,
        "Approval detail must show approve or reject controls"
      ).toBe(true);

      await assertPageNoSecretCanary(page, "/approvals/[id]");
    }
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
    const hasRuns = (await runItemLink.count()) > 0;

    if (hasRuns) {
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
    }
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

    const hasRows = (await auditRegion.getByRole("row").count()) > 1;

    if (hasRows) {
      const content = await page.content();
      expect(content).not.toContain("payload_values");
      expect(content).not.toContain("raw_provider_response");
    }

    await assertPageNoSecretCanary(page, "/audit");
  });

  test("4-page navigation runtime DOM secret scan", async ({ page }) => {
    await loginAsDev(page);

    const pages = [
      { path: "/tickets", label: "チケット" },
      { path: "/approvals", label: "承認" },
      { path: "/runs", label: "AI 実行" },
      { path: "/audit", label: "監査" },
    ];

    for (const { path, label } of pages) {
      await page.goto(path);
      await expect(page.getByRole("heading").first()).toBeVisible();
      await assertPageNoSecretCanary(page, `${label} (${path})`);
    }
  });
});
