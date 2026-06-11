"use client";

import { useRef, useState, useTransition } from "react";

import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { formatApprovalStatus } from "@/lib/i18n/approval-labels";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

import {
  decideApprovalAction,
  type DecideActionResult
} from "../_actions/decide";

type ApprovalDecideFormProps = {
  approvalId: string;
  initialStatus: string;
};

export function ApprovalDecideForm({ approvalId, initialStatus }: ApprovalDecideFormProps) {
  const requestRefresh = useDeferredRouterRefresh();
  const formRef = useRef<HTMLFormElement>(null);
  // uncontrolled textarea の draft 検知 (onChange で立てる)。full reload で失われ得る入力。
  const [dirty, setDirty] = useState(false);
  // R10 系: discard event で uncontrolled 入力は form.reset() で消えるが、dirty state も戻す。
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setDirty(false), formRef);
  // R11 系: 他領域 draft の破棄は判定成功時にのみ commit する (失敗時は draft 無傷)。
  const commitDiscardRef = useRef<() => void>(noop);
  // adversarial R5: approve/reject の二重 submit を同期 lock で防ぐ (isPending は次 render まで false で race)。
  // R7 で役割を「in-flight 窓のみの guard」に限定 (async settle で必ず reset)。terminal lock は decided が担う。
  const inFlightRef = useRef(false);
  // R7 (Codex adversarial HIGH): 判定成功後の terminal lock。requestRefresh の reload は
  // 「mutation 中に作られた別 draft」の破棄確認でキャンセルされ得る (reload しない) ため、
  // reload に依存せず form を可視的に無効化し、dead button (見た目有効・実際 inFlightRef で無言ブロック) を防ぐ。
  const [decided, setDecided] = useState(false);
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
            // C-5: action 側 revalidatePath 撤去のため client full reload で表示同期。
            // 自分の理由 draft はクリアし、他領域の捕捉済み draft は成功時にのみ破棄。
            formRef.current?.reset();
            setDirty(false);
            commitDiscardRef.current();
            commitDiscardRef.current = noop;
            // R7: 判定は terminal。reload 有無に依存せず decided で form を無効化する
            // (reload が別 draft の破棄確認でキャンセルされても dead button にならない)。
            setDecided(true);
            inFlightRef.current = false;
            requestRefresh();
          } else {
            inFlightRef.current = false;
          }
        })
        .catch((error: unknown) => {
          setResult({
            ok: false,
            error: error instanceof Error ? error.message : "判定に失敗しました"
          });
          inFlightRef.current = false;
        });
    });
  }

  return (
    <form
      ref={discardGuardRef}
      action={submitDecision}
      // C-5: 判定成功は full reload を伴うため、他領域の未保存 draft があれば mutation 前に破棄確認
      // (except=自form: 自分の理由入力では確認しない)。キャンセル時は action を実行しない。
      onSubmit={(event) => {
        // in-flight 中 (inFlightRef) または判定済み (decided) は再 submit を弾く。
        if (inFlightRef.current || decided) {
          event.preventDefault();
          return;
        }
        const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
        if (!approved) {
          event.preventDefault();
          return;
        }
        inFlightRef.current = true;
        commitDiscardRef.current = commit;
      }}
      className="rounded-lg border border-line bg-panel p-5 shadow-sm"
      data-unsaved-guard=""
      data-dirty={dirty ? "true" : undefined}
    >
      <fieldset className="grid gap-4" disabled={!canDecide || isPending || decided}>
        <legend className="text-base font-semibold">レビュー判定</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">理由</span>
          <textarea
            className="min-h-28 resize-y rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            maxLength={2000}
            name="rationale"
            onChange={() => setDirty(true)}
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
            className="rounded-md border border-line bg-panel px-3 py-2 text-sm font-semibold text-danger outline-offset-2 hover:bg-rose-50 dark:hover:bg-rose-950/40 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent disabled:cursor-not-allowed disabled:text-slate-400 dark:disabled:text-slate-500"
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
            result.ok ? "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300" : "bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300"
          }`}
          role="status"
        >
          {result.ok ? `判定を保存しました: ${formatApprovalStatus(result.status)}` : result.error}
        </p>
      ) : null}
    </form>
  );
}
