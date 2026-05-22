"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect, useState } from "react";

import { createTicketAction, type CreateTicketState } from "../actions";

const INITIAL_STATE: CreateTicketState = { kind: "idle" };

export function NewTicketForm() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);

  // SP-012-11.1 BL-TCU-016: React 19 useActionState pattern (Codex PR #120 P2 完全 migration)
  // - state: action 結果 (idle / ok / error)
  // - formAction: form の action prop に直接渡す handler
  // - isPending: action 実行中 true (POST 完了まで保持、二重 submit 防止)
  const [state, formAction, isPending] = useActionState(
    createTicketAction,
    INITIAL_STATE
  );

  // 成功時の副作用 (router.refresh) は useEffect で副作用化
  useEffect(() => {
    if (state.kind === "ok") {
      router.refresh();
    }
  }, [state, router]);

  // state.kind === "ok" で form 自動 close (render-time derived、useEffect 内
  // setIsOpen 回避 = React 19 react-hooks rule "no setState in effect" 遵守)
  const showForm = isOpen && state.kind !== "ok";

  if (!showForm) {
    return (
      <div>
        <button
          type="button"
          onClick={() => setIsOpen(true)}
          className="rounded-md border border-line bg-panel px-3 py-2 text-sm font-medium shadow-sm hover:bg-panel-muted"
        >
          + 新規 Ticket
        </button>
      </div>
    );
  }

  return (
    <form
      action={formAction}
      className="rounded-lg border border-line bg-panel p-5 shadow-sm"
      data-testid="new-ticket-form"
    >
      <fieldset className="grid gap-4" disabled={isPending}>
        <legend className="text-base font-semibold">新規 Ticket 作成</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Slug (kebab-case)</span>
          <input
            name="slug"
            required
            placeholder="my-ticket-slug"
            pattern="^[a-z0-9]+(-[a-z0-9]+)*$"
            className="rounded-md border border-line bg-white px-3 py-2 text-sm font-mono outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Title</span>
          <input
            name="title"
            required
            placeholder="Ticket title"
            className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Description (任意)</span>
          <textarea
            name="description"
            rows={3}
            placeholder="ticket description"
            className="min-h-20 resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm">
            <span className="font-medium">Status</span>
            <select
              name="status"
              defaultValue="open"
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="open">open</option>
              <option value="in_progress">in_progress</option>
              <option value="blocked">blocked</option>
              <option value="review">review</option>
            </select>
          </label>

          <label className="grid gap-2 text-sm">
            <span className="font-medium">Priority (任意)</span>
            <select
              name="priority"
              defaultValue=""
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="">(未指定)</option>
              <option value="low">low</option>
              <option value="medium">medium</option>
              <option value="high">high</option>
              <option value="critical">critical</option>
            </select>
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
          >
            {isPending ? "送信中..." : "作成"}
          </button>
          <button
            type="button"
            onClick={() => setIsOpen(false)}
            className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium shadow-sm hover:bg-panel-muted"
          >
            キャンセル
          </button>
        </div>

        {/* ok 時は showForm が false で form 自体非表示、success フィードバックは
            router.refresh による list 再表示 + new ticket 一覧出現で代替 */}
        {state.kind === "error" ? (
          <p
            role="status"
            className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            {state.message}
          </p>
        ) : null}
      </fieldset>
    </form>
  );
}
