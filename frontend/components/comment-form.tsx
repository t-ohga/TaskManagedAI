"use client";

import { useActionState, useEffect, useState } from "react";

import { confirmDiscardUnsavedDrafts } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";

import { MarkdownEditor } from "@/components/markdown-editor";

type CommentResult = { kind: "ok" } | { kind: "error"; message: string };
type CommentState = CommentResult | { kind: "idle" };

type CommentFormProps = {
  ticketId: string;
  onSubmit: (formData: FormData) => Promise<CommentResult>;
};

export function CommentForm({ ticketId, onSubmit }: CommentFormProps) {
  const [body, setBody] = useState("");
  const requestRefresh = useDeferredRouterRefresh();
  const [state, formAction, pending] = useActionState<CommentState, FormData>(
    async (_prev, formData) => {
      const result = await onSubmit(formData);
      if (result.kind === "ok") setBody("");
      return result;
    },
    { kind: "idle" }
  );

  // C-5 workaround: action 側の revalidatePath を撤去したため (isPending 固着 regression、
  // lib/use-deferred-router-refresh.ts 参照)、投稿成功後のコメント一覧反映は transition 外の
  // refresh で行う。
  useEffect(() => {
    if (state.kind === "ok") {
      requestRefresh();
    }
  }, [state, requestRefresh]);

  return (
    <form
      action={formAction}
      // R2 (Codex adversarial HIGH): 投稿成功は reload を伴うため、未保存のチケット編集が
      // あれば mutation **前** に破棄確認する。キャンセル時は preventDefault で action 自体を
      // 実行しない (post-commit 確認では stale form 保存で巻き戻せるため)。
      onSubmit={(event) => {
        // except=自 form: コメント送信は自分の draft を consume する操作なので、自分の
        // 入力では confirm を出さない (他領域の draft があるときだけ確認)。
        if (!confirmDiscardUnsavedDrafts(event.currentTarget)) {
          event.preventDefault();
        }
      }}
      className="grid gap-3"
      // R4 F-2 (Codex adversarial): コメント下書き (最大 4000 字) も reload で失われ得る draft。
      // 汎用 guard convention (lib/full-reload.ts) に登録し、status/タグ等の操作から保護する。
      data-unsaved-guard=""
      data-dirty={body.trim() ? "true" : undefined}
    >
      <input type="hidden" name="ticket_id" value={ticketId} />
      <MarkdownEditor
        name="body"
        value={body}
        onValueChange={setBody}
        rows={3}
        placeholder="コメントを入力 (Markdown 対応)"
        ariaLabel="コメント本文"
      />
      {state.kind === "error" ? <p className="text-xs text-danger">{state.message}</p> : null}
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
