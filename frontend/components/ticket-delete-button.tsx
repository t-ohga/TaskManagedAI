"use client";

import { useRouter } from "next/navigation";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { useToast } from "@/components/toast";
import { updateTicketAction, type UpdateTicketState } from "@/app/(admin)/tickets/[id]/actions";
import { confirmDiscardUnsavedDrafts, prepareDiscardOnCommit } from "@/lib/full-reload";

type TicketDeleteButtonProps = {
  ticketId: string;
  projectId: string;
};

// O-2 (UI 監査 fix): bespoke native <dialog> を共通 ConfirmDialog + トーストに統一 (E-1/O-1/O-2)。
export function TicketDeleteButton({ ticketId }: TicketDeleteButtonProps) {
  const router = useRouter();
  const { toast } = useToast();

  async function handleDelete(): Promise<void> {
    // R3 F-2 (Codex adversarial): 中止も status mutation + 一覧へ遷移で未保存編集を失うため、
    // server action 実行前に破棄確認 gate を通す (キャンセル時は何も変えない)。
    // R11: 確認のみ pre-commit、破棄は中止成功時に commit (失敗時は draft 無傷)。
    const { approved, commit } = prepareDiscardOnCommit();
    if (!approved) return;
    const fd = new FormData();
    fd.set("ticket_id", ticketId);
    fd.set("status", "cancelled");
    const result = await updateTicketAction({ kind: "idle" } as UpdateTicketState, fd);
    if (result.kind === "ok") {
      commit();
      // R14 (Codex adversarial HIGH): 本 path は reload ではなく router.push で遷移するため、
      // useDeferredRouterRefresh の R7 最終再確認を通らない。承認後に編集された draft は commit()
      // で skip (R12) され dirty 残存するが、そのまま遷移すると無確認消失する。遷移前に再確認し、
      // 拒否なら遷移を中止 (中止 mutation 自体は成功済 — draft 保持を優先)。
      if (!confirmDiscardUnsavedDrafts()) return;
      toast("チケットを中止しました", "success");
      router.push("/tickets");
    } else if (result.kind === "error") {
      toast(result.message, "error");
    }
  }

  return (
    <ConfirmDialog
      title="チケットを中止しますか？"
      message="チケットのステータスが「中止」に変更され、看板・一覧から非表示になります。ステータスで「中止」を選ぶと再表示できます。"
      confirmLabel="中止する"
      cancelLabel="キャンセル"
      variant="danger"
      onConfirm={handleDelete}
    >
      {(open) => (
        <button
          type="button"
          onClick={open}
          className="rounded-md border border-danger/30 px-4 py-2 text-center text-sm font-medium text-danger transition-colors hover:bg-red-50 dark:hover:bg-red-950/40"
        >
          チケットを中止
        </button>
      )}
    </ConfirmDialog>
  );
}
