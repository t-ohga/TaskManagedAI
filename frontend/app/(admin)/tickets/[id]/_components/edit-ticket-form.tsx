"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import { formatTicketPriority, formatTicketStatus } from "@/lib/i18n/ticket-labels";
import { assigneeSelectOptions, type AssignableActor } from "@/lib/domain/assignee";
import { MarkdownEditor } from "@/components/markdown-editor";

import { updateTicketAction, type UpdateTicketState } from "../actions";

// A-6 (ADR-00046 R1 F-006): TicketRead への as-unknown cast を解消し、編集フォームが使う field のみを
// 明示的に受け取る。TicketDetail (load-ticket) が構造的に満たす。
type EditableTicket = {
  id: string;
  title: string;
  description: string | null;
  due_date: string | null;
  status: string;
  priority: string | null;
  assignee_actor_id: string | null;
};

type EditTicketFormProps = {
  ticket: EditableTicket;
  // A-6: 担当者候補 (tenant 内 human)。取得失敗時は [] + degraded=true (現 assignee のみ option 保持)。
  assignableActors: AssignableActor[];
  assignableActorsDegraded: boolean;
  // Codex App F-C3: 候補が cap 超過で切り詰められたか (一覧に無い human を割り当てられない旨を警告)。
  assignableActorsTruncated: boolean;
};

const INITIAL_STATE: UpdateTicketState = { kind: "idle" };

export function EditTicketForm({
  ticket,
  assignableActors,
  assignableActorsDegraded,
  assignableActorsTruncated
}: EditTicketFormProps) {
  const router = useRouter();
  // R1 F-009: 現 assignee が候補一覧に無くても option に保持 (select が現在値を失わない)。
  const assigneeOptions = assigneeSelectOptions(assignableActors, ticket.assignee_actor_id);

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
      {/* Codex App F-C2: 更新前の assignee。Server Action が「変更時のみ assignee を送信」判定に使う
          (legacy 非 human assignee 付き ticket でも他 field だけ編集でき、unchanged な不正値を再送して
          422 で全編集不能にしない)。 */}
      <input
        type="hidden"
        name="original_assignee_actor_id"
        value={ticket.assignee_actor_id ?? ""}
      />
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

        <div className="grid gap-2 text-sm">
          <span className="font-medium">説明</span>
          <MarkdownEditor
            name="description"
            rows={5}
            defaultValue={ticket.description ?? ""}
            ariaLabel="説明"
            textareaClassName="min-h-32 w-full resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </div>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">期限</span>
          <input
            type="date"
            name="due_date"
            // A-7 (ADR-00045 R11 F-001): ticket.due_date は TicketReadSchema で strict YMD 検証済
            // (YYYY-MM-DD or null)。slice(0,10) の truncation fallback は不要 (malformed は loadTicket
            // で既に fail-closed)。validated 値をそのまま date input の default に使う。
            defaultValue={ticket.due_date ?? ""}
            className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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

        <label className="grid gap-2 text-sm">
          <span className="font-medium">担当者</span>
          <select
            name="assignee_actor_id"
            defaultValue={ticket.assignee_actor_id ?? ""}
            // degraded 警告は aria-describedby で関連付ける (label 内に置くと select の
            // accessible name を汚染するため、name は「担当者」のまま description で補足する)。
            aria-describedby={assignableActorsDegraded ? "assignee-degraded" : undefined}
            className="rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          >
            <option value="">未割当</option>
            {assigneeOptions.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
        {assignableActorsDegraded ? (
          // R1 F-009: 候補取得失敗を degraded で可視化 (silent に未割当へ倒さない)。現 assignee は
          // option に保持済のため保存しても現在値を失わない。label 外に出して select の name を汚さない。
          <p id="assignee-degraded" className="text-xs text-amber-700">
            担当者候補を取得できませんでした。現在の担当者の保持・解除のみ可能です。
          </p>
        ) : assignableActorsTruncated ? (
          // Codex App F-C3: 候補が cap 超過で切り詰められた場合、一覧に無い human を割り当てられない旨を
          // 警告 (tickets 一覧 page と同じ扱い、silent な部分候補にしない)。
          <p id="assignee-degraded" className="text-xs text-amber-700">
            担当者が多いため候補の一部のみ表示しています。一覧に無い担当者は割り当てできません。
          </p>
        ) : null}

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
