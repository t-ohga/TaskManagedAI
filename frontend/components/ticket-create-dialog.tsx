"use client";

import { useActionState, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import type { Route } from "next";

import { createTicketAction, type CreateTicketState } from "@/app/(admin)/tickets/actions";
import { confirmDiscardUnsavedDrafts } from "@/lib/full-reload";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";
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

  // R10 (Codex adversarial HIGH): form.reset() は MarkdownEditor の内部 state を戻せず、slug /
  // titleError state も残る。discard event で state を初期化し、nonce remount で editor 内部
  // state ごと破棄する (破棄後に title だけ入れて submit すると stale description が送信される
  // 経路の封鎖)。
  const [discardNonce, setDiscardNonce] = useState(0);
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => {
    setTitleError(null);
    setSlug("ticket");
    setDiscardNonce((n) => n + 1);
  });

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
      // C-4 UX fix (Mac 実機検証): 旧版は 1.2s setTimeout 後に遷移していたが、action 成功後の
      // revalidatePath 再レンダーと effect cleanup が競合すると timer が発火せず「成功 banner +
      // 開いたままの form」で止まる。timer を廃して即時遷移し、遷移が遅延した場合の fallback と
      // して成功 banner に明示の詳細 link も出す (下記 JSX)。
      router.push(`/tickets/${state.ticket_id}` as Route);
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
          チケットを作成しました。詳細ページへ移動します…{" "}
          <Link
            href={`/tickets/${state.ticket_id}` as Route}
            className="font-medium underline underline-offset-2"
          >
            移動しない場合はこちら
          </Link>
        </div> : null}
      {state.kind === "error" ? <div className="mb-3 rounded-md bg-red-50 dark:bg-red-950/40 px-3 py-2 text-xs text-red-700 dark:text-red-300">
          {state.message}
        </div> : null}
      <form
        key={`create-form-discard:${discardNonce}`}
        ref={discardGuardRef}
        action={formAction}
        // R4 F-2 (Codex adversarial): 新規チケットの下書きも reload (一覧の一括変更等) で失われ得る
        // draft。汎用 guard convention (lib/full-reload.ts) に登録し、入力で data-dirty を立てる。
        // 作成 submit 自身は except=自 form で confirm を出さない (自分の draft の consume)。
        onChange={(event) => {
          event.currentTarget.dataset.dirty = "true";
        }}
        onSubmit={(event) => {
          if (!confirmDiscardUnsavedDrafts(event.currentTarget)) {
            event.preventDefault();
          }
        }}
        data-unsaved-guard=""
        className="grid gap-3"
      >
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
