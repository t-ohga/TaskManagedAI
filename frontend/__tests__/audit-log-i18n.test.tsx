import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as ApiClient from "@/lib/api/client";

import AuditLogPage from "../app/(admin)/audit/page";

const apiMocks = vi.hoisted(() => ({
  fetchBackendRaw: vi.fn()
}));

// AuditPage の loadAuditEvents は fetchBackendRaw(/api/v1/audit_events) で監査イベントを
// 取得する (per-resource listAuditEvents ではなく fetchBackendRaw 直接)。実データはこの
// mock から供給する。BackendApiError 等の実 export は importActual で残す。
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof ApiClient>()),
  fetchBackendRaw: apiMocks.fetchBackendRaw
}));

afterEach(() => {
  apiMocks.fetchBackendRaw.mockReset();
});

describe("AuditLogPage i18n", () => {
  it("renders Japanese audit labels while preserving raw audit identifiers", async () => {
    apiMocks.fetchBackendRaw.mockResolvedValue({
      items: [
        {
          id: "00000000-0000-4000-8000-00000000b001",
          event_type: "runner_blocked",
          actor_id: "00000000-0000-4000-8000-00000000b002",
          reason_code: "dangerous_command",
          payload_keys: ["argv_hash", "deny_category"],
          payload_redaction_status: "keys_only",
          created_at: "2026-05-22T00:00:00Z"
        }
      ],
      total: 1
    });

    // AuditPage は searchParams (type / page filter) を必須 prop に持つ async Server Component。
    // i18n ラベル検証なので空 filter で render する。
    render(await AuditLogPage({ searchParams: Promise.resolve({}) }));

    // region / heading は i18n で日本語化済 (section aria-label="監査ログ"、h1="監査ログ")。
    const region = screen.getByRole("region", { name: "監査ログ" });
    expect(within(region).getByRole("heading", { name: "監査ログ", level: 1 })).toBeVisible();

    // テーブルの column header は日本語化済 (event_type / actor_id / reason_code / payload /
    // redaction_status / datetime → イベント種別 / アクター / 理由コード / ペイロード /
    // マスク状態 / 日時)。マスク状態列は AC-HARD-02 の per-row redaction observability。
    const table = within(region).getByRole("table");
    for (const header of ["イベント種別", "アクター", "理由コード", "ペイロード", "マスク状態", "日時"]) {
      expect(within(table).getByRole("columnheader", { name: header })).toBeVisible();
    }

    // event_type は EVENT_TYPE_LABELS で日本語 badge 化される (runner_blocked → "ランナーブロック")。
    expect(within(table).getByText("ランナーブロック")).toBeVisible();
    // reason_code は canonical な raw identifier をそのまま保持する (翻訳しない)。
    expect(within(table).getByText("dangerous_command")).toBeVisible();
    // AC-HARD-02 observability: payload_redaction_status を per-row で surface する。
    // canonical な backend enum を raw 値で表示し (keys_only)、operator が redaction の
    // 欠落 / drift を検知できる。この列が消えると本 assertion が落ち regression を捕捉する。
    expect(within(table).getByText("keys_only")).toBeVisible();
  });
});
