"use client";

import { useRouter } from "next/navigation";
import { useActionState, useEffect } from "react";

import { formatTicketPriority, formatTicketStatus } from "@/lib/i18n/ticket-labels";
import { assigneeSelectOptions, type AssignableActor } from "@/lib/domain/assignee";
import { MarkdownEditor } from "@/components/markdown-editor";

import {
  updateTicketAction,
  type UpdatedTicketSnapshot,
  type UpdateTicketState
} from "../actions";

// A-6 (ADR-00046 R1 F-006): TicketRead への as-unknown cast を解消し、編集フォームが使う field のみを
// 明示的に受け取る。TicketDetail (load-ticket) が構造的に満たす。
export type EditableTicket = {
  id: string;
  title: string;
  description: string | null;
  due_date: string | null;
  status: string;
  priority: string | null;
  assignee_actor_id: string | null;
  // C-5 R2/R3: snapshot と props の新旧判定に使う version。loader (load-ticket) が strict validate
  // して必須 string で渡す (null/欠落は loader が fail-closed で throw、「順序不明」な version を
  // 本 form に持ち込ませない)。
  updated_at: string;
};

// C-5 R4/R5 (Codex adversarial HIGH): updated_at の時系列順序 key (回帰 test 対象)。
// - raw 文字列比較は offset 混在 (`+09:00` vs `Z`) で順序が壊れる (R4)。
// - Date.parse 直比較は ms 精度で、backend (PostgreSQL timestamptz) の microsecond 精度
//   updated_at が同一 ms 内に並ぶと新旧を区別できない (R5)。
// 対策: fractional seconds を自前で全桁抽出し (engine 依存の長 fraction parse を回避)、
// fraction を除いた base を Date.parse (offset 正規化、ECMA 仕様内) して
// `base epoch ms + fraction ms (全桁 float)` を順序 key にする。parse 不能は NaN を返し、
// 比較は false に倒れて props (server 由来) が勝つ = fail-closed。
export function timestampOrderKey(value: string): number {
  const fracMatch = /\.(\d+)(?=(?:[zZ]|[+-]\d{2}:?\d{2})?$)/.exec(value);
  const withoutFrac = fracMatch ? value.replace(fracMatch[0], "") : value;
  const baseMs = Date.parse(withoutFrac);
  if (Number.isNaN(baseMs)) {
    return Number.NaN;
  }
  const fracMs = fracMatch ? Number(`0.${fracMatch[1]}`) * 1000 : 0;
  return baseMs + fracMs;
}

// C-5 R2/R3/R4/R5/R6 (Codex adversarial HIGH): form の表示正本を決める pure helper (回帰 test 対象)。
// - 直近の保存成功 snapshot (PATCH response = DB truth) は、**同一 ticket** かつ props と同等以上に
//   新しい間だけ正本 (別 ticket への snapshot 誤適用 guard)。
// - 外部更新 (同画面 TicketStatusChanger / 別 session) が refresh でより新しい props を運んだら、
//   snapshot を捨てて props に戻る (古い成功 snapshot が新しい DB truth を恒久遮断しない)。
// 比較は timestampOrderKey (offset 正規化 + microsecond 以上の fraction 保持)。どちらかが
// parse 不能なら比較は false → props 勝ち = fail-closed (loader は parseable を保証済)。
// R6: 引数は action state ではなく「保持済み snapshot (null 可)」。useActionState の state は
// 次 submit (error 含む) で置き換わるため、ok→error 遷移で snapshot を失い stale props へ戻る
// 再入口があった。component 側で last-ok snapshot を別 state に保持して渡す。
export function resolveServerTicket(
  snapshot: UpdatedTicketSnapshot | null,
  ticket: EditableTicket
): EditableTicket {
  if (
    snapshot !== null &&
    snapshot.id === ticket.id &&
    timestampOrderKey(snapshot.updated_at) >= timestampOrderKey(ticket.updated_at)
  ) {
    return snapshot;
  }
  return ticket;
}

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

  // C-5 R6 (Codex adversarial HIGH): useActionState の state は次 submit (error 含む) で置き換わる。
  // ok→(refresh 未着)→error の遷移で成功 snapshot を失うと stale props へ戻る再入口になるため、
  // **server action が error state に直近 ok snapshot を carry する** (actions.ts carriedSnapshot)。
  // 【C-5 再 FAIL root cause (Playwright 実測 04:07 で確定)】: client 側で「render 中 setState」
  // 保持を実装すると、React 19 の action transition の結果 render を sync 再 render が破棄し、
  // action state の commit と isPending 解除が永遠に完了しない (Server Action POST は 200/27ms で
  // 返るのに「保存中...」が解除されない)。render 中 ref も react-hooks/refs 違反。よって client は
  // hook を追加せず、action state からの**純 render 派生のみ**で snapshot を得る。
  const candidateSnapshot =
    state.kind === "ok"
      ? state.ticket
      : state.kind === "error"
        ? state.last_ok_ticket
        : null;

  // C-5 fix (Mac 実機検証 + Codex adversarial R1): React 19 は form action 完了後に uncontrolled
  // field を defaultValue へ自動 reset するが、その時点の props は refresh 前の stale ticket のため、
  // 保存直後に状態 select 等が旧値 (例: open) に見え、router.refresh 到着まで stale DOM が操作可能な
  // window が残る (DOM を SoT として読む AI agent が旧値を誤読・再 submit して DB を巻き戻すリスク)。
  // 対策: action の PATCH response (= DB truth) snapshot を成功直後から defaultValue / remount key の
  // 正本にする。action 完了の瞬間に key が変わって form が DB truth で remount されるため stale
  // window は構造的にゼロ。優先順位は resolveServerTicket (pure helper、回帰 test 対象) — snapshot は
  // 同一 ticket かつ props と同等以上に新しい間だけ正本、props が新しくなったら props に戻る。
  const serverTicket = resolveServerTicket(candidateSnapshot, ticket);
  // R1 F-009: 現 assignee が候補一覧に無くても option に保持 (select が現在値を失わない)。
  // 保存後は snapshot の assignee を保持対象にする (props より新しい DB truth)。
  const assigneeOptions = assigneeSelectOptions(assignableActors, serverTicket.assignee_actor_id);
  const serverTicketKey = [
    serverTicket.title,
    serverTicket.description ?? "",
    serverTicket.due_date ?? "",
    serverTicket.status,
    serverTicket.priority ?? "",
    serverTicket.assignee_actor_id ?? ""
    // separator は field 値に現れない NUL escape。隣接 field の値またぎ衝突を防ぐ。
  ].join("\u0000");

  return (
    <form
      key={serverTicketKey}
      action={formAction}
      className="rounded-lg border border-line bg-panel p-5 shadow-sm"
      data-testid="edit-ticket-form"
    >
      <input type="hidden" name="ticket_id" value={serverTicket.id} />
      {/* Codex App F-C2: 更新前の assignee。Server Action が「変更時のみ assignee を送信」判定に使う
          (legacy 非 human assignee 付き ticket でも他 field だけ編集でき、unchanged な不正値を再送して
          422 で全編集不能にしない)。 */}
      <input
        type="hidden"
        name="original_assignee_actor_id"
        value={serverTicket.assignee_actor_id ?? ""}
      />
      <fieldset className="grid gap-4" disabled={isPending}>
        <legend className="text-base font-semibold">チケット編集</legend>

        <label className="grid gap-2 text-sm">
          <span className="font-medium">タイトル</span>
          <input
            name="title"
            defaultValue={serverTicket.title}
            className="rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <div className="grid gap-2 text-sm">
          <span className="font-medium">説明</span>
          <MarkdownEditor
            name="description"
            rows={5}
            defaultValue={serverTicket.description ?? ""}
            ariaLabel="説明"
            textareaClassName="min-h-32 w-full resize-y rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
            defaultValue={serverTicket.due_date ?? ""}
            className="rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
          />
        </label>

        <div className="grid gap-4 sm:grid-cols-2">
          <label className="grid gap-2 text-sm">
            <span className="font-medium">状態</span>
            <select
              name="status"
              defaultValue={serverTicket.status}
              className="rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
              defaultValue={serverTicket.priority ?? ""}
              className="rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
            defaultValue={serverTicket.assignee_actor_id ?? ""}
            // degraded 警告は aria-describedby で関連付ける (label 内に置くと select の
            // accessible name を汚染するため、name は「担当者」のまま description で補足する)。
            aria-describedby={assignableActorsDegraded ? "assignee-degraded" : undefined}
            className="rounded-md border border-line bg-panel px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
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
          <p id="assignee-degraded" className="text-xs text-amber-700 dark:text-amber-300">
            担当者候補を取得できませんでした。現在の担当者の保持・解除のみ可能です。
          </p>
        ) : assignableActorsTruncated ? (
          // Codex App F-C3: 候補が cap 超過で切り詰められた場合、一覧に無い human を割り当てられない旨を
          // 警告 (tickets 一覧 page と同じ扱い、silent な部分候補にしない)。
          <p id="assignee-degraded" className="text-xs text-amber-700 dark:text-amber-300">
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
            className="rounded-md bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-700 dark:text-rose-300"
          >
            {state.message}
          </p>
        ) : null}
        {state.kind === "ok" ? (
          <p
            role="status"
            className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300"
          >
            チケットを更新しました (id: {state.ticket_id})
          </p>
        ) : null}
      </fieldset>
    </form>
  );
}
