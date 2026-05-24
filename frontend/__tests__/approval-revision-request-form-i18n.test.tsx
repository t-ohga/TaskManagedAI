import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApprovalRevisionRequestForm } from "../app/(admin)/approvals/[id]/_components/approval-revision-request-form";

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh
  })
}));

vi.mock("../app/(admin)/approvals/[id]/_actions/request-revision", () => ({
  requestApprovalRevisionAction: vi.fn()
}));

afterEach(() => {
  routerMocks.refresh.mockClear();
});

describe("ApprovalRevisionRequestForm i18n", () => {
  it("renders Japanese labels without rendering a rationale value", () => {
    render(
      <ApprovalRevisionRequestForm
        approvalId="00000000-0000-4000-8000-00000000a301"
        initialStatus="pending"
      />
    );

    expect(screen.getByRole("group", { name: "修正依頼" })).toBeVisible();
    expect(screen.getByLabelText("修正理由")).toHaveAttribute("name", "rationale");
    expect(screen.getByPlaceholderText("再提出前に直すべき内容")).toBeVisible();
    expect(screen.getByRole("button", { name: "修正依頼" })).toBeVisible();
    expect(screen.queryByText("Please update the tests.")).not.toBeInTheDocument();
  });
});
