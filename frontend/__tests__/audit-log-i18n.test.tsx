import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AuditLogPage from "../app/(admin)/audit/page";

const apiMocks = vi.hoisted(() => ({
  listAuditEvents: vi.fn()
}));

vi.mock("@/lib/api/audit", () => ({
  listAuditEvents: apiMocks.listAuditEvents
}));

afterEach(() => {
  apiMocks.listAuditEvents.mockReset();
});

describe("AuditLogPage i18n", () => {
  it("renders Japanese audit labels while preserving raw audit identifiers", async () => {
    apiMocks.listAuditEvents.mockResolvedValue({
      events: [
        {
          id: "00000000-0000-4000-8000-00000000b001",
          event_type: "runner_blocked",
          actor_id: "00000000-0000-4000-8000-00000000b002",
          principal_id: null,
          tenant_id: 1,
          trace_id: null,
          correlation_id: null,
          reason_code: "dangerous_command",
          payload_keys: ["argv_hash", "deny_category"],
          payload_redaction_status: "keys_only",
          created_at: "2026-05-22T00:00:00Z"
        }
      ],
      total: 1,
      limit: 50,
      offset: 0
    });

    render(await AuditLogPage());

    const region = screen.getByRole("region", { name: "監査ログ" });
    expect(within(region).getByRole("heading", { name: "監査ログ" })).toBeVisible();

    const table = within(region).getByRole("table", {
      name: /event_type、actor_id、reason_code/u
    });
    expect(within(table).getByRole("columnheader", { name: "event_type" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "reason_code" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "payload_keys" })).toBeVisible();
    expect(within(table).getByText("runner_blocked")).toBeVisible();
    expect(within(table).getByText("dangerous_command")).toBeVisible();
    expect(within(table).getByText("argv_hash, deny_category")).toBeVisible();
  });
});
