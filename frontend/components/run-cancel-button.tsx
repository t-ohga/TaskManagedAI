"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

type Props = {
  runId: string;
};

export function RunCancelButton({ runId }: Props) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [confirmed, setConfirmed] = useState(false);

  if (!confirmed) {
    return (
      <button
        type="button"
        onClick={() => setConfirmed(true)}
        className="rounded-md bg-orange-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-orange-700"
      >
        キャンセル
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span className="text-sm text-orange-700">本当にキャンセルしますか？</span>
      <button
        type="button"
        disabled={isPending}
        onClick={() => {
          startTransition(async () => {
            try {
              await fetch(`/api/proxy/agent_runs/${runId}/cancel`, { method: "POST" });
              router.refresh();
            } catch {
              setConfirmed(false);
            }
          });
        }}
        className="rounded-md bg-red-600 px-3 py-1.5 text-xs font-medium text-white transition-colors hover:bg-red-700 disabled:opacity-50"
      >
        {isPending ? "処理中..." : "はい、キャンセル"}
      </button>
      <button
        type="button"
        onClick={() => setConfirmed(false)}
        className="rounded-md border border-line px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-slate-50"
      >
        いいえ
      </button>
    </div>
  );
}
