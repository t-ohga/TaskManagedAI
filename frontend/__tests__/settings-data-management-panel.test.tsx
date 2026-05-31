import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DataManagementPanel } from "../app/(admin)/settings/_components/data-management-panel";

// Server Action は vitest では実行しないため no-op に mock (useActionState 経由で参照)。
vi.mock("../app/(admin)/settings/actions", () => ({
  archiveProjectAction: vi.fn(async () => ({ kind: "idle" })),
  bulkSoftDeleteAction: vi.fn(async () => ({ kind: "idle" })),
  restoreBatchAction: vi.fn(async () => ({ kind: "idle" })),
  importTicketsAction: vi.fn(async () => ({ kind: "idle" }))
}));

vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn(), push: vi.fn(), replace: vi.fn() })
}));

const PROJECT_ID = "00000000-0000-4000-8000-0000000cc001";

afterEach(() => {
  vi.clearAllMocks();
});

describe("DataManagementPanel (Q-2〜Q-4 / ADR-00037)", () => {
  it("shows an active badge and editable destructive controls when active", () => {
    render(
      <DataManagementPanel projectId={PROJECT_ID} status="active" activeTicketCount={5} />
    );
    expect(screen.getByText("アクティブ")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "プロジェクトをアーカイブする" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "アクティブ ticket を全件削除する" })
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "プレビュー (検証のみ)" })
    ).toBeInTheDocument();
  });

  it("freezes child operations and shows an archived badge when archived", () => {
    render(
      <DataManagementPanel projectId={PROJECT_ID} status="archived" activeTicketCount={5} />
    );
    expect(screen.getByText("アーカイブ済み")).toBeInTheDocument();
    // archive 解除ボタンは出る
    expect(
      screen.getByRole("button", { name: "アーカイブを解除する" })
    ).toBeInTheDocument();
    // child 操作 (一括削除 / 復元 / インポート) は disable され notice を表示
    expect(
      screen.queryByRole("button", { name: "アクティブ ticket を全件削除する" })
    ).not.toBeInTheDocument();
    expect(screen.getByText(/一括削除は無効/u)).toBeInTheDocument();
    expect(screen.getByText(/復元は無効/u)).toBeInTheDocument();
    expect(screen.getByText(/インポートは無効/u)).toBeInTheDocument();
  });

  it("requires a second confirmation step before archiving (two-stage)", () => {
    render(
      <DataManagementPanel projectId={PROJECT_ID} status="active" activeTicketCount={5} />
    );
    // 確定ボタンは最初は出ていない
    expect(
      screen.queryByRole("button", { name: "アーカイブを確定" })
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "プロジェクトをアーカイブする" }));
    // 確認ステップが出る
    expect(
      screen.getByRole("button", { name: "アーカイブを確定" })
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "キャンセル" })).toBeInTheDocument();
  });

  it("requires a second confirmation step before bulk delete (two-stage)", () => {
    render(
      <DataManagementPanel projectId={PROJECT_ID} status="active" activeTicketCount={3} />
    );
    expect(
      screen.queryByRole("button", { name: "3 件の削除を確定" })
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "アクティブ ticket を全件削除する" })
    );
    expect(
      screen.getByRole("button", { name: "3 件の削除を確定" })
    ).toBeInTheDocument();
  });

  it("disables bulk delete when there are no active tickets", () => {
    render(
      <DataManagementPanel projectId={PROJECT_ID} status="active" activeTicketCount={0} />
    );
    expect(
      screen.getByRole("button", { name: "アクティブ ticket を全件削除する" })
    ).toBeDisabled();
    expect(screen.getByText(/削除対象のアクティブ ticket はありません/u)).toBeInTheDocument();
  });

  it("disables the import-commit button until a valid preview exists", () => {
    render(
      <DataManagementPanel projectId={PROJECT_ID} status="active" activeTicketCount={5} />
    );
    // preview 前は「インポートを実行」は無効
    expect(screen.getByRole("button", { name: "インポートを実行" })).toBeDisabled();
    // プレビューボタンも空 textarea では無効
    expect(screen.getByRole("button", { name: "プレビュー (検証のみ)" })).toBeDisabled();
  });
});
