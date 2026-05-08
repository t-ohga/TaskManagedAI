import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ApprovalInboxPage from "../app/(admin)/approvals/page";

const apiMocks = vi.hoisted(() => ({
  listPendingApprovals: vi.fn()
}));

vi.mock("@/lib/api/approvals", () => ({
  listPendingApprovals: apiMocks.listPendingApprovals
}));

afterEach(() => {
  apiMocks.listPendingApprovals.mockReset();
});

describe("ApprovalInboxPage", () => {
  it("renders pending approvals with review links", async () => {
    const approvalId = "00000000-0000-4000-8000-000000007001";
    apiMocks.listPendingApprovals.mockResolvedValue([
      {
        id: approvalId,
        action_class: "repo_write",
        resource_ref: "repo:taskmanagedai:path/to/file.ts",
        risk_level: "high",
        status: "pending",
        requested_by_actor_id: "00000000-0000-4000-8000-000000007002",
        requested_at: "2026-05-08T00:00:00Z"
      }
    ]);

    render(await ApprovalInboxPage());

    expect(screen.getByRole("heading", { name: "Approval Inbox" })).toBeVisible();
    expect(screen.getByText("repo_write")).toBeVisible();
    expect(screen.getByText("repo:taskmanagedai:path/to/file.ts")).toBeVisible();
    expect(screen.getByRole("link", { name: "Review" })).toHaveAttribute(
      "href",
      `/approvals/${approvalId}`
    );
  });

  it("renders an empty state", async () => {
    apiMocks.listPendingApprovals.mockResolvedValue([]);

    render(await ApprovalInboxPage());

    expect(screen.getByText("No pending approvals.")).toBeVisible();
  });
});

