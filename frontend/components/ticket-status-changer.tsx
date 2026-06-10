"use client";

import { useEffect, useState, useTransition } from "react";

import { confirmDiscardUnsavedDrafts } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

import { updateTicketAction, type UpdateTicketState } from "@/app/(admin)/tickets/[id]/actions";

const STATUSES = [
  { value: "open", label: "未着手", color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300 hover:bg-blue-200 dark:hover:bg-blue-800" },
  { value: "in_progress", label: "進行中", color: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300 hover:bg-amber-200 dark:hover:bg-amber-800" },
  { value: "review", label: "レビュー", color: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300 hover:bg-purple-200 dark:hover:bg-purple-800" },
  { value: "blocked", label: "ブロック", color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300 hover:bg-orange-200 dark:hover:bg-orange-800" },
  { value: "closed", label: "完了", color: "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 hover:bg-emerald-200 dark:hover:bg-emerald-800" },
  { value: "cancelled", label: "中止", color: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300 hover:bg-gray-200 dark:hover:bg-gray-700" },
] as const;

type Props = {
  ticketId: string;
  currentStatus: string;
};

export function TicketStatusChanger({ ticketId, currentStatus }: Props) {
  const requestRefresh = useDeferredRouterRefresh();
  const [isPending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);
  const [optimisticStatus, setOptimisticStatus] = useState(currentStatus);

  useEffect(() => {
    // optimistic UI 用の local state を、server 更新後 (router.refresh で currentStatus prop が
    // 変わったとき) に canonical な値へ再同期する。optimistic 更新で一時的に prop と乖離するため
    // derive ではなく local state を持ち、prop 変化時にこの effect で同期する。
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setOptimisticStatus(currentStatus);
  }, [currentStatus]);

  function handleStatusChange(newStatus: string) {
    if (newStatus === optimisticStatus || isPending) return;
    // R2 (Codex adversarial HIGH): 未保存編集の破棄確認は mutation **前**。キャンセルなら
    // server action を実行しない (post-commit 確認だと stale form 保存で commit を巻き戻せる)。
    if (!confirmDiscardUnsavedDrafts()) return;
    setError(null);
    setOptimisticStatus(newStatus);

    const formData = new FormData();
    formData.set("ticket_id", ticketId);
    formData.set("status", newStatus);

    startTransition(async () => {
      const result = await updateTicketAction({ kind: "idle" } as UpdateTicketState, formData);
      if (result.kind === "error") {
        setError(result.message);
        setOptimisticStatus(currentStatus);
      } else {
      // C-5 workaround: transition 内の router.refresh() は isPending を固める (lib/use-deferred-router-refresh.ts 参照)。
        requestRefresh();
      }
    });
  }

  return (
    <div>
      <div className="flex flex-wrap gap-2">
        {STATUSES.map(({ value, label, color }) => (
          <button
            key={value}
            type="button"
            disabled={isPending}
            onClick={() => handleStatusChange(value)}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${color} ${
              optimisticStatus === value ? "ring-2 ring-offset-1 ring-accent" : "opacity-60"
            } ${isPending ? "opacity-30 cursor-wait" : "cursor-pointer"}`}
          >
            {label}
            {optimisticStatus === value ? " ✓" : null}
          </button>
        ))}
      </div>
      <div aria-live="polite" className="mt-2">
        {error ? <p className="text-xs text-red-600 dark:text-red-400">{error}</p> : null}
        {isPending ? <p className="text-xs text-muted-foreground">更新中...</p> : null}
      </div>
    </div>
  );
}
