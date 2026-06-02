"use server";

import { revalidatePath } from "next/cache";
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
  due_date: z.string().refine(isValidYmd).nullable().optional()
});

export type UpdateTicketState =
  | { kind: "idle" }
  | { kind: "ok"; ticket_id: string }
  | { kind: "error"; message: string };

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
    due_date: clearableField(formData.get("due_date"))
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  const { ticket_id, ...rest } = parsed.data;
  // Zod optional fields は undefined を残すので、undefined 排除。
  // `null` (explicit clear) は payload に残す = backend に null として送り clear。
  const updatePayload: Record<string, string | null> = {};
  for (const [key, value] of Object.entries(rest)) {
    if (value !== undefined) {
      updatePayload[key] = value;
    }
  }

  if (Object.keys(updatePayload).length === 0) {
    return { kind: "error", message: "更新する項目を入力してください" };
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
    revalidatePath(`/tickets/${ticket_id}`);
    revalidatePath("/tickets");
    return { kind: "ok", ticket_id: updated.id };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : "チケット更新に失敗しました。";
    return { kind: "error", message };
  }
}
