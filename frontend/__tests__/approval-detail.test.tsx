import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import ApprovalDetailPage from "@/app/(admin)/approvals/[id]/page";

const apiMocks = vi.hoisted(() => ({
  getApprovalDetail: vi.fn(),
}));

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh,
  }),
}));

vi.mock("@/lib/api/approvals", () => ({
  getApprovalDetail: apiMocks.getApprovalDetail,
}));

afterEach(() => {
  apiMocks.getApprovalDetail.mockReset();
  routerMocks.refresh.mockClear();
});

describe("ApprovalDetailPage", () => {
  it("renders decision packet hashes and stale event sequence", async () => {
    apiMocks.getApprovalDetail.mockResolvedValue(
      buildApprovalDetail({
        artifact_hash: "a".repeat(64),
        diff_hash: "b".repeat(64),
        policy_pack_lock: "c".repeat(64),
        provider_request_fingerprint: "d".repeat(64),
        stale_after_event_seq: 42,
      })
    );

    render(await ApprovalDetailPage({ params: Promise.resolve({ id: APPROVAL_ID }) }));

    const packet = screen.getByRole("heading", { name: "Decision packet" }).closest("article");
    expect(packet).not.toBeNull();
    const packetQueries = within(packet as HTMLElement);
    expect(packetQueries.getByText("policy-v1")).toBeVisible();
    expect(packetQueries.getByText("a".repeat(64))).toBeVisible();
    expect(packetQueries.getByText("b".repeat(64))).toBeVisible();
    expect(packetQueries.getByText("c".repeat(64))).toBeVisible();
    expect(packetQueries.getByText("d".repeat(64))).toBeVisible();
    expect(packetQueries.getByText("42")).toBeVisible();
    expect(screen.queryByRole("group", { name: "修正依頼" })).not.toBeInTheDocument();
  });

  it("does not render non-hash decision packet values as raw text", async () => {
    apiMocks.getApprovalDetail.mockResolvedValue(
      buildApprovalDetail({
        artifact_hash: "raw artifact body",
        diff_hash: "raw diff body",
        policy_pack_lock: "raw policy pack",
        provider_request_fingerprint: "raw provider request",
        stale_after_event_seq: null,
      })
    );

    render(await ApprovalDetailPage({ params: Promise.resolve({ id: APPROVAL_ID }) }));

    expect(screen.queryByText("raw artifact body")).not.toBeInTheDocument();
    expect(screen.queryByText("raw diff body")).not.toBeInTheDocument();
    expect(screen.queryByText("raw policy pack")).not.toBeInTheDocument();
    expect(screen.queryByText("raw provider request")).not.toBeInTheDocument();
    expect(screen.getAllByText("(非 SHA-256 形式のため非表示)")).toHaveLength(4);
    expect(screen.getByText("(未設定)")).toBeVisible();
  });

  it("renders request revision action only for pending approvals", async () => {
    apiMocks.getApprovalDetail.mockResolvedValue(
      buildApprovalDetail({
        status: "pending",
        decided_by_actor_id: null,
        decided_at: null,
        rationale: null,
      })
    );

    render(await ApprovalDetailPage({ params: Promise.resolve({ id: APPROVAL_ID }) }));

    expect(screen.getByText("レビュー判定")).toBeVisible();
    expect(screen.getByRole("group", { name: "修正依頼" })).toBeVisible();
    expect(screen.getByLabelText("修正理由")).toBeVisible();
    expect(screen.getByRole("button", { name: "修正依頼" })).toBeVisible();
  });
});

const APPROVAL_ID = "00000000-0000-4000-8000-000000007101";

function buildApprovalDetail(overrides: Record<string, unknown>) {
  return {
    id: APPROVAL_ID,
    action_class: "repo_write",
    resource_ref: "repo:TaskManagedAI:decision-packet",
    risk_level: "high",
    status: "approved",
    requested_by_actor_id: "00000000-0000-4000-8000-000000007102",
    decided_by_actor_id: "00000000-0000-4000-8000-000000007103",
    requested_at: "2026-05-24T00:00:00Z",
    decided_at: "2026-05-24T00:10:00Z",
    rationale: "approved for test",
    artifact_hash: null,
    diff_hash: null,
    policy_version: "policy-v1",
    policy_pack_lock: null,
    provider_request_fingerprint: null,
    stale_after_event_seq: null,
    ...overrides,
  };
}
