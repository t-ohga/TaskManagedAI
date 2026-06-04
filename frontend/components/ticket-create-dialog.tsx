"use client";

import { useActionState, useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import type { Route } from "next";

import { createTicketAction, type CreateTicketState } from "@/app/(admin)/tickets/actions";
import { assigneeSelectOptions, type AssignableActor } from "@/lib/domain/assignee";
import { MarkdownEditor } from "@/components/markdown-editor";

const initialState: CreateTicketState = { kind: "idle" };

type TicketCreateDialogProps = {
  // A-6 (ADR-00046): 担当者候補 (tenant 内 human)。取得失敗時は [] (作成は未割当のまま可能)。
  assignableActors?: AssignableActor[];
};

// 作成先 project は server action が session の current_project から resolve する
// (server-owned-boundary §1: project_id は caller-supplied 禁止)。本 dialog は
// 呼び出し側で「現在の project を表示中のときだけ」mount される (tickets/page.tsx)。
export function TicketCreateDialog({ assignableActors = [] }: TicketCreateDialogProps) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [titleError, setTitleError] = useState<string | null>(null);
  const [slug, setSlug] = useState("ticket");
  const [state, formAction, pending] = useActionState(createTicketAction, initialState);

  function deriveSlug(title: string): string {
    const base = title
      .toLowerCase()
      .replace(/[^a-z0-9぀-ゟ゠-ヿ一-鿿]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 40) || "ticket";
    return `${base}-${Date.now() % 100000}`;
  }

  useEffect(() => {
    if (state.kind === "ok") {
      // G-5 (UI 監査 fix): 作成後は一覧 refresh ではなく作成したチケット詳細へ遷移する。
      const ticketId = state.ticket_id;
      const timer = setTimeout(() => {
        setOpen(false);
        router.push(`/tickets/${ticketId}` as Route);
      }, 1200);
      return () => clearTimeout(timer);
    }
  }, [state, router]);

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
      {state.kind === "ok" ? <div className="mb-3 rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-xs text-emerald-700 dark:text-emerald-300">
          チケットを作成しました
        </div> : null}
      {state.kind === "error" ? <div className="mb-3 rounded-md bg-red-50 dark:bg-red-950/40 px-3 py-2 text-xs text-red-700 dark:text-red-300">
          {state.message}
        </div> : null}
      <form action={formAction} className="grid gap-3">
        <input type="hidden" name="slug" value={slug} />
        <div>
          <label htmlFor="title" className="text-xs font-medium text-muted-foreground">
            タイトル <span className="text-danger">*</span>
          </label>
          <input
            id="title"
            name="title"
            type="text"
            required
            aria-required="true"
            aria-invalid={titleError ? "true" : undefined}
            aria-describedby={titleError ? "title-error" : undefined}
            placeholder="チケットのタイトル"
            onChange={(e) => {
              setTitleError(e.target.value.trim() === "" ? "タイトルは必須です" : null);
              setSlug(deriveSlug(e.target.value));
            }}
            className={`mt-1 w-full rounded-md border px-3 py-2 text-sm focus:outline-none focus:ring-1 ${
              titleError ? "border-danger focus:border-danger focus:ring-danger" : "border-line focus:border-accent focus:ring-accent"
            }`}
          />
          {titleError ? <p id="title-error" className="mt-1 text-xs text-danger" role="alert">{titleError}</p> : null}
        </div>
        <div>
          <span className="text-xs font-medium text-muted-foreground">説明 (任意)</span>
          <div className="mt-1">
            <MarkdownEditor
              name="description"
              rows={2}
              placeholder="詳細な説明"
              ariaLabel="説明"
              textareaClassName="w-full resize-y rounded-md border border-line px-3 py-2 text-sm focus:border-accent focus:outline-none focus:ring-1 focus:ring-accent"
            />
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <select
            name="priority"
            aria-label="優先度"
            className="rounded-md border border-line px-2 py-1.5 text-xs focus:border-accent focus:outline-none"
          >
            <option value="">優先度なし</option>
            <option value="low">低</option>
            <option value="medium">中</option>
            <option value="high">高</option>
            <option value="critical">最優先</option>
          </select>
          {/* A-6: 担当者 (任意)。候補なし (取得失敗 / human 0) でも「未割当」で作成可能。 */}
          <select
            name="assignee_actor_id"
            aria-label="担当者"
            defaultValue=""
            className="rounded-md border border-line px-2 py-1.5 text-xs focus:border-accent focus:outline-none"
          >
            <option value="">担当者なし</option>
            {assigneeSelectOptions(assignableActors, null).map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
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
            className="rounded-md border border-line px-4 py-2 text-sm font-medium text-muted-foreground transition-colors hover:bg-slate-50 dark:hover:bg-slate-800"
          >
            キャンセル
          </button>
        </div>
      </form>
    </div>
  );
}
