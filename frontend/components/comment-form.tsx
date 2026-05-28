"use client";

import { useActionState, useState } from "react";

type CommentFormProps = {
  ticketId: string;
  onSubmit: (formData: FormData) => Promise<{ kind: "ok" } | { kind: "error"; message: string }>;
};

export function CommentForm({ ticketId, onSubmit }: CommentFormProps) {
  const [body, setBody] = useState("");
  const [state, formAction, pending] = useActionState(
    async (_prev: { kind: string; message?: string }, formData: FormData) => {
      const result = await onSubmit(formData);
      if (result.kind === "ok") setBody("");
      return result;
    },
    { kind: "idle" }
  );

  return (
    <form action={formAction} className="grid gap-3">
      <input type="hidden" name="ticket_id" value={ticketId} />
      <textarea
        name="body"
        value={body}
        onChange={(e) => setBody(e.target.value)}
        rows={3}
        required
        placeholder="コメントを入力 (Markdown 対応)"
        className="w-full rounded-md border border-line bg-transparent px-3 py-2 text-sm outline-none focus:border-accent"
        aria-label="コメント本文"
      />
      {state.kind === "error" && (
        <p className="text-xs text-danger">{state.message}</p>
      )}
      <div className="flex justify-end">
        <button
          type="submit"
          disabled={pending || !body.trim()}
          className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
        >
          {pending ? "送信中..." : "コメントを追加"}
        </button>
      </div>
    </form>
  );
}
