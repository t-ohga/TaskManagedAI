"use client";

import { useRef, useState, useTransition } from "react";

import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { formatApprovalStatus } from "@/lib/i18n/approval-labels";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

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
  const requestRefresh = useDeferredRouterRefresh();
  const formRef = useRef<HTMLFormElement>(null);
  // uncontrolled textarea の draft 検知 (onChange で立てる)。full reload で失われ得る入力。
  const [dirty, setDirty] = useState(false);
  // R10 系: discard event で uncontrolled 入力は form.reset() で消えるが、dirty state も戻す。
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setDirty(false), formRef);
  // R11 系: 他領域 draft の破棄は依頼成功時にのみ commit する (失敗時は draft 無傷)。
  const commitDiscardRef = useRef<() => void>(noop);
  // adversarial R5: 高速二重 submit を同期 lock で防ぐ (isPending は次 render まで false で race)。
  // R7 で役割を「in-flight 窓のみの guard」に限定 (async settle で必ず reset)。terminal lock は requested が担う。
  const inFlightRef = useRef(false);
  // R7 (Codex adversarial HIGH): 修正依頼成功後の terminal lock。requestRefresh の reload は
  // 「mutation 中に作られた別 draft」の破棄確認でキャンセルされ得るため、reload に依存せず
  // form を可視的に無効化し、dead button (見た目有効・実際 inFlightRef で無言ブロック) を防ぐ。
  const [requested, setRequested] = useState(false);
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
            // C-5: action 側 revalidatePath 撤去のため client full reload で表示同期。
            // 自分の修正理由 draft はクリアし、他領域の捕捉済み draft は成功時にのみ破棄。
            formRef.current?.reset();
            setDirty(false);
            commitDiscardRef.current();
            commitDiscardRef.current = noop;
            // R7: 修正依頼は terminal。reload 有無に依存せず requested で form を無効化する
            // (reload が別 draft の破棄確認でキャンセルされても dead button にならない)。
            setRequested(true);
            inFlightRef.current = false;
            requestRefresh();
          } else {
            inFlightRef.current = false;
          }
        })
        .catch((error: unknown) => {
          setResult({
            ok: false,
            error: error instanceof Error ? error.message : "修正依頼に失敗しました"
          });
          inFlightRef.current = false;
        });
    });
  }

  return (
    <form
      action={submitRevisionRequest}
      // C-5: 依頼成功は full reload を伴うため、他領域の未保存 draft があれば mutation 前に破棄確認
      // (except=自form: 自分の修正理由入力では確認しない)。キャンセル時は action を実行しない。
      onSubmit={(event) => {
        // in-flight 中 (inFlightRef) または依頼済み (requested) は再 submit を弾く。
        if (inFlightRef.current || requested) {
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
      ref={discardGuardRef}
      data-unsaved-guard=""
      data-dirty={dirty ? "true" : undefined}
    >
      <fieldset className="grid gap-4" disabled={!canRequestRevision || isPending || requested}>
        <legend className="text-base font-semibold">修正依頼</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">修正理由</span>
          <textarea
            className="min-h-32 resize-y rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            maxLength={2000}
            name="rationale"
            onChange={() => setDirty(true)}
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
