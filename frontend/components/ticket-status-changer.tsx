"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState, useTransition } from "react";

import { updateTicketAction, type UpdateTicketState } from "@/app/(admin)/tickets/[id]/actions";

const STATUSES = [
  { value: "open", label: "未着手", color: "bg-blue-100 text-blue-700 hover:bg-blue-200" },
  { value: "in_progress", label: "進行中", color: "bg-amber-100 text-amber-700 hover:bg-amber-200" },
  { value: "review", label: "レビュー", color: "bg-purple-100 text-purple-700 hover:bg-purple-200" },
  { value: "blocked", label: "ブロック", color: "bg-orange-100 text-orange-700 hover:bg-orange-200" },
  { value: "closed", label: "完了", color: "bg-emerald-100 text-emerald-700 hover:bg-emerald-200" },
  { value: "cancelled", label: "中止", color: "bg-gray-100 text-gray-600 hover:bg-gray-200" },
] as const;

type Props = {
  ticketId: string;
  currentStatus: string;
};

export function TicketStatusChanger({ ticketId, currentStatus }: Props) {
  const router = useRouter();
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
        router.refresh();
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
        {error ? <p className="text-xs text-red-600">{error}</p> : null}
        {isPending ? <p className="text-xs text-muted-foreground">更新中...</p> : null}
      </div>
    </div>
  );
}
