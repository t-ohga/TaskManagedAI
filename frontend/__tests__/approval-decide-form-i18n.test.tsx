import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ApprovalDecideForm } from "../app/(admin)/approvals/[id]/_components/approval-decide-form";

const routerMocks = vi.hoisted(() => ({
  refresh: vi.fn()
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    refresh: routerMocks.refresh
  })
}));

afterEach(() => {
  routerMocks.refresh.mockClear();
});

describe("ApprovalDecideForm i18n", () => {
  it("renders Japanese labels while preserving action submit values", () => {
    render(
      <ApprovalDecideForm
        approvalId="00000000-0000-4000-8000-000000007001"
        initialStatus="pending"
      />
    );

    expect(screen.getByText("レビュー判定")).toBeVisible();
    expect(screen.getByLabelText("理由")).toHaveAttribute("name", "rationale");
    expect(screen.getByPlaceholderText("この判定の理由")).toBeVisible();
    expect(screen.getByRole("button", { name: "承認" })).toHaveValue("approve");
    expect(screen.getByRole("button", { name: "却下" })).toHaveValue("reject");
  });
});
