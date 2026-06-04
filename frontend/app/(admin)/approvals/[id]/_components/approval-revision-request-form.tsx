"use client";

import { useRouter } from "next/navigation";
import { useRef, useState, useTransition } from "react";

import { formatApprovalStatus } from "@/lib/i18n/approval-labels";

import {
  requestApprovalRevisionAction,
  type RequestRevisionActionResult
} from "../_actions/request-revision";

type ApprovalRevisionRequestFormProps = {
  approvalId: string;
  initialStatus: string;
};

export function ApprovalRevisionRequestForm({
  approvalId,
  initialStatus
}: ApprovalRevisionRequestFormProps) {
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [result, setResult] = useState<RequestRevisionActionResult | null>(null);
  const [isPending, startTransition] = useTransition();
  const canRequestRevision = initialStatus === "pending";

  function submitRevisionRequest(formData: FormData): void {
    if (!canRequestRevision) {
      return;
    }

    setResult(null);
    startTransition(() => {
      void requestApprovalRevisionAction(approvalId, formData)
        .then((nextResult) => {
          setResult(nextResult);
          if (nextResult.ok) {
            formRef.current?.reset();
            router.refresh();
          }
        })
        .catch((error: unknown) => {
          setResult({
            ok: false,
            error: error instanceof Error ? error.message : "修正依頼に失敗しました"
          });
        });
    });
  }

  return (
    <form
      action={submitRevisionRequest}
      className="rounded-lg border border-line bg-panel p-5 shadow-sm"
      ref={formRef}
    >
      <fieldset className="grid gap-4" disabled={!canRequestRevision || isPending}>
        <legend className="text-base font-semibold">修正依頼</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">修正理由</span>
          <textarea
            className="min-h-32 resize-y rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            maxLength={2000}
            name="rationale"
            placeholder="再提出前に直すべき内容"
            required
          />
        </label>

        <button
          className="rounded-md border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm font-semibold text-attention outline-offset-2 hover:bg-amber-100 dark:hover:bg-amber-900/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:border-line disabled:bg-slate-100 dark:disabled:bg-slate-800 disabled:text-slate-400 dark:disabled:text-slate-500"
          type="submit"
        >
          修正依頼
        </button>
      </fieldset>

      {result ? (
        <p
          className={`mt-4 rounded-md p-3 text-sm ${
            result.ok ? "bg-amber-50 dark:bg-amber-950/40 text-attention" : "bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300"
          }`}
          role="status"
        >
          {result.ok
            ? `修正依頼を保存しました: ${formatApprovalStatus(result.status)}`
            : result.error}
        </p>
      ) : null}
    </form>
  );
}
