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
    const keysOnly = within(table).getByText("keys_only");
    expect(keysOnly).toBeVisible();
    // keys_only (通常 redaction) のみ safe (emerald) 表示。
    expect(keysOnly.className).toMatch(/emerald/);
  });

  it("surfaces non-safe / drifted payload redaction status as fail-closed (AC-HARD-02)", async () => {
    // backend PayloadRedactionStatus は keys_only / blocked_by_secret_scan の 2 値のみ。
    // fail-closed: keys_only 以外 (secret 検出 block / API skew で来た未知値) は safe 表示にしない。
    apiMocks.fetchBackendRaw.mockResolvedValue({
      items: [
        {
          id: "00000000-0000-4000-8000-00000000b101",
          event_type: "run_completed",
          actor_id: null,
          reason_code: null,
          payload_keys: ["status"],
          payload_redaction_status: "keys_only",
          created_at: "2026-05-22T00:00:00Z"
        },
        {
          id: "00000000-0000-4000-8000-00000000b102",
          event_type: "secret_canary_detected",
          actor_id: null,
          reason_code: "secret_canary",
          payload_keys: [],
          payload_redaction_status: "blocked_by_secret_scan",
          created_at: "2026-05-22T00:01:00Z"
        },
        {
          id: "00000000-0000-4000-8000-00000000b103",
          event_type: "run_failed",
          actor_id: null,
          reason_code: null,
          payload_keys: [],
          payload_redaction_status: "drifted_unknown_value",
          created_at: "2026-05-22T00:02:00Z"
        }
      ],
      total: 3
    });

    render(await AuditLogPage({ searchParams: Promise.resolve({}) }));
    const table = screen.getByRole("table");

    // keys_only のみ safe (emerald)。
    expect(within(table).getByText("keys_only").className).toMatch(/emerald/);

    // blocked_by_secret_scan は raw secret 検出の警告イベント。safe (emerald) 扱いしない。
    const blocked = within(table).getByText("blocked_by_secret_scan");
    expect(blocked.className).not.toMatch(/emerald/);
    expect(blocked.className).toMatch(/red/);

    // 未知 / drift した status は raw 値を DOM に出さず固定ラベル "不明" + fail-closed (非 emerald)。
    expect(within(table).queryByText("drifted_unknown_value")).not.toBeInTheDocument();
    const unknown = within(table).getByText("不明");
    expect(unknown.className).not.toMatch(/emerald/);
  });
});
