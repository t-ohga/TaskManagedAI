/**
 * Sprint 9 BL-0111: Playwright E2E for Sprint 9 admin pages.
 *
 * Sprint 9 batches 1-2 で実装した 6 page (Tickets / Runs / Audit / Settings +
 * dynamic [id] routes) が Server Component で render され、ARIA label /
 * heading / navigation が正しく出ることを verify。
 */

import { expect, test, type Locator, type Page } from "@playwright/test";

import { DEV_SESSION_COOKIE_NAME } from "@/lib/auth/dev-login";

// F-P2R1-010 fix: import the canonical cookie name from the auth module
// rather than duplicating the literal string, so future renames cannot drift.
const SESSION_COOKIE_NAME = DEV_SESSION_COOKIE_NAME;

// F-P2R1-001 + F-P2R1-008 fix: exact-set verification of AgentRun 16 states,
// blocked_reason 3 reasons, and ContextSnapshot 10 columns. These are P0
// invariants (#6 / #8) and must not silently change in either direction.
const AGENT_RUN_STATES_16 = [
  "queued",
  "gathering_context",
  "running",
  "generated_artifact",
  "schema_validated",
  "policy_linted",
  "diff_ready",
  "waiting_approval",
  "blocked",
  "provider_refused",
  "provider_incomplete",
  "validation_failed",
  "repair_exhausted",
  "completed",
  "failed",
  "cancelled"
] as const;

const BLOCKED_REASONS_3 = [
  "policy_blocked",
  "budget_blocked",
  "runtime_blocked"
] as const;

const CONTEXT_SNAPSHOT_COLUMNS = [
  "prompt_pack_version",
  "prompt_pack_lock",
  "policy_version",
  "policy_pack_lock",
  "repo_state",
  "tool_manifest",
  "evidence_set_hash",
  "provider_continuation_ref",
  "provider_request_fingerprint",
  "snapshot_kind"
] as const;

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
  await page.getByRole("button", { name: "ログイン" }).click();
  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
  await waitForDevSessionCookie(page);
}

test("Sprint 9: tickets list page renders with ARIA + heading", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/tickets");

  const ticketsRegion = page.getByRole("region", {
    name: "チケット一覧",
    exact: true
  });

  await expect(ticketsRegion).toHaveCount(1);
  await expect(ticketsRegion).toBeVisible();
  await expect(
    ticketsRegion.getByRole("heading", { name: "チケット一覧", exact: true })
  ).toBeVisible();
  await expect(
    ticketsRegion.getByRole("button", { name: "+ 新規チケット" })
  ).toBeVisible();
});

test("Sprint 9: agent runs list page renders 16 states + 3 blocked reasons", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs");

  const agentRunsRegion = page.getByRole("region", {
    name: "AI 実行",
    exact: true
  });

  await expect(agentRunsRegion).toHaveCount(1);
  await expect(agentRunsRegion).toBeVisible();
  await expect(
    agentRunsRegion.getByRole("heading", { name: "AI 実行", exact: true })
  ).toBeVisible();

  const stateGraph = agentRunsRegion.getByRole("list", {
    name: "AgentRun 16 状態実行グラフ",
    exact: true
  });

  await expect(stateGraph).toHaveCount(1);
  await expect(stateGraph).toBeVisible();
  // F-P2R1-001 fix: exact 16 items + every enum value visible
  await expect(stateGraph.locator("li")).toHaveCount(AGENT_RUN_STATES_16.length);
  for (const state of AGENT_RUN_STATES_16) {
    await expectUniqueCodeText(stateGraph, state);
  }

  const blockedReasons = agentRunsRegion.getByRole("list", {
    name: "blocked_reason 固定サブ分類",
    exact: true
  });

  await expect(blockedReasons).toHaveCount(1);
  await expect(blockedReasons).toBeVisible();
  // F-P2R1-001 fix: exact 3 items + every blocked_reason visible
  await expect(blockedReasons.locator("li")).toHaveCount(BLOCKED_REASONS_3.length);
  for (const reason of BLOCKED_REASONS_3) {
    await expectUniqueCodeText(blockedReasons, reason);
  }
});

test("Sprint 9: audit log page renders event types + no raw secret notice", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/audit");

  const auditRegion = page.getByRole("region", {
    name: "監査ログ",
    exact: true
  });

  await expect(auditRegion).toHaveCount(1);
  await expect(auditRegion).toBeVisible();
  await expect(
    auditRegion.getByRole("heading", { name: "監査ログ", exact: true })
  ).toBeVisible();

  const auditTable = auditRegion.getByRole("table", {
    name: /event_type、actor_id、reason_code/u
  });

  await expect(auditTable).toHaveCount(1);
  await expect(auditTable).toBeVisible();
  // 主要 audit_event 種別
  await expectUniqueCodeText(auditTable, "policy_decision_created");
  await expectUniqueCodeText(auditTable, "secret_canary_detected");
  await expectUniqueCodeText(auditTable, "runner_blocked");
  // F-P3R1-002 fix: reason_code と blocked_reason の列分離を CI 固定する
  await expect(
    auditTable.getByRole("columnheader", { name: "reason_code" })
  ).toBeVisible();
  await expect(
    auditTable.getByRole("columnheader", { name: "blocked_reason" })
  ).toBeVisible();
  // runner_blocked 行は reason_code=dangerous_command と blocked_reason=runtime_blocked の分離
  await expectUniqueCodeText(auditTable, "dangerous_command");
  await expectUniqueCodeText(auditTable, "runtime_blocked");

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
    name: "設定",
    exact: true
  });

  await expect(settingsRegion).toHaveCount(1);
  await expect(settingsRegion).toBeVisible();
  await expect(
    settingsRegion.getByRole("heading", {
      name: "設定",
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
    name: "チケット詳細",
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
  // F-P2R1-008 fix: ContextSnapshot must expose exactly 10 columns (#8 invariant).
  // Test now verifies all 10 column names + total dt count.
  await expect(contextSnapshot.locator("dt")).toHaveCount(
    CONTEXT_SNAPSHOT_COLUMNS.length
  );
  for (const columnKey of CONTEXT_SNAPSHOT_COLUMNS) {
    await expectUniqueDefinitionTerm(contextSnapshot, columnKey);
  }
});

test("Sprint 9: agent run detail dynamic route renders timeline", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs/00000000-0000-4000-8000-000000000002");

  const agentRunDetailRegion = page.getByRole("region", {
    name: "AI 実行詳細",
    exact: true
  });

  await expect(agentRunDetailRegion).toHaveCount(1);
  await expect(agentRunDetailRegion).toBeVisible();

  const eventTimeline = agentRunDetailRegion.getByRole("list", {
    name: "AgentRunEvent 時系列タイムライン",
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

// F-P3R1-001 fix: 不正 route id (UUID 形式違反) で notFound() が走り 404 を返す
// ことを CI で固定する。F-P2R1-007 で導入した UUID guard の fail-closed 経路。
test("Sprint 9: ticket detail rejects non-UUID id with 404", async ({
  page
}) => {
  await loginAsDev(page);
  const response = await page.goto("/tickets/not-a-uuid");
  expect(response?.status()).toBe(404);
});

test("Sprint 9: agent run detail rejects non-UUID id with 404", async ({
  page
}) => {
  await loginAsDev(page);
  const response = await page.goto("/runs/not-a-uuid");
  expect(response?.status()).toBe(404);
});
