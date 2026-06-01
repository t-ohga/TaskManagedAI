"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { BackendApiError, fetchBackendJson } from "@/lib/api/client";
import { getCurrentProjectId } from "@/lib/api/session";
import { createTicketComment, TicketReadSchema } from "@/lib/api/tickets";

const SLUG_PATTERN = /^[a-z0-9]+(-[a-z0-9]+)*$/;

const TicketCreateFormSchema = z.object({
  slug: z.string().trim().min(1).regex(SLUG_PATTERN, "slug は kebab-case (a-z0-9 + hyphen)"),
  title: z.string().trim().min(1, "タイトルは必須項目です"),
  description: z.string().trim().optional(),
  status: z
    .enum(["open", "in_progress", "blocked", "review", "closed", "cancelled"])
    .default("open"),
  priority: z.enum(["low", "medium", "high", "critical"]).optional()
});

export type CreateTicketState =
  | { kind: "idle" }
  | { kind: "ok"; ticket_id: string }
  | { kind: "error"; message: string };

export async function createTicketAction(
  _prevState: CreateTicketState,
  formData: FormData
): Promise<CreateTicketState> {
  const rawDescription = formData.get("description");
  const rawPriority = formData.get("priority");
  const rawStatus = formData.get("status");
  const parsed = TicketCreateFormSchema.safeParse({
    slug: typeof formData.get("slug") === "string" ? formData.get("slug") : "",
    title: typeof formData.get("title") === "string" ? formData.get("title") : "",
    description:
      typeof rawDescription === "string" && rawDescription.length > 0
        ? rawDescription
        : undefined,
    status:
      typeof rawStatus === "string" && rawStatus.length > 0 ? rawStatus : "open",
    priority:
      typeof rawPriority === "string" && rawPriority.length > 0
        ? rawPriority
        : undefined
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  try {
    // SP-012-11.1 BL-TCU-014: session 経由 project resolve (DEFAULT_PROJECT_ID hardcode 解除)
    const projectId = await getCurrentProjectId();
    const created = await fetchBackendJson(
      `/api/v1/projects/${projectId}/tickets` as `/${string}`,
      TicketReadSchema,
      {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(parsed.data)
      }
    );
    revalidatePath("/tickets");
    return { kind: "ok", ticket_id: created.id };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : "チケット作成に失敗しました。";
    return { kind: "error", message };
  }
}

// ── ADR-00041 N-1: ticket コメント投稿 (CommentForm onSubmit、task_write 相当) ──
// CommentForm が期待する戻り値 { kind: "ok" } | { kind: "error"; message }。
// project は createTicketAction と同じく getCurrentProjectId() で server-owned に解決し、
// form の値は使わない (wrong-project write 防止、B2b gating と同方針。詳細ページは
// isWritable=ticket.project_id===current_project のときだけ CommentForm を描画する)。
const COMMENT_MESSAGE_MAX_LENGTH = 4000;

const TicketCommentFormSchema = z.object({
  ticket_id: z.string().uuid("チケット ID が不正です"),
  body: z
    .string()
    .trim()
    .min(1, "コメントを入力してください")
    .max(COMMENT_MESSAGE_MAX_LENGTH, `コメントは ${COMMENT_MESSAGE_MAX_LENGTH} 文字以内で入力してください`)
});

export type AddTicketCommentResult =
  | { kind: "ok" }
  | { kind: "error"; message: string };

export async function addTicketCommentAction(
  formData: FormData
): Promise<AddTicketCommentResult> {
  const parsed = TicketCommentFormSchema.safeParse({
    ticket_id: typeof formData.get("ticket_id") === "string" ? formData.get("ticket_id") : "",
    body: typeof formData.get("body") === "string" ? formData.get("body") : ""
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  try {
    const projectId = await getCurrentProjectId();
    await createTicketComment(projectId, parsed.data.ticket_id, parsed.data.body);
    revalidatePath(`/tickets/${parsed.data.ticket_id}`);
    return { kind: "ok" };
  } catch (error: unknown) {
    // 422 (secret pattern hit / 文字数超過) は backend が detail を返すが raw 値は含まない。
    // user-facing は固定文言にし、backend の内部 detail をそのまま晒さない。
    if (error instanceof BackendApiError) {
      if (error.status === 422) {
        return {
          kind: "error",
          message: "コメントを保存できませんでした。機密情報が含まれていないか確認してください。"
        };
      }
      if (error.status === 404 || error.status === 409) {
        return {
          kind: "error",
          message: "このチケットにはコメントできません (プロジェクト外 / アーカイブ済みの可能性があります)。"
        };
      }
    }
    return { kind: "error", message: "コメントの投稿に失敗しました。" };
  }
}
