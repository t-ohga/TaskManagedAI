"use client";

import { useState, useTransition } from "react";
import { useRouter } from "next/navigation";

type BulkStatusChangerProps = {
  selectedIds: string[];
  onClear: () => void;
};

const STATUSES = [
  { value: "open", label: "未着手" },
  { value: "in_progress", label: "進行中" },
  { value: "closed", label: "完了" },
  { value: "cancelled", label: "中止" },
];

export function BulkStatusChanger({ selectedIds, onClear }: BulkStatusChangerProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [targetStatus, setTargetStatus] = useState("");

  if (selectedIds.length === 0) return null;

  function handleApply() {
    if (!targetStatus) return;
    startTransition(async () => {
      for (const id of selectedIds) {
        try {
          const fd = new FormData();
          fd.set("ticket_id", id);
          fd.set("status", targetStatus);
          const { updateTicketAction } = await import("@/app/(admin)/tickets/[id]/actions");
          await updateTicketAction({ kind: "idle" }, fd);
        } catch {
          /* continue with remaining */
        }
      }
      onClear();
      router.refresh();
    });
  }

  return (
    <div className="flex items-center gap-3 rounded-md border border-accent/30 bg-accent/5 px-4 py-2">
      <span className="text-sm font-medium">{selectedIds.length} 件選択中</span>
      <select
        value={targetStatus}
        onChange={(e) => setTargetStatus(e.target.value)}
        className="rounded-md border border-line px-2 py-1 text-sm"
        aria-label="一括変更先ステータス"
      >
        <option value="">ステータスを選択</option>
        {STATUSES.map((s) => (
          <option key={s.value} value={s.value}>{s.label}</option>
        ))}
      </select>
      <button
        type="button"
        onClick={handleApply}
        disabled={!targetStatus || isPending}
        className="rounded-md bg-accent px-3 py-1 text-sm font-medium text-white disabled:opacity-50"
      >
        {isPending ? "処理中..." : "一括変更"}
      </button>
      <button
        type="button"
        onClick={onClear}
        className="text-sm text-muted-foreground hover:text-ink"
      >
        選択解除
      </button>
    </div>
  );
}
