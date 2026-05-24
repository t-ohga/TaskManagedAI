import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import NotificationsPage from "@/app/(admin)/notifications/page";

const apiMocks = vi.hoisted(() => ({
  listNotificationTriage: vi.fn()
}));

vi.mock("@/lib/api/notifications", () => ({
  listNotificationTriage: apiMocks.listNotificationTriage
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: vi.fn()
  })
}));

vi.mock("@/app/(admin)/notifications/_actions/mark-read", () => ({
  markNotificationReadAction: vi.fn()
}));

vi.mock("@/app/(admin)/notifications/_actions/triage", () => ({
  resolveNotificationTriageAction: vi.fn(),
  snoozeNotificationTriageAction: vi.fn()
}));

afterEach(() => {
  apiMocks.listNotificationTriage.mockReset();
});

describe("NotificationsPage triage view", () => {
  it("renders redacted notification triage rows and state tabs", async () => {
    apiMocks.listNotificationTriage.mockResolvedValueOnce([
      {
        id: "00000000-0000-4000-8000-00000000b201",
        event_type: "approval_pending",
        payload_keys: ["approval_id", "resource_ref"],
        payload_redaction_status: "keys_only",
        severity: "high",
        required_action: "review_approval",
        due_at: "2026-05-25T00:00:00Z",
        snoozed_until: null,
        resolved_at: null,
        resolved_by_actor_id: null,
        created_at: "2026-05-24T00:00:00Z",
        read_at: null
      }
    ]);

    render(await NotificationsPage({ searchParams: Promise.resolve({ state: "open" }) }));

    const region = screen.getByRole("region", { name: "通知" });
    expect(within(region).getByRole("heading", { name: "通知" })).toBeVisible();
    expect(within(region).getByRole("link", { name: "未解決" })).toHaveAttribute(
      "aria-current",
      "page"
    );

    const item = within(region).getByTestId(
      "notification-triage-00000000-0000-4000-8000-00000000b201"
    );
    expect(within(item).getByText("承認確認")).toBeVisible();
    expect(within(item).getByText("高")).toBeVisible();
    expect(within(item).getByText("approval_id")).toBeVisible();
    expect(within(item).getByText("resource_ref")).toBeVisible();
    expect(within(item).queryByText("raw payload value")).not.toBeInTheDocument();
    expect(within(item).getByRole("button", { name: "1時間スヌーズ" })).toBeVisible();
    expect(within(item).getByRole("button", { name: "解決" })).toBeVisible();
  });
});
