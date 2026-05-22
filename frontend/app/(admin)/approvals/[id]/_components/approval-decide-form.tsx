"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { formatApprovalStatus } from "@/lib/i18n/approval-labels";

import {
  decideApprovalAction,
  type DecideActionResult
} from "../_actions/decide";

type ApprovalDecideFormProps = {
  approvalId: string;
  initialStatus: string;
};

export function ApprovalDecideForm({ approvalId, initialStatus }: ApprovalDecideFormProps) {
  const router = useRouter();
  const [result, setResult] = useState<DecideActionResult | null>(null);
  const [isPending, startTransition] = useTransition();
  const canDecide = initialStatus === "pending";

  function submitDecision(formData: FormData): void {
    if (!canDecide) {
      return;
    }

    setResult(null);
    startTransition(() => {
      void decideApprovalAction(approvalId, formData)
        .then((nextResult) => {
          setResult(nextResult);
          if (nextResult.ok) {
            router.refresh();
          }
        })
        .catch((error: unknown) => {
          setResult({
            ok: false,
            error: error instanceof Error ? error.message : "判定に失敗しました"
          });
        });
    });
  }

  return (
    <form action={submitDecision} className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <fieldset className="grid gap-4" disabled={!canDecide || isPending}>
        <legend className="text-base font-semibold">レビュー判定</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">理由</span>
          <textarea
            className="min-h-28 resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            maxLength={2000}
            name="rationale"
            placeholder="この判定の理由"
          />
        </label>

        <div className="flex flex-wrap gap-2">
          <button
            className="rounded-md bg-accent px-3 py-2 text-sm font-semibold text-white outline-offset-2 hover:bg-teal-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:bg-slate-300"
            name="action"
            type="submit"
            value="approve"
          >
            承認
          </button>
          <button
            className="rounded-md border border-line bg-white px-3 py-2 text-sm font-semibold text-danger outline-offset-2 hover:bg-rose-50 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:text-slate-400"
            name="action"
            type="submit"
            value="reject"
          >
            却下
          </button>
        </div>
      </fieldset>

      {result ? (
        <p
          className={`mt-4 rounded-md p-3 text-sm ${
            result.ok ? "bg-emerald-50 text-emerald-700" : "bg-rose-50 text-rose-700"
          }`}
          role="status"
        >
          {result.ok ? `判定を保存しました: ${formatApprovalStatus(result.status)}` : result.error}
        </p>
      ) : null}
    </form>
  );
}
