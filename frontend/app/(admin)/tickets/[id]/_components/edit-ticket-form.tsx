"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import { formatTicketPriority, formatTicketStatus } from "@/lib/i18n/ticket-labels";
import type { TicketRead } from "@/lib/api/tickets";

import { updateTicketAction, type UpdateTicketState } from "../actions";

type EditTicketFormProps = {
  ticket: TicketRead;
};

const INITIAL_STATE: UpdateTicketState = { kind: "idle" };

export function EditTicketForm({ ticket }: EditTicketFormProps) {
  const router = useRouter();

  // SP-012-11.1 BL-TCU-016: React 19 useActionState (Codex PR #120 P2 完全 migration)
  const [state, formAction, isPending] = useActionState(
    updateTicketAction,
    INITIAL_STATE
  );

  // 成功時 router.refresh で 詳細 + 一覧 再 fetch (revalidatePath 連動)
  useEffect(() => {
    if (state.kind === "ok") {
      router.refresh();
    }
  }, [state, router]);

  return (
    <form
      action={formAction}
      className="rounded-lg border border-line bg-panel p-5 shadow-sm"
      data-testid="edit-ticket-form"
    >
      <input type="hidden" name="ticket_id" value={ticket.id} />
      <fieldset className="grid gap-4" disabled={isPending}>
        <legend className="text-base font-semibold">チケット編集</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">タイトル</span>
          <input
            name="title"
            defaultValue={ticket.title}
            className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">説明</span>
          <textarea
            name="description"
            rows={5}
            defaultValue={ticket.description ?? ""}
            className="min-h-32 resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm">
            <span className="font-medium">状態</span>
            <select
              name="status"
              defaultValue={ticket.status}
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="open">{formatTicketStatus("open")}</option>
              <option value="in_progress">{formatTicketStatus("in_progress")}</option>
              <option value="blocked">{formatTicketStatus("blocked")}</option>
              <option value="review">{formatTicketStatus("review")}</option>
              <option value="closed">{formatTicketStatus("closed")}</option>
              <option value="cancelled">{formatTicketStatus("cancelled")}</option>
            </select>
          </label>

          <label className="grid gap-2 text-sm">
            <span className="font-medium">優先度</span>
            <select
              name="priority"
              defaultValue={ticket.priority ?? ""}
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="">(未指定)</option>
              <option value="low">{formatTicketPriority("low")}</option>
              <option value="medium">{formatTicketPriority("medium")}</option>
              <option value="high">{formatTicketPriority("high")}</option>
              <option value="critical">{formatTicketPriority("critical")}</option>
            </select>
          </label>
        </div>

        <div className="flex flex-wrap gap-2">
          <button
            type="submit"
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
          >
            {isPending ? "保存中..." : "保存"}
          </button>
        </div>

        {state.kind === "error" ? (
          <p
            role="status"
            className="rounded-md bg-rose-50 px-3 py-2 text-sm text-rose-700"
          >
            {state.message}
          </p>
        ) : null}
        {state.kind === "ok" ? (
          <p
            role="status"
            className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-700"
          >
            チケットを更新しました (id: {state.ticket_id})
          </p>
        ) : null}
      </fieldset>
    </form>
  );
}
