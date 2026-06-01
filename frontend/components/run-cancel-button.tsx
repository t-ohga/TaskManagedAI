"use client";

import { useRouter } from "next/navigation";

import { ConfirmDialog } from "@/components/confirm-dialog";
import { useToast } from "@/components/toast";

type Props = {
  runId: string;
};

// O-2 (UI 監査 fix): bespoke 2 段階 inline confirm + blocking alert() を、共通 ConfirmDialog +
// トースト通知に統一 (これまで ConfirmDialog/Toast は orphan だった、E-1/O-1/O-2)。
export function RunCancelButton({ runId }: Props) {
  const router = useRouter();
  const { toast } = useToast();

  async function handleCancel(): Promise<void> {
    try {
      const res = await fetch(`/api/proxy/agent_runs/${runId}/cancel`, { method: "POST" });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string; detail?: string };
        toast(data.error ?? data.detail ?? "キャンセルに失敗しました", "error");
        return;
      }
      toast("AI 実行をキャンセルしました", "success");
      router.refresh();
    } catch {
      toast("キャンセルに失敗しました", "error");
    }
  }

  return (
    <ConfirmDialog
      title="AI 実行をキャンセル"
      message="本当にこの AI 実行をキャンセルしますか？この操作は取り消せません。"
      confirmLabel="はい、キャンセル"
      cancelLabel="いいえ"
      variant="danger"
      onConfirm={handleCancel}
    >
      {(open) => (
        <button
          type="button"
          onClick={open}
          className="rounded-md bg-orange-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-orange-700"
        >
          キャンセル
        </button>
      )}
    </ConfirmDialog>
  );
}
