import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import AuditLogPage from "../app/(admin)/audit/page";

describe("AuditLogPage i18n", () => {
  it("renders Japanese audit labels while preserving raw audit identifiers", () => {
    render(<AuditLogPage />);

    const region = screen.getByRole("region", { name: "監査ログ" });
    expect(within(region).getByRole("heading", { name: "監査ログ" })).toBeVisible();
    expect(within(region).getByRole("heading", { name: "監査 event stream" })).toBeVisible();

    const table = within(region).getByRole("table", {
      name: /event_type、actor_id、reason_code/u
    });
    expect(within(table).getByRole("columnheader", { name: "event_type" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "reason_code" })).toBeVisible();
    expect(within(table).getByRole("columnheader", { name: "blocked_reason" })).toBeVisible();
    expect(within(table).getByText("runner_blocked")).toBeVisible();
    expect(within(table).getByText("dangerous_command")).toBeVisible();
    expect(within(table).getByText("runtime_blocked")).toBeVisible();
    expect(within(table).getByText("argv_hash と deny_category のみ")).toBeVisible();
  });
});
