"use server";

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";
import { getCurrentProjectId } from "@/lib/api/session";
import { TicketReadSchema } from "@/lib/api/tickets";
import { isValidYmd } from "@/lib/domain/due-date";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

// Codex PR #121 R1 F-PR121-001 (P1) fix: description / priority は `""` で
// **explicit clear** (= null へ更新) を表現する必要。`nonEmpty` で `""` を
// undefined 化すると PATCH payload から drop され、backend が old value を保持
// → user の "クリア" 意図が反映されない bug。
//
// 修正: form value `""` を `null` として backend に送る (explicit clear)、
// field key 不存在は `undefined` で send 不要を表現。
const TicketUpdateFormSchema = z.object({
  ticket_id: z.string().regex(UUID_PATTERN, "ticket_id の形式が不正です"),
  title: z.string().trim().min(1).optional(),
  description: z.string().trim().nullable().optional(),
  status: z
    .enum(["open", "in_progress", "blocked", "review", "closed", "cancelled"])
    .optional(),
  priority: z.enum(["low", "medium", "high", "critical"]).nullable().optional(),
  // A-7 (ADR-00045 R11 F-001): due_date は <input type="date"> 由来の YYYY-MM-DD または "" (=null clear)。
  // strict YMD validator で検証し、timestamp / junk / 非実在日を reject (malformed を backend へ
  // 書き戻して deadline を silent 改変しない、strict-YMD all-surface 整合)。null=clear / undefined=変更なし。
  due_date: z.string().refine(isValidYmd).nullable().optional(),
  // A-6 (ADR-00046): 担当者。"" -> null (担当解除) / uuid -> set / 未指定 -> 変更なし。
  // backend repository choke point が human-only + tenant を最終 enforce する (UI は補助)。
  assignee_actor_id: z.string().regex(UUID_PATTERN, "担当者の形式が不正です").nullable().optional()
});

// C-5 fix R2 (Codex adversarial): PATCH response (= DB truth) の編集対象 field snapshot。
// form は成功直後からこの snapshot を defaultValue / remount key の正本に使い、
// 「action 完了 (React 19 auto-reset で stale defaults に戻る) 〜 router.refresh 到着」の間に
// stale DOM を再 submit して DB を巻き戻す window を構造的に閉じる。
export type UpdatedTicketSnapshot = {
  id: string;
  title: string;
  description: string | null;
  due_date: string | null;
  status: string;
  priority: string | null;
  assignee_actor_id: string | null;
  // C-5 R2 (Codex adversarial): snapshot と props の新旧を決める version。refresh / 外部更新で
  // props がこれより新しい updated_at を運んだら、form は snapshot を捨てて props を正本に戻す
  // (古い成功 snapshot が新しい DB truth を恒久遮断して巻き戻す経路の封鎖)。
  updated_at: string;
};

export type UpdateTicketState =
  | { kind: "idle" }
  | { kind: "ok"; ticket_id: string; ticket: UpdatedTicketSnapshot }
  // C-5 R6: error は直近の成功 snapshot を carry する。useActionState の state は次 submit で
  // 置き換わるため、ok→(refresh 未着)→error の遷移で snapshot を失うと stale props へ戻る
  // 再入口になる。client 側で別 state/ref に保持する案は React 19 で action transition を壊す
  // (render 中 setState は commit 不能、render 中 ref は react-hooks/refs 違反) ため、
  // **server action が _prevState から carry する** 純データ設計にする。
  | { kind: "error"; message: string; last_ok_ticket: UpdatedTicketSnapshot | null };

// 直前 state から「直近の成功 snapshot」を引き継ぐ (ok→error→error... の連鎖でも保持)。
function carriedSnapshot(prev: UpdateTicketState): UpdatedTicketSnapshot | null {
  if (prev.kind === "ok") {
    return prev.ticket;
  }
  if (prev.kind === "error") {
    return prev.last_ok_ticket;
  }
  return null;
}

/**
 * formData value を 3 状態に分類:
 * - key 不存在 (typeof !== "string"): `undefined` (PATCH 不要)
 * - empty string `""`: `null` (explicit clear)
 * - non-empty string: そのまま (update)
 *
 * title は `min_length=1` のため `null` でも `""` でも clear 不可 (backend reject)、
 * form では required にして clear 不可とする (UI 側で防御)。
 */
function clearableField(
  value: FormDataEntryValue | null
): string | null | undefined {
  if (typeof value !== "string") return undefined;
  return value === "" ? null : value;
}

function nonEmpty(value: FormDataEntryValue | null): string | undefined {
  return typeof value === "string" && value.length > 0 ? value : undefined;
}

export async function updateTicketAction(
  _prevState: UpdateTicketState,
  formData: FormData
): Promise<UpdateTicketState> {
  // title / status は clear 不可 (title min_length=1、status は enum)、
  // 空文字 → undefined (PATCH 不要)。description / priority は `""` を null として送り
  // explicit clear を backend に伝える。
  const parsed = TicketUpdateFormSchema.safeParse({
    ticket_id: typeof formData.get("ticket_id") === "string" ? formData.get("ticket_id") : "",
    title: nonEmpty(formData.get("title")),
    description: clearableField(formData.get("description")),
    status: nonEmpty(formData.get("status")),
    priority: clearableField(formData.get("priority")),
    due_date: clearableField(formData.get("due_date")),
    // A-6: "" -> null (担当解除) / uuid -> set / 未指定 -> undefined (変更なし)。
    assignee_actor_id: clearableField(formData.get("assignee_actor_id"))
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", "),
      last_ok_ticket: carriedSnapshot(_prevState)
    };
  }

  const { ticket_id, ...rest } = parsed.data;
  // Codex App F-C2: assignee が変更されていなければ payload から外す。legacy 非 human assignee を持つ
  // ticket でも他 field だけ編集できるようにし、unchanged な不正値を再送して repository の human-only
  // 検証で 422 (全編集不能) にしない。null=clear / 別 human への変更時のみ送信する (= 変更時のみ検証)。
  const originalAssignee = clearableField(formData.get("original_assignee_actor_id"));
  if (rest.assignee_actor_id === originalAssignee) {
    rest.assignee_actor_id = undefined;
  }
  // Zod optional fields は undefined を残すので、undefined 排除。
  // `null` (explicit clear) は payload に残す = backend に null として送り clear。
  const updatePayload: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(rest)) {
    if (value !== undefined) {
      updatePayload[key] = value;
    }
  }

  if (Object.keys(updatePayload).length === 0) {
    return {
      kind: "error",
      message: "更新する項目を入力してください",
      last_ok_ticket: carriedSnapshot(_prevState)
    };
  }

  try {
    // SP-012-11.1 BL-TCU-014: Codex PR #121 R1 F-PR121-002 (P1) carry-over fix
    // session 経由 project resolve (DEFAULT_PROJECT_ID hardcode 解除)
    const projectId = await getCurrentProjectId();
    const updated = await fetchBackendJson(
      `/api/v1/projects/${projectId}/tickets/${ticket_id}` as `/${string}`,
      TicketReadSchema,
      {
        method: "PATCH",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(updatePayload)
      }
    );
    // C-5 root cause workaround (Playwright 実測で確定、Next.js 16 / React 19 既知 regression):
    // Server Action 内の revalidatePath() は action transition の isPending を永遠に解除しない
    // (https://github.com/vercel/next.js/discussions/82289 / discussions/88767)。
    // 対象 page は全て force-dynamic + client Router Cache の dynamic staleTime=0 のため、
    // revalidatePath なしでも navigation は常に最新を取得する。現在画面の即時反映は client 側の
    // transition 外 router.refresh() (useDeferredRouterRefresh / useEffect) が担う。
    return {
      kind: "ok",
      ticket_id: updated.id,
      ticket: {
        id: updated.id,
        title: updated.title,
        description: updated.description ?? null,
        due_date: updated.due_date,
        status: updated.status,
        priority: updated.priority,
        assignee_actor_id: updated.assignee_actor_id,
        updated_at: updated.updated_at
      }
    };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : "チケット更新に失敗しました。";
    return { kind: "error", message, last_ok_ticket: carriedSnapshot(_prevState) };
  }
}
