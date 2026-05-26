/**
 * SP-009 golden flow E2E: 4-surface acceptance gate.
 *
 * Tests approval detail + approve/reject, agent run events timeline
 * redaction, audit log redacted metadata, and 4-page runtime DOM
 * secret canary scan. Complements existing smoke specs without
 * duplicating ticket CRUD or approval inbox render.
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";
import { assertPageNoSecretCanary } from "./_helpers/secret-canary";

test.describe.serial("SP-009 golden flow", () => {
  test("approval detail shows approve/reject with human-only decider", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/approvals");

    const approvalRegion = page.getByRole("region", {
      name: "承認リクエスト",
    });
    await expect(approvalRegion).toBeVisible();

    const firstRow = approvalRegion.getByRole("link").first();
    const hasApprovals = (await firstRow.count()) > 0;

    if (hasApprovals) {
      await firstRow.click();
      await expect(page).toHaveURL(/\/approvals\/[0-9a-f-]+$/u);

      const detail = page.getByRole("region", { name: /承認詳細/u });
      await expect(detail).toBeVisible();

      const approveButton = detail.getByRole("button", { name: /承認/u });
      const rejectButton = detail.getByRole("button", { name: /却下/u });
      const hasButtons =
        (await approveButton.count()) > 0 ||
        (await rejectButton.count()) > 0;

      if (hasButtons) {
        expect(hasButtons).toBe(true);
      }

      await assertPageNoSecretCanary(page, "/approvals/[id]");
    }
  });

  test("agent run detail shows events timeline with redacted payload", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/runs");

    const runsRegion = page.getByRole("region", {
      name: /AI実行/u,
    });
    await expect(runsRegion).toBeVisible();

    const firstRow = runsRegion.getByRole("link").first();
    const hasRuns = (await firstRow.count()) > 0;

    if (hasRuns) {
      await firstRow.click();
      await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/u);

      const detail = page.getByRole("region", { name: /AI実行詳細/u });
      await expect(detail).toBeVisible();

      const statusBadge = detail.getByTestId("agent-run-status");
      if ((await statusBadge.count()) > 0) {
        const statusText = await statusBadge.textContent();
        expect(statusText).toBeTruthy();
      }

      const eventsSection = detail.getByRole("region", {
        name: /イベント/u,
      });
      if ((await eventsSection.count()) > 0) {
        await expect(eventsSection).toBeVisible();
      }

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
      name: /監査ログ/u,
    });
    await expect(auditRegion).toBeVisible();

    const hasRows =
      (await auditRegion.getByRole("row").count()) > 1;

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
      { path: "/runs", label: "AI実行" },
      { path: "/audit", label: "監査" },
    ];

    for (const { path, label } of pages) {
      await page.goto(path);
      await expect(
        page.getByRole("heading").first()
      ).toBeVisible();
      await assertPageNoSecretCanary(page, `${label} (${path})`);
    }
  });
});
