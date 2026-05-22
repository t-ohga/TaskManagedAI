"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";

import type { TicketRead } from "@/lib/api/tickets";

import { updateTicketAction, type UpdateTicketState } from "../actions";

type EditTicketFormProps = {
  ticket: TicketRead;
};

export function EditTicketForm({ ticket }: EditTicketFormProps) {
  const router = useRouter();
  const [result, setResult] = useState<UpdateTicketState>({ kind: "idle" });
  const [isPending, startTransition] = useTransition();

  function submit(formData: FormData): void {
    setResult({ kind: "idle" });
    startTransition(() => {
      void updateTicketAction({ kind: "idle" }, formData)
        .then((nextState) => {
          setResult(nextState);
          if (nextState.kind === "ok") {
            router.refresh();
          }
        })
        .catch((error: unknown) => {
          setResult({
            kind: "error",
            message:
              error instanceof Error ? error.message : "ticket update failed"
          });
        });
    });
  }

  return (
    <form
      action={submit}
      className="rounded-lg border border-line bg-panel p-5 shadow-sm"
      data-testid="edit-ticket-form"
    >
      <input type="hidden" name="ticket_id" value={ticket.id} />
      <fieldset className="grid gap-4" disabled={isPending}>
        <legend className="text-base font-semibold">Ticket 編集</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Title</span>
          <input
            name="title"
            defaultValue={ticket.title}
            className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">Description</span>
          <textarea
            name="description"
            rows={5}
            defaultValue={ticket.description ?? ""}
            className="min-h-32 resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm">
            <span className="font-medium">Status</span>
            <select
              name="status"
              defaultValue={ticket.status}
              className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            >
              <option value="open">open</option>
              <option value="in_progress">in_progress</option>
              <option value="blocked">blocked</option>
              <option value="review">review</option>
              <option value="closed">closed</option>
              <option value="cancelled">cancelled</option>
            </select>
          </label>

          <label className="grid gap-2 text-sm">
            <span className="font-medium">Priority</span>
            <select
              name="priority"
              defaultValue={ticket.priority ?? ""}
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
            {isPending ? "保存中..." : "保存"}
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
            Ticket 更新成功 (id: {result.ticket_id})
          </p>
        ) : null}
      </fieldset>
    </form>
  );
}
