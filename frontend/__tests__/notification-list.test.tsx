import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationListItem } from "../app/(admin)/notifications/_components/notification-list-item";
import { ApprovalListItemSchema } from "../lib/api/approvals";

import type { NotificationItem } from "../lib/api/notifications";

const actionMocks = vi.hoisted(() => ({
  markNotificationReadAction: vi.fn()
}));

vi.mock("../app/(admin)/notifications/_actions/mark-read", () => ({
  markNotificationReadAction: actionMocks.markNotificationReadAction
}));

afterEach(() => {
  actionMocks.markNotificationReadAction.mockReset();
});

const unreadNotification: NotificationItem = {
  id: "00000000-0000-4000-8000-000000005001",
  event_type: "approval_pending",
  payload: {
    approval_id: "00000000-0000-4000-8000-000000005011",
    action_class: "task_write",
    resource_ref: "task:notification-demo",
    risk_level: "medium"
  },
  created_at: "2026-05-08T10:00:00Z",
  read_at: null
};

describe("NotificationListItem", () => {
  it("renders unread notifications with a mark-read action", () => {
    render(<NotificationListItem notification={unreadNotification} />);

    const item = screen.getByTestId(`notification-${unreadNotification.id}`);
    expect(item).toHaveAttribute("data-read", "false");
    expect(screen.getByText("approval_pending")).toBeVisible();
    expect(screen.getByRole("button", { name: "既読にする" })).toBeVisible();
  });

  it("renders read notifications without a mark-read action", () => {
    render(
      <NotificationListItem
        notification={{
          ...unreadNotification,
          id: "00000000-0000-4000-8000-000000005002",
          read_at: "2026-05-08T10:05:00Z"
        }}
      />
    );

    const item = screen.getByTestId("notification-00000000-0000-4000-8000-000000005002");
    expect(item).toHaveAttribute("data-read", "true");
    expect(screen.queryByRole("button", { name: "既読にする" })).not.toBeInTheDocument();
  });
});

describe("ApprovalListItemSchema", () => {
  it("rejects unknown action classes", () => {
    expect(() =>
      ApprovalListItemSchema.parse({
        id: "00000000-0000-4000-8000-000000005101",
        action_class: "unknown_action",
        resource_ref: "task:unknown-action",
        risk_level: "medium",
        status: "pending",
        requested_by_actor_id: "00000000-0000-4000-8000-000000005102",
        requested_at: "2026-05-08T10:00:00Z"
      })
    ).toThrow();
  });
});
