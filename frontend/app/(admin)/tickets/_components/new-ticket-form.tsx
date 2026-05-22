"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import { createTicketAction, type CreateTicketState } from "../actions";

export function NewTicketForm() {
  const router = useRouter();
  const [isOpen, setIsOpen] = useState(false);
  const [result, setResult] = useState<CreateTicketState>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  function submit(formData: FormData): void {
    // Codex PR #120 R1 F-PR120-001/002 (P2) fix: startTransition callback を
    // async 化し、`await` で完了まで pending 状態を保持。これにより:
    // - isPending が POST resolve まで active (二重 submit 防止)
    // - fields は backend 成功まで reset されない (error 時 user の入力保持)
    //
    // 旧実装は `() => { void promise.then(...) }` (sync callback + fire-and-forget) で
    // startTransition は callback return 直後に終了 → pending flag が POST 完了前に drop。
    setResult({ kind: "idle" });
    startTransition(async () => {
      try {
        const nextState = await createTicketAction({ kind: "idle" }, formData);
        setResult(nextState);
        if (nextState.kind === "ok") {
          router.refresh();
          // 成功後 form 閉じる
          setIsOpen(false);
        }
      } catch (error: unknown) {
        setResult({
          kind: "error",
          message:
            error instanceof Error ? error.message : "ticket creation failed"
        });
      }
    });
  }

  if (!isOpen) {
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
      action={submit}
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
            onClick={() => {
              setIsOpen(false);
              setResult({ kind: "idle" });
            }}
            className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium shadow-sm hover:bg-panel-muted"
          >
            キャンセル
          </button>
        </div>

        {result.kind === "error" ? (
          <p
            role="status"
            className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            {result.message}
          </p>
        ) : null}
        {result.kind === "ok" ? (
          <p
            role="status"
            className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
          >
            Ticket created (id: {result.ticket_id})
          </p>
        ) : null}
      </fieldset>
    </form>
  );
}
