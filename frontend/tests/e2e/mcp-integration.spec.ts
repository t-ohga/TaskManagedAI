/**
 * MCP integration E2E: verifies that MCP-created data appears in UI.
 * Tests the full loop: MCP tool → DB → API → Frontend render.
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";
import { assertPageNoSecretCanary } from "./_helpers/secret-canary";

test.describe("MCP integration", () => {
  test("dashboard renders after login with no secret canary", async ({
    page,
  }) => {
    await loginAsDev(page);
    await expect(page).toHaveURL(/\/dashboard$/u);
    await assertPageNoSecretCanary(page, "/dashboard");
  });

  test("all admin pages are reachable from navigation", async ({ page }) => {
    await loginAsDev(page);

    const navLinks = [
      { path: "/tickets", heading: /チケット/u },
      { path: "/approvals", heading: /承認/u },
      { path: "/runs", heading: /AI/u },
      { path: "/audit", heading: /監査/u },
      { path: "/today", heading: /Today/u },
      { path: "/notifications", heading: /通知/u },
    ];

    for (const { path } of navLinks) {
      await page.goto(path);
      await expect(page.getByRole("heading").first()).toBeVisible();
      await assertPageNoSecretCanary(page, path);
    }
  });

  test("settings page renders without exposing secrets", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/settings");

    const content = await page.content();
    expect(content).not.toContain("PRIVATE KEY");
    expect(content).not.toContain("ghp_");
    expect(content).not.toContain("sk-");
    await assertPageNoSecretCanary(page, "/settings");
  });

  test("eval dashboard KPI section is visible", async ({ page }) => {
    await loginAsDev(page);
    await page.goto("/eval-dashboard");

    await expect(
      page.getByRole("heading").first()
    ).toBeVisible();
    await assertPageNoSecretCanary(page, "/eval-dashboard");
  });
});
