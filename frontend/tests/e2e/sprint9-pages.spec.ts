/**
 * Sprint 9 BL-0111: Playwright E2E for Sprint 9 admin pages.
 *
 * Sprint 9 batches 1-2 で実装した 6 page (Tickets / Runs / Audit / Settings +
 * dynamic [id] routes) が Server Component で render され、ARIA label /
 * heading / navigation が正しく出ることを verify。
 */

import { expect, test, type Page } from "@playwright/test";

const SESSION_COOKIE_NAME = "taskmanagedai_session";

function readDevLoginToken(): string {
  return (
    process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ??
    process.env.DEV_LOGIN_TOKEN ??
    "dev-login-token"
  );
}

async function waitForDevSessionCookie(page: Page): Promise<void> {
  await expect
    .poll(
      async () => {
        const cookies = await page.context().cookies();
        return cookies.some(
          (cookie) => cookie.name === SESSION_COOKIE_NAME && cookie.value.length > 0
        );
      },
      {
        message: "Dev session cookie should be persisted before protected route navigation.",
        timeout: 10_000
      }
    )
    .toBe(true);
}

async function loginAsDev(page: Page) {
  await page.goto("/login?next=/dashboard");
  await page.getByLabel("Dev login token").fill(readDevLoginToken());
  await page.getByRole("button", { name: "Sign in" }).click();
  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: /dashboard/i })).toBeVisible();
  await waitForDevSessionCookie(page);
}

test("Sprint 9: tickets list page renders with ARIA + heading", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/tickets");

  await expect(
    page.getByRole("region", { name: "Tickets" })
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Tickets" })).toBeVisible();
  // Sprint 9 batch 1 skeleton 文言の verify
  await expect(page.getByText(/Sprint 9 batch 1 進捗/u)).toBeVisible();
});

test("Sprint 9: agent runs list page renders 16 states + 3 blocked reasons", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs");

  await expect(
    page.getByRole("region", { name: "Agent Runs" })
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Agent Runs" })).toBeVisible();
  // AgentRun 16 状態の主要な enum 値が表示されている
  await expect(page.getByText("queued", { exact: false })).toBeVisible();
  await expect(page.getByText("completed", { exact: false })).toBeVisible();
  // blocked_reason の 3 種
  await expect(page.getByText("policy_blocked")).toBeVisible();
  await expect(page.getByText("budget_blocked")).toBeVisible();
  await expect(page.getByText("runtime_blocked")).toBeVisible();
});

test("Sprint 9: audit log page renders event types + no raw secret notice", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/audit");

  await expect(
    page.getByRole("region", { name: "Audit Log" })
  ).toBeVisible();
  await expect(page.getByRole("heading", { name: "Audit Log" })).toBeVisible();
  // 主要 audit_event 種別
  await expect(page.getByText("policy_decision_created")).toBeVisible();
  await expect(page.getByText("secret_canary_detected")).toBeVisible();
  await expect(page.getByText("runner_blocked")).toBeVisible();
  // AC-HARD-02 invariant 文言
  await expect(page.getByText(/raw secret/u)).toBeVisible();
});

test("Sprint 9: settings page renders provider matrix + policy profiles", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/settings");

  await expect(
    page.getByRole("region", { name: "Project Settings" })
  ).toBeVisible();
  await expect(
    page.getByRole("heading", { name: "Project Settings" })
  ).toBeVisible();
  // Provider Compliance Matrix 4 entries
  await expect(page.getByText("openai")).toBeVisible();
  await expect(page.getByText("anthropic")).toBeVisible();
  // Policy profiles
  await expect(page.getByText("minimal_safe")).toBeVisible();
  await expect(page.getByText("approval_required")).toBeVisible();
  await expect(page.getByText("merge_deny")).toBeVisible();
});

test("Sprint 9: ticket detail dynamic route renders", async ({ page }) => {
  await loginAsDev(page);
  await page.goto("/tickets/00000000-0000-4000-8000-000000000001");

  await expect(
    page.getByRole("region", { name: "Ticket detail" })
  ).toBeVisible();
  // ContextSnapshot 10 column が全て表示
  await expect(page.getByText("prompt_pack_version")).toBeVisible();
  await expect(page.getByText("policy_pack_lock")).toBeVisible();
  await expect(page.getByText("evidence_set_hash")).toBeVisible();
  await expect(page.getByText("provider_continuation_ref")).toBeVisible();
  await expect(page.getByText("provider_request_fingerprint")).toBeVisible();
  await expect(page.getByText("snapshot_kind")).toBeVisible();
});

test("Sprint 9: agent run detail dynamic route renders timeline", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs/00000000-0000-4000-8000-000000000002");

  await expect(
    page.getByRole("region", { name: "Agent Run detail" })
  ).toBeVisible();
  // Timeline events が render される
  await expect(page.getByText("run_queued")).toBeVisible();
  await expect(page.getByText("runner_started")).toBeVisible();
  await expect(page.getByText("runner_completed")).toBeVisible();
  await expect(page.getByText("repo_pr_opened")).toBeVisible();
  // AC-HARD-02 invariant 文言
  await expect(page.getByText(/AC-HARD-02/u)).toBeVisible();
});
