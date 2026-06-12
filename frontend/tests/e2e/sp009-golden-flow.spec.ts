/**
 * SP-009 golden-flow surfaces: 4-surface acceptance gate.
 *
 * 各 surface (approval 詳細 / run 詳細 / audit / 横断ナビ) を seed した固定 fixture で **独立に**
 * 検証する surface smoke。approval と run は相関した 1 本のフロー (approval→run→PR) として結び
 * 付けておらず、各画面が seeded fixture を正しく描画し redaction が効くことを保証するゲートである
 * (相関フローの結合検証は別途 P0.1 以降)。
 *
 * All assertions are mandatory (no skip-by-count). If seed data is
 * missing, the test fails rather than silently passing.
 */

import { expect, test } from "@playwright/test";

import { loginAsDev } from "./_helpers/login";
import { assertPageNoSecretCanary } from "./_helpers/secret-canary";

// backend seed_golden_flow_fixtures (test 専用 seed) の固定 fixture ID。「最初のリンク」依存をやめ、
// seed した golden-flow approval / run / events を直接開いて deterministic に検証する。
const SEED_TICKET_ID = "00000000-0000-4000-8000-000000000006";
const SEED_AGENT_ACTOR_ID = "00000000-0000-4000-8000-000000000009";
const SEED_APPROVAL_ID = "00000000-0000-4000-8000-00000000000a";
const SEED_RUN_ID = "00000000-0000-4000-8000-00000000000b";

test.describe.serial("SP-009 golden flow", () => {
  test("seeded approval detail shows fixture content and both controls", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/approvals");

    const approvalRegion = page.getByRole("region", {
      name: "承認一覧",
    });
    await expect(approvalRegion).toBeVisible();

    // 「最初のリンク」ではなく seed した固定 approval を一覧から特定して開く (deterministic)。
    const seededLink = page.locator(`a[href="/approvals/${SEED_APPROVAL_ID}"]`);
    await expect(
      seededLink,
      "Seeded golden-flow approval must be listed"
    ).toBeVisible({ timeout: 10_000 });

    await seededLink.click();
    await expect(page).toHaveURL(new RegExp(`/approvals/${SEED_APPROVAL_ID}$`, "u"));

    // content assertion は詳細 region にスコープする (nav の「承認待ち」link が mobile では
    // hamburger 折りたたみで hidden になり、page 全体の getByText だと hidden 要素を拾うため)。
    const detail = page.getByRole("region", { name: "承認詳細" });
    await expect(detail).toBeVisible();

    // seed した fixture の内容が描画されていること (request の実連鎖)。
    await expect(
      detail.getByText(`ticket:${SEED_TICKET_ID}`),
      "Approval resource_ref must point to the seeded ticket"
    ).toBeVisible();
    // action_class=task_write / status=pending の表示。
    await expect(detail.getByText("タスク更新").first()).toBeVisible();
    await expect(detail.getByText("承認待ち").first()).toBeVisible();
    // requester は agent actor (self-approval 回避、human DEFAULT_ACTOR ではない)。
    await expect(detail.getByText(SEED_AGENT_ACTOR_ID)).toBeVisible();

    await expect(
      detail.getByRole("button", { name: /承認/u }),
      "Approve button must be visible in approval detail"
    ).toBeVisible();
    await expect(
      detail.getByRole("button", { name: /却下/u }),
      "Reject button must be visible in approval detail"
    ).toBeVisible();

    await assertPageNoSecretCanary(page, "/approvals/[id]");
  });

  test("seeded agent run detail shows the events timeline with redacted payload", async ({
    page,
  }) => {
    await loginAsDev(page);
    await page.goto("/runs");

    const runsRegion = page.getByRole("region", {
      name: "AI 実行一覧",
    });
    await expect(runsRegion).toBeVisible();

    // seed した固定 run を一覧から特定して開く (deterministic)。
    const seededRunLink = page.locator(`a[href="/runs/${SEED_RUN_ID}"]`).first();
    await expect(
      seededRunLink,
      "Seeded golden-flow run must be listed"
    ).toBeVisible({ timeout: 10_000 });

    await seededRunLink.click();
    await expect(page).toHaveURL(new RegExp(`/runs/${SEED_RUN_ID}$`, "u"));

    const detail = page.getByRole("region", { name: "AI 実行詳細" });
    await expect(detail).toBeVisible();

    await expect(
      page.getByRole("heading", { name: /イベントタイムライン/u }),
      "Events timeline heading must be visible in run detail"
    ).toBeVisible();

    // 空 timeline 文言が出たら fail = seed した 3 events が取得・描画されていることを保証。
    await expect(detail.getByText("イベントはまだ記録されていません")).toHaveCount(0);

    // seed した 3 AgentRunEvent が event_type label で描画される (run_queued / provider_responded /
    // run_completed)。AgentRunEvent の取得・event_type 表示が壊れたら検出する。content assertion は
    // 詳細 region にスコープ (nav link / status indicator 等の同名テキスト誤一致を避ける)。
    await expect(detail.getByText("実行キュー追加").first()).toBeVisible();
    await expect(detail.getByText("プロバイダー応答").first()).toBeVisible();
    await expect(detail.getByText("実行完了").first()).toBeVisible();

    // payload は keys のみ表示 (redaction)。raw value は出さない。
    await expect(detail.getByText(/keys:/u).first()).toBeVisible();

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

    // header 行 + 1 件以上の data 行 (= 計 2 行以上)。full suite では先行 spec の操作で audit
    // event が累積するため exact count は使えない。golden flow seed が最低 1 行を保証する。
    const rows = auditRegion.getByRole("row");
    await expect(
      rows.nth(1),
      "Audit log must have at least one data row for golden flow"
    ).toBeVisible({ timeout: 10_000 });

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
