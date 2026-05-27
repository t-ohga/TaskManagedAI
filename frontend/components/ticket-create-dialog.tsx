"use client";

import { useActionState, useState } from "react";

import { createTicketAction, type CreateTicketState } from "@/app/(admin)/tickets/actions";

const initialState: CreateTicketState = { kind: "idle" };

export function TicketCreateDialog({ projectSlug, projectId }: { projectSlug: string; projectId?: string | undefined }) {
  const [open, setOpen] = useState(false);
  const [state, formAction, pending] = useActionState(createTicketAction, initialState);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg border-2 border-dashed border-accent/30 bg-accent/5 px-4 py-2 text-sm font-medium text-accent transition-colors hover:border-accent/50 hover:bg-accent/10"
        type="button"
      >
        + チケットを作成
      </button>
    );
  }

  return (
    <div className="rounded-lg border border-line bg-panel p-4 shadow-md">
      <h3 className="mb-3 text-sm font-semibold">新規チケット作成</h3>
      {state.kind === "ok" && (
        <div className="mb-3 rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-700">
          チケットを作成しました
        </div>
      )}
      {state.kind === "error" && (
        <div className="mb-3 rounded-md bg-red-50 px-3 py-2 text-xs text-red-700">
          {state.message}
        </div>
      )}
      <form action={formAction} className="grid gap-3">
        <input type="hidden" name="slug" value="ticket" />
        
        {projectId && <input type="hidden" name="project_id" value={projectId} />}
        <div>
          <label htmlFor="title" className="text-xs font-medium text-muted-foreground">
            タイトル
          </label>
          <input
            id="title"
            name="title"
            type="text"
            required
            placeholder="チケットのタイトル"
            onChange={(e) => {
              const slug = e.target.value
                .toLowerCase()
                .replace(/[^a-z0-9぀-ゟ゠-ヿ一-鿿]+/g, '-')
                .replace(/^-|-$/g, '')
                .slice(0, 40) || 'ticket';
              const slugInput = e.target.form?.querySelector('input[name="slug"]') as HTMLInputElement;
              if (slugInput) slugInput.value = slug + '-' + Date.now() % 100000;
            }}
            className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div>
          <label htmlFor="description" className="text-xs font-medium text-muted-foreground">
            説明 (任意)
          </label>
          <textarea
            id="description"
            name="description"
            rows={2}
            placeholder="詳細な説明"
            className="mt-1 w-full rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
          />
        </div>
        <div className="flex items-center gap-2">
          <select
            name="priority"
            className="rounded-md border border-line px-2 py-1.5 text-xs focus:border-accent focus:outline-none"
          >
            <option value="">優先度なし</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="critical">最優先</option>
          </select>
        </div>
        <div className="flex gap-2">
          <button
            type="submit"
            disabled={pending}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-accent/90 disabled:opacity-50"
          >
            {pending ? "作成中..." : "作成"}
          </button>
          <button
            type="button"
            onClick={() => setOpen(false)}
            className="rounded-md border border-line px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-slate-50"
          >
            キャンセル
          </button>
        </div>
      </form>
    </div>
  );
}
