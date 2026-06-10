"use client";

import { useState, useTransition } from "react";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

import { useToast } from "@/components/toast";

type BulkStatusChangerProps = {
  selectedIds: string[];
  onClear: () => void;
  onSelectionChange?: (ids: string[]) => void;
};

const STATUSES = [
  { value: "open", label: "未着手" },
  { value: "in_progress", label: "進行中" },
  { value: "closed", label: "完了" },
  { value: "cancelled", label: "中止" },
];

export function BulkStatusChanger({ selectedIds, onClear, onSelectionChange }: BulkStatusChangerProps) {
  const requestRefresh = useDeferredRouterRefresh();
  const { toast } = useToast();
  const [isPending, startTransition] = useTransition();
  const [targetStatus, setTargetStatus] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (selectedIds.length === 0) return null;

  function handleApply() {
    if (!targetStatus) return;
    setError(null);
    startTransition(async () => {
      const { updateTicketAction } = await import("@/app/(admin)/tickets/[id]/actions");
      const failedIds: string[] = [];
      for (const id of selectedIds) {
        try {
          const fd = new FormData();
          fd.set("ticket_id", id);
          fd.set("status", targetStatus);
          const result = await updateTicketAction({ kind: "idle" }, fd);
          if (result.kind === "error") failedIds.push(id);
        } catch {
          failedIds.push(id);
        }
      }
      // C-5 workaround: transition 内の router.refresh() は isPending を固める (lib/use-deferred-router-refresh.ts 参照)。
      requestRefresh();
      if (failedIds.length > 0) {
        const succeeded = selectedIds.length - failedIds.length;
        setError(`${failedIds.length} 件の更新に失敗しました (権限またはプロジェクト境界を確認してください)`);
        toast(
          `${failedIds.length} 件の更新に失敗${succeeded > 0 ? ` (${succeeded} 件成功)` : ""}`,
          "error"
        );
        setSelectedIdsFromParent(failedIds);
      } else {
        toast(`${selectedIds.length} 件のステータスを更新しました`, "success");
        onClear();
      }
    });
  }

  function setSelectedIdsFromParent(ids: string[]) {
    onSelectionChange?.(ids);
  }

  return (
    <div className="grid gap-2 rounded-md border border-accent/30 bg-accent/5 px-4 py-2">
      <div className="flex items-center gap-3">
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
      {error ? <p className="text-xs text-danger" role="alert">{error}</p> : null}
    </div>
  );
}
