/**
 * Sprint 9 admin pages, rewritten against the current feature pages.
 *
 * The old Sprint-9 skeleton-only ARIA regions were removed from the product UI.
 * This spec now pins current content invariants that should survive visual and
 * implementation refactors without duplicating broad render/a11y/responsive gates.
 */

import { expect, test, type Locator, type Page } from "@playwright/test";

import { DEV_SESSION_COOKIE_NAME } from "@/lib/auth/dev-login";

test.describe.configure({ mode: "serial" });

const SESSION_COOKIE_NAME = DEV_SESSION_COOKIE_NAME;
const SEEDED_TICKET_ID = "00000000-0000-4000-8000-000000000006";
const UNSEEDED_AGENT_RUN_ID = "00000000-0000-4000-8000-000000000002";
const NOT_FOUND_HEADING = "ページが見つかりません";

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
  await page.getByRole("button", { name: /^(ログイン|Sign in)$/u }).click();
  await expect(page).toHaveURL(/\/dashboard$/u);
  await expect(page.getByRole("heading", { name: "ダッシュボード" })).toBeVisible();
  await waitForDevSessionCookie(page);
}

async function expectNotFoundPage(page: Page): Promise<void> {
  await expect(page.getByRole("heading", { name: NOT_FOUND_HEADING })).toBeVisible();
  await expect(
    page.getByText("指定されたページは存在しないか、移動された可能性があります。")
  ).toBeVisible();
  await expect(page.getByRole("link", { name: "ダッシュボードへ戻る" })).toBeVisible();
}

async function expectPageDoesNotExposeRawPayload(page: Page): Promise<void> {
  const content = await page.content();
  expect(content).not.toContain("payload_values");
  expect(content).not.toContain("raw_provider_response");
}

test("Sprint 9: tickets list page shows the current kanban board invariants", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/tickets");

  const ticketsRegion = page.getByRole("region", {
    name: "チケット看板ボード",
    exact: true
  });

  await expect(ticketsRegion).toHaveCount(1);
  await expect(ticketsRegion).toBeVisible();
  await expect(
    ticketsRegion.getByRole("heading", { level: 1, name: "チケット" })
  ).toBeVisible();
  await expect(ticketsRegion.getByText(/全 \d+ チケット/u)).toBeVisible();

  for (const columnName of ["未着手", "進行中", "完了"]) {
    await expect(
      ticketsRegion.getByRole("heading", { level: 3, name: columnName })
    ).toBeVisible();
  }

  await expect(ticketsRegion.getByRole("link", {
    name: /Welcome to TaskManagedAI/u
  })).toBeVisible();
});

test("Sprint 9: agent runs list page shows current filters and list state", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs");

  const agentRunsRegion = page.getByRole("region", {
    name: "AI 実行一覧",
    exact: true
  });

  await expect(agentRunsRegion).toHaveCount(1);
  await expect(agentRunsRegion).toBeVisible();
  await expect(
    agentRunsRegion.getByRole("heading", { level: 1, name: "AI 実行" })
  ).toBeVisible();
  await expect(agentRunsRegion.getByText(/全 \d+ 実行/u)).toBeVisible();
  await expect(agentRunsRegion.getByText(/アクティブ \d+/u)).toBeVisible();
  await expect(agentRunsRegion.getByText(/完了 \d+/u)).toBeVisible();

  for (const statusLabel of ["すべて", "待機中", "実行中", "承認待ち", "ブロック", "完了", "キャンセル"]) {
    await expect(
      agentRunsRegion.getByRole("link", { name: statusLabel, exact: true })
    ).toBeVisible();
  }

  const emptyState = agentRunsRegion.getByText("AI 実行はまだありません");
  if (await emptyState.isVisible()) {
    await expect(emptyState).toBeVisible();
    await expect(
      agentRunsRegion.getByText(/MCP 経由で run_create を実行/u)
    ).toBeVisible();
  } else {
    await expect(
      agentRunsRegion
        .locator("h2")
        .filter({ hasText: /コスト・トークン集計|アクティブな実行|完了した実行/u })
        .first()
    ).toBeVisible();
  }
});

test("Sprint 9: audit log page shows redacted audit metadata", async ({
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
    auditRegion.getByRole("heading", { level: 1, name: "監査ログ" })
  ).toBeVisible();
  await expect(auditRegion.getByText(/追記専用の監査イベント \(\d+ 件\)/u)).toBeVisible();

  const auditTable = auditRegion.locator("table");

  await expect(auditTable).toHaveCount(1);
  await expect(auditTable).toBeVisible();
  await expect(
    auditTable.getByRole("columnheader", { name: "イベント種別" })
  ).toBeVisible();
  await expect(
    auditTable.getByRole("columnheader", { name: "理由コード" })
  ).toBeVisible();
  await expect(
    auditTable.getByRole("columnheader", { name: "ペイロード" })
  ).toBeVisible();
  await expect(
    auditTable.getByRole("columnheader", { name: "マスク状態" })
  ).toBeVisible();
  await expect(auditTable).toContainText("seed_initialized");
  await expect(auditTable).toContainText("keys_only");

  await expect(auditRegion.getByText("AC-HARD-02 監査マスク")).toBeVisible();
  await expect(auditRegion.getByText(/生のシークレット、トークン/u)).toBeVisible();
  await expectPageDoesNotExposeRawPayload(page);
});

test("Sprint 9: settings page shows provider matrix and policy profiles", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/settings");

  const settingsRegion = page.getByRole("region", {
    name: "プロジェクト設定",
    exact: true
  });

  await expect(settingsRegion).toHaveCount(1);
  await expect(settingsRegion).toBeVisible();
  await expect(
    settingsRegion.getByRole("heading", {
      level: 1,
      name: "プロジェクト設定"
    })
  ).toBeVisible();

  const providerMatrix = settingsRegion.getByRole("table", {
    name: /Provider Compliance Matrix with provider/u
  });

  await expect(providerMatrix).toHaveCount(1);
  await expect(providerMatrix).toBeVisible();
  for (const headerName of [
    "provider",
    "api_or_feature",
    "allowed_data_class",
    "retention",
    "zdr_eligible",
    "training_use"
  ]) {
    await expect(
      providerMatrix.getByRole("columnheader", { name: headerName })
    ).toBeVisible();
  }
  await expectUniqueCodeText(providerMatrix, "openai");
  await expectCodeTextCount(providerMatrix, "anthropic", 2);

  const policyProfiles = settingsRegion.getByRole("region", {
    name: "ポリシープロファイル"
  });

  await expect(policyProfiles).toHaveCount(1);
  await expect(policyProfiles).toBeVisible();
  await expectUniqueCodeText(policyProfiles, "minimal_safe");
  await expectUniqueCodeText(policyProfiles, "approval_required");
  await expectUniqueCodeText(policyProfiles, "merge_deny");
});

test("Sprint 9: ticket detail dynamic route shows seeded ticket content", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto(`/tickets/${SEEDED_TICKET_ID}`);

  const ticketDetailRegion = page.getByRole("region", {
    name: "チケット詳細",
    exact: true
  });

  await expect(ticketDetailRegion).toHaveCount(1);
  await expect(ticketDetailRegion).toBeVisible();
  await expect(
    ticketDetailRegion.getByRole("heading", {
      level: 1,
      name: "Welcome to TaskManagedAI"
    })
  ).toBeVisible();
  const ticketSlug = ticketDetailRegion
    .locator("dd")
    .filter({ hasText: exactTextPattern("welcome") });

  await expect(ticketSlug).toHaveCount(1);
  await expect(ticketSlug).toHaveText("welcome");
  await expect(ticketSlug).toBeVisible();
  await expect(ticketDetailRegion.getByText("未着手").first()).toBeVisible();

  for (const sectionHeading of ["基本情報", "説明", "ラベル", "アクティビティ"]) {
    await expect(
      ticketDetailRegion.getByRole("heading", { name: sectionHeading })
    ).toBeVisible();
  }
});

test("Sprint 9: unseeded agent run detail shows not-found UI", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto(`/runs/${UNSEEDED_AGENT_RUN_ID}`);

  await expectNotFoundPage(page);
  await expect(page.getByRole("region", { name: "AI 実行詳細" })).toHaveCount(0);
});

test("Sprint 9: ticket detail rejects non-UUID id with not-found UI", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/tickets/not-a-uuid");

  await expectNotFoundPage(page);
  await expect(page.getByRole("region", { name: "チケット詳細" })).toHaveCount(0);
  await expect(page.getByText("Welcome to TaskManagedAI")).toHaveCount(0);
});

test("Sprint 9: agent run detail rejects non-UUID id with not-found UI", async ({
  page
}) => {
  await loginAsDev(page);
  await page.goto("/runs/not-a-uuid");

  await expectNotFoundPage(page);
  await expect(page.getByRole("region", { name: "AI 実行詳細" })).toHaveCount(0);
});
