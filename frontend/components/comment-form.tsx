"use client";

import { useActionState, useEffect, useRef, useState } from "react";

import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

import { MarkdownEditor } from "@/components/markdown-editor";

type CommentResult = { kind: "ok" } | { kind: "error"; message: string };
type CommentState = CommentResult | { kind: "idle" };

type CommentFormProps = {
  ticketId: string;
  onSubmit: (formData: FormData) => Promise<CommentResult>;
};

export function CommentForm({ ticketId, onSubmit }: CommentFormProps) {
  const [body, setBody] = useState("");
  // R10 (Codex adversarial HIGH): data-dirty は body state 由来のため、discardDrafts() の
  // DOM 操作だけでは次 render で draft が復活する。discard event で state を正本ごと破棄する。
  const discardGuardRef = useDraftDiscardRef<HTMLFormElement>(() => setBody(""));
  const requestRefresh = useDeferredRouterRefresh();
  // R11: 他領域 draft の破棄は **投稿成功時にのみ** commit する (失敗時は draft 無傷)。
  const commitDiscardRef = useRef<() => void>(noop);
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
      // R11: 成功確定後に捕捉済み他領域 draft を破棄してから reload (失敗時はここに来ない)。
      commitDiscardRef.current();
      commitDiscardRef.current = noop;
      requestRefresh();
    }
  }, [state, requestRefresh]);

  return (
    <form
      ref={discardGuardRef}
      action={formAction}
      // R2 (Codex adversarial HIGH): 投稿成功は reload を伴うため、未保存のチケット編集が
      // あれば mutation **前** に破棄確認する。キャンセル時は preventDefault で action 自体を
      // 実行しない (post-commit 確認では stale form 保存で巻き戻せるため)。
      onSubmit={(event) => {
        // except=自 form: コメント送信は自分の draft を consume する操作なので、自分の
        // 入力では confirm を出さない (他領域の draft があるときだけ確認)。
        // R11: 確認のみ pre-commit、破棄は成功時に commit (失敗時は draft 無傷)。
        const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
        if (!approved) {
          event.preventDefault();
          return;
        }
        commitDiscardRef.current = commit;
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
