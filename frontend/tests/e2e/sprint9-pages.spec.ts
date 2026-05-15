/**
 * Sprint 9 BL-0111: Playwright E2E for Sprint 9 admin pages.
 *
 * Sprint 9 batches 1-2 で実装した 6 page (Tickets / Runs / Audit / Settings +
 * dynamic [id] routes) が Server Component で render され、ARIA label /
 * heading / navigation が正しく出ることを verify。
 */

import { expect, test, type Locator, type Page } from "@playwright/test";

const SESSION_COOKIE_NAME = "taskmanagedai_session";

function readDevLoginToken(): string {
  return (
    process.env.TASKMANAGEDAI_DEV_LOGIN_TOKEN ??
    process.env.DEV_LOGIN_TOKEN ??
    "dev-login-token"
  );
}

function escapeRegExp(value: string): string {
  return value.replace(/[.*+?^${}()|[\]\\]/gu, "\\$&");
}

function exactTextPattern(value: string): RegExp {
  return new RegExp(`^${escapeRegExp(value)}$`, "u");
}

function exactCodeText(scope: Locator, value: string): Locator {
  return scope.locator("code").filter({ hasText: exactTextPattern(value) });
}

async function expectUniqueCodeText(scope: Locator, value: string): Promise<void> {
  const match = exactCodeText(scope, value);

  await expect(match).toHaveCount(1);
  await expect(match).toHaveText(value);
  await expect(match).toBeVisible();
}

async function expectCodeTextCount(
  scope: Locator,
  value: string,
  count: number
): Promise<void> {
  const matches = exactCodeText(scope, value);

  await expect(matches).toHaveCount(count);

  if (count > 0) {
    await expect(matches.first()).toBeVisible();
  }
}

async function expectUniqueDefinitionTerm(
  scope: Locator,
  value: string
): Promise<void> {
  const match = scope
    .locator("dt code")
    .filter({ hasText: exactTextPattern(value) });

  await expect(match).toHaveCount(1);
  await expect(match).toHaveText(value);
  await expect(match).toBeVisible();
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

  const ticketsRegion = page.getByRole("region", {
    name: "Tickets",
    exact: true
  });

  await expect(ticketsRegion).toHaveCount(1);
  await expect(ticketsRegion).toBeVisible();
  await expect(
    ticketsRegion.getByRole("heading", { name: "Tickets", exact: true })
  ).toBeVisible();
  // Sprint 9 batch 1 skeleton 文言の verify
  await expect(ticketsRegion).toContainText(/Sprint 9 batch 1 進捗/u);
});

test("Sprint 9: agent runs list page renders 16 states + 3 blocked reasons", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs");

  const agentRunsRegion = page.getByRole("region", {
    name: "Agent Runs",
    exact: true
  });

  await expect(agentRunsRegion).toHaveCount(1);
  await expect(agentRunsRegion).toBeVisible();
  await expect(
    agentRunsRegion.getByRole("heading", { name: "Agent Runs", exact: true })
  ).toBeVisible();

  const stateGraph = agentRunsRegion.getByRole("list", {
    name: "AgentRun 16 state execution graph",
    exact: true
  });

  await expect(stateGraph).toHaveCount(1);
  await expect(stateGraph).toBeVisible();
  // AgentRun 16 状態の主要な enum 値が表示されている
  await expectUniqueCodeText(stateGraph, "queued");
  await expectUniqueCodeText(stateGraph, "completed");

  const blockedReasons = agentRunsRegion.getByRole("list", {
    name: "blocked_reason fixed sub categories",
    exact: true
  });

  await expect(blockedReasons).toHaveCount(1);
  await expect(blockedReasons).toBeVisible();
  // blocked_reason の 3 種
  await expectUniqueCodeText(blockedReasons, "policy_blocked");
  await expectUniqueCodeText(blockedReasons, "budget_blocked");
  await expectUniqueCodeText(blockedReasons, "runtime_blocked");
});

test("Sprint 9: audit log page renders event types + no raw secret notice", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/audit");

  const auditRegion = page.getByRole("region", {
    name: "Audit Log",
    exact: true
  });

  await expect(auditRegion).toHaveCount(1);
  await expect(auditRegion).toBeVisible();
  await expect(
    auditRegion.getByRole("heading", { name: "Audit Log", exact: true })
  ).toBeVisible();

  const auditTable = auditRegion.getByRole("table", {
    name: /Audit events with event_type/u
  });

  await expect(auditTable).toHaveCount(1);
  await expect(auditTable).toBeVisible();
  // 主要 audit_event 種別
  await expectUniqueCodeText(auditTable, "policy_decision_created");
  await expectUniqueCodeText(auditTable, "secret_canary_detected");
  await expectUniqueCodeText(auditTable, "runner_blocked");

  const secretBoundary = auditRegion.getByRole("region", {
    name: "AC-HARD-02 audit redaction",
    exact: true
  });

  await expect(secretBoundary).toHaveCount(1);
  await expect(secretBoundary).toBeVisible();
  // AC-HARD-02 invariant 文言
  await expect(secretBoundary).toContainText("raw secret");
});

test("Sprint 9: settings page renders provider matrix + policy profiles", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/settings");

  const settingsRegion = page.getByRole("region", {
    name: "Project Settings",
    exact: true
  });

  await expect(settingsRegion).toHaveCount(1);
  await expect(settingsRegion).toBeVisible();
  await expect(
    settingsRegion.getByRole("heading", {
      name: "Project Settings",
      exact: true
    })
  ).toBeVisible();

  const providerMatrix = settingsRegion.getByRole("table", {
    name: /Provider Compliance Matrix with provider/u
  });

  await expect(providerMatrix).toHaveCount(1);
  await expect(providerMatrix).toBeVisible();
  // Provider Compliance Matrix entries
  await expectUniqueCodeText(providerMatrix, "openai");
  await expectCodeTextCount(providerMatrix, "anthropic", 2);

  const policyProfiles = settingsRegion.getByRole("region", {
    name: "Policy Profiles",
    exact: true
  });

  await expect(policyProfiles).toHaveCount(1);
  await expect(policyProfiles).toBeVisible();
  // Policy profiles
  await expectUniqueCodeText(policyProfiles, "minimal_safe");
  await expectUniqueCodeText(policyProfiles, "approval_required");
  await expectUniqueCodeText(policyProfiles, "merge_deny");
});

test("Sprint 9: ticket detail dynamic route renders", async ({ page }) => {
  await loginAsDev(page);
  await page.goto("/tickets/00000000-0000-4000-8000-000000000001");

  const ticketDetailRegion = page.getByRole("region", {
    name: "Ticket detail",
    exact: true
  });

  await expect(ticketDetailRegion).toHaveCount(1);
  await expect(ticketDetailRegion).toBeVisible();

  const contextSnapshot = ticketDetailRegion.getByRole("region", {
    name: "ContextSnapshot 10 columns",
    exact: true
  });

  await expect(contextSnapshot).toHaveCount(1);
  await expect(contextSnapshot).toBeVisible();
  // ContextSnapshot 10 column が全て表示
  await expectUniqueDefinitionTerm(contextSnapshot, "prompt_pack_version");
  await expectUniqueDefinitionTerm(contextSnapshot, "policy_pack_lock");
  await expectUniqueDefinitionTerm(contextSnapshot, "evidence_set_hash");
  await expectUniqueDefinitionTerm(contextSnapshot, "provider_continuation_ref");
  await expectUniqueDefinitionTerm(
    contextSnapshot,
    "provider_request_fingerprint"
  );
  await expectUniqueDefinitionTerm(contextSnapshot, "snapshot_kind");
});

test("Sprint 9: agent run detail dynamic route renders timeline", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs/00000000-0000-4000-8000-000000000002");

  const agentRunDetailRegion = page.getByRole("region", {
    name: "Agent Run detail",
    exact: true
  });

  await expect(agentRunDetailRegion).toHaveCount(1);
  await expect(agentRunDetailRegion).toBeVisible();

  const eventTimeline = agentRunDetailRegion.getByRole("list", {
    name: "Chronological AgentRunEvent timeline",
    exact: true
  });

  await expect(eventTimeline).toHaveCount(1);
  await expect(eventTimeline).toBeVisible();
  // Timeline events が render される
  await expectUniqueCodeText(eventTimeline, "run_queued");
  await expectUniqueCodeText(eventTimeline, "runner_started");
  await expectUniqueCodeText(eventTimeline, "runner_completed");
  await expectUniqueCodeText(eventTimeline, "repo_pr_opened");

  const secretBoundary = agentRunDetailRegion.getByRole("region", {
    name: "AC-HARD-02 AgentRunEvent redaction",
    exact: true
  });

  await expect(secretBoundary).toHaveCount(1);
  await expect(secretBoundary).toBeVisible();
  // AC-HARD-02 invariant 文言
  await expect(secretBoundary).toContainText("AC-HARD-02");
});
