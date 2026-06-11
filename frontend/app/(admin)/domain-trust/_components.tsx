"use client";

import { useActionState, useEffect, useRef, useState, type RefObject } from "react";

import {
  TrustTierEnum,
  trustTierLabel,
  trustTierTone,
  type DomainTrust,
  type TrustTier
} from "@/lib/domain/research-advanced";
import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

import {
  createDomainTrustAction,
  deleteDomainTrustAction,
  updateDomainTrustAction,
  type DomainTrustActionState
} from "./actions";

const INITIAL: DomainTrustActionState = { kind: "idle" };

const TONE_CLASS: Record<"danger" | "warning" | "success" | "muted", string> = {
  danger: "border-rose-300 bg-rose-50 text-rose-700 dark:border-rose-800 dark:bg-rose-950/40 dark:text-rose-300",
  warning:
    "border-amber-300 bg-amber-50 text-amber-700 dark:border-amber-800 dark:bg-amber-950/40 dark:text-amber-300",
  success:
    "border-emerald-300 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300",
  muted: "border-line bg-canvas text-muted-foreground"
};

function StatusMessage({ state }: { readonly state: DomainTrustActionState }) {
  if (state.kind === "error") {
    return (
      <p role="status" className="rounded-md bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
        {state.message}
      </p>
    );
  }
  if (state.kind === "ok") {
    return (
      <p role="status" className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
        {state.message}
      </p>
    );
  }
  return null;
}

function TierBadge({ tier }: { readonly tier: TrustTier }) {
  return (
    <span
      className={`inline-flex items-center rounded-full border px-2 py-0.5 text-xs font-medium ${TONE_CLASS[trustTierTone(tier)]}`}
    >
      信頼度: {trustTierLabel(tier)}
    </span>
  );
}

const TIER_OPTIONS = TrustTierEnum.options;

function AddForm({ onSuccess }: { readonly onSuccess: () => void }) {
  const formRef = useRef<HTMLFormElement>(null);
  // C-5: full reload で失われ得る入力 (domain / rationale) を draft guard に登録。
  const [dirty, setDirty] = useState(false);
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setDirty(false), formRef);
  // adversarial R2: pre-commit gate で承認済みの他領域 draft の破棄関数を保持。
  const commitDiscardRef = useRef<() => void>(noop);
  // 成功時の入力クリア (uncontrolled は form.reset) は action wrapper 内で行う
  // (effect 内 setState を避ける、comment-form と同 pattern)。表示更新は effect の full reload。
  const [state, action, pending] = useActionState(
    async (prev: DomainTrustActionState, formData: FormData): Promise<DomainTrustActionState> => {
      const result = await createDomainTrustAction(prev, formData);
      if (result.kind === "ok") {
        formRef.current?.reset();
        setDirty(false);
      }
      return result;
    },
    INITIAL
  );
  useEffect(() => {
    if (state.kind === "ok") {
      commitDiscardRef.current();
      commitDiscardRef.current = noop;
      onSuccess();
    }
  }, [state, onSuccess]);
  return (
    <form
      ref={discardGuardRef}
      action={action}
      onChange={() => setDirty(true)}
      onSubmit={(event) => {
        const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
        if (!approved) {
          event.preventDefault();
          return;
        }
        commitDiscardRef.current = commit;
      }}
      className="grid gap-3 rounded-md border border-line bg-panel p-4"
      data-testid="domain-trust-add-form"
      data-unsaved-guard=""
      data-dirty={dirty ? "true" : undefined}
    >
      <fieldset className="grid gap-3 sm:grid-cols-[2fr_1fr] sm:items-end" disabled={pending}>
        <legend className="text-sm font-medium">ドメイン信頼度を追加</legend>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">ドメイン (ホスト名)</span>
          <input
            name="domain"
            required
            placeholder="example.com"
            className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>
        <label className="grid gap-1 text-sm">
          <span className="font-medium">信頼度</span>
          <select
            name="trust_tier"
            defaultValue="medium"
            className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            {TIER_OPTIONS.map((tier) => (
              <option key={tier} value={tier}>
                {trustTierLabel(tier)}
              </option>
            ))}
          </select>
        </label>
      </fieldset>
      <label className="grid gap-1 text-sm">
        <span className="font-medium">理由 (任意)</span>
        <input
          name="rationale"
          maxLength={1000}
          placeholder="政府機関の一次情報源など"
          className="rounded-md border border-line bg-canvas px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        />
      </label>
      <div>
        <button
          type="submit"
          disabled={pending}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
        >
          {pending ? "登録中..." : "登録"}
        </button>
      </div>
      <StatusMessage state={state} />
    </form>
  );
}

function DomainTrustRow({ entry, onSuccess }: { readonly entry: DomainTrust; readonly onSuccess: () => void }) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  const editFormRef = useRef<HTMLFormElement>(null);
  // C-5: 編集中の trust_tier / rationale は full reload で失われ得る draft。
  const [editDirty, setEditDirty] = useState(false);
  const editDiscardRef = useDraftDiscardRef<HTMLFormElement>(() => setEditDirty(false), editFormRef);
  // adversarial R2/R4: pre-commit gate の承認済み draft 破棄関数を action ごとに保持 (shared ref は並行 submit で誤破棄)。
  const updateCommitRef = useRef<() => void>(noop);
  const deleteCommitRef = useRef<() => void>(noop);
  // adversarial R3: 副作用は any-ok effect ではなく各 action wrapper で action-scoped に実行する。
  const finish = (ref: RefObject<() => void>) => {
    ref.current();
    ref.current = noop;
    onSuccess();
  };
  // 編集 form は成功時に form.reset() しない (defaultValue=entry prop で巻き戻る、F-001)。代わりに自分の
  // dirty だけを wrapper 内 (成功確定後 / requestRefresh 前) でクリアし、保存成功後の reload 直前 confirm が
  // 自分自身を誤検知しないようにする (adversarial finding: saved-form-dirty が full reload を阻害し表示 stale 化)。
  const [updateState, updateAction, updatePending] = useActionState(
    async (prev: DomainTrustActionState, formData: FormData): Promise<DomainTrustActionState> => {
      const result = await updateDomainTrustAction(prev, formData);
      if (result.kind === "ok") {
        setEditDirty(false);
        finish(updateCommitRef);
      }
      return result;
    },
    INITIAL
  );
  const [deleteState, deleteAction, deletePending] = useActionState(
    async (prev: DomainTrustActionState, formData: FormData): Promise<DomainTrustActionState> => {
      const result = await deleteDomainTrustAction(prev, formData);
      // delete 成功時は row 自体が消える。entry は独立 row のため巻き戻しは entry 単位で閉じる。
      if (result.kind === "ok") finish(deleteCommitRef);
      return result;
    },
    INITIAL
  );

  const anyPending = updatePending || deletePending;

  return (
    <li className="grid gap-3 rounded-md border border-line bg-panel p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="font-mono text-sm text-ink">{entry.domain}</span>
        <TierBadge tier={entry.trust_tier} />
      </div>
      {entry.rationale ? <p className="text-sm text-muted-foreground">{entry.rationale}</p> : null}

      <form
        ref={editDiscardRef}
        action={updateAction}
        onChange={() => setEditDirty(true)}
        onSubmit={(event) => {
          const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
          if (!approved) {
            event.preventDefault();
            return;
          }
          updateCommitRef.current = commit;
        }}
        className="flex flex-wrap items-end gap-2"
        data-testid="domain-trust-edit-form"
        data-unsaved-guard=""
        data-dirty={editDirty ? "true" : undefined}
      >
        <input type="hidden" name="entry_id" value={entry.id} />
        <label className="grid gap-1 text-xs">
          <span className="font-medium">信頼度を変更</span>
          <select
            name="trust_tier"
            defaultValue={entry.trust_tier}
            disabled={anyPending}
            className="rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          >
            {TIER_OPTIONS.map((tier) => (
              <option key={tier} value={tier}>
                {trustTierLabel(tier)}
              </option>
            ))}
          </select>
        </label>
        <label className="grid gap-1 text-xs flex-1 min-w-40">
          <span className="font-medium">理由</span>
          <input
            name="rationale"
            defaultValue={entry.rationale ?? ""}
            maxLength={1000}
            disabled={anyPending}
            className="rounded-md border border-line bg-canvas px-2 py-1 text-sm"
          />
        </label>
        <button
          type="submit"
          disabled={anyPending}
          className="rounded-md border border-line px-3 py-1 text-sm font-medium hover:bg-canvas disabled:opacity-60"
        >
          {updatePending ? "保存中..." : "保存"}
        </button>
      </form>
      <StatusMessage state={updateState} />

      {confirmDelete ? (
        <form
          action={deleteAction}
          onSubmit={(event) => {
            const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
            if (!approved) {
              event.preventDefault();
              return;
            }
            deleteCommitRef.current = commit;
          }}
          className="flex items-center gap-2"
          data-testid="domain-trust-delete-form"
        >
          <input type="hidden" name="entry_id" value={entry.id} />
          <span className="text-sm text-rose-700 dark:text-rose-300">削除しますか?</span>
          <button
            type="submit"
            disabled={anyPending}
            className="rounded-md bg-rose-600 px-3 py-1 text-sm font-medium text-white hover:bg-rose-700 disabled:opacity-60"
          >
            {deletePending ? "削除中..." : "削除する"}
          </button>
          <button
            type="button"
            onClick={() => setConfirmDelete(false)}
            className="rounded-md border border-line px-3 py-1 text-sm hover:bg-canvas"
          >
            キャンセル
          </button>
        </form>
      ) : (
        <button
          type="button"
          onClick={() => setConfirmDelete(true)}
          className="self-start rounded-md border border-rose-300 px-3 py-1 text-sm font-medium text-rose-700 hover:bg-rose-50 dark:border-rose-800 dark:text-rose-300 dark:hover:bg-rose-950/40"
        >
          削除
        </button>
      )}
      <StatusMessage state={deleteState} />
    </li>
  );
}

export function DomainTrustManager({ entries }: { readonly entries: readonly DomainTrust[] }) {
  // C-5: action 側 revalidatePath 撤去のため、表示更新は client full reload。
  // requestRefresh は安定参照のため onSuccess に直接渡せる (effect 再発火による reload ループを防ぐ、F-005)。
  const requestRefresh = useDeferredRouterRefresh();
  return (
    <div className="grid gap-5">
      <AddForm onSuccess={requestRefresh} />
      {entries.length === 0 ? (
        <p className="rounded-md border border-dashed border-line bg-canvas p-4 text-sm text-muted-foreground">
          登録済みのドメイン信頼度はありません。
        </p>
      ) : (
        <ul className="grid gap-3">
          {entries.map((entry) => (
            <DomainTrustRow key={entry.id} entry={entry} onSuccess={requestRefresh} />
          ))}
        </ul>
      )}
    </div>
  );
}
