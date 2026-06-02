"use server";

import { revalidatePath } from "next/cache";

import { BackendApiError } from "@/lib/api/client";
import { getCurrentProjectId } from "@/lib/api/session";
import {
  attachTag,
  createTag,
  deleteTag,
  detachTag,
  renameTag,
  TagColorEnum
} from "@/lib/api/tags";

/**
 * ADR-00044 (A-5): ticket への tag 付与/除去 + project tag の作成/編集/削除 Server Action。
 *
 * project_id は server-owned (getCurrentProjectId、session current_project)。caller-supplied
 * 経路を持たない。ticket 詳細で isWritable (ticket.project_id === current_project) のときだけ
 * UI が出るため、current_project に対する mutation は ticket の所有 project と一致する。
 */

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type TagActionState =
  | { kind: "idle" }
  | { kind: "ok" }
  | { kind: "error"; message: string };

function mapTagError(error: unknown): string {
  if (error instanceof BackendApiError) {
    switch (error.status) {
      case 409:
        // tag in use (active ticket 付与あり) / 同名重複
        return "このタグは使用中、または同名のタグが既に存在します。";
      case 404:
        return "対象のタグまたはチケットが見つかりません。";
      case 422:
        return "タグ名または色が不正です。";
      case 403:
        return "この操作を行う権限がありません。";
      default:
        return `操作に失敗しました (${error.status})。`;
    }
  }
  return error instanceof Error ? error.message : "操作に失敗しました。";
}

function revalidateTicket(ticketId: string): void {
  revalidatePath(`/tickets/${ticketId}`);
  revalidatePath("/tickets");
}

export async function attachTagAction(
  _prev: TagActionState,
  formData: FormData
): Promise<TagActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const tagId = String(formData.get("tag_id") ?? "");
  if (!UUID_PATTERN.test(ticketId) || !UUID_PATTERN.test(tagId)) {
    return { kind: "error", message: "不正な ID です。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await attachTag(projectId, ticketId, tagId);
    revalidateTicket(ticketId);
    return { kind: "ok" };
  } catch (error) {
    return { kind: "error", message: mapTagError(error) };
  }
}

export async function detachTagAction(
  _prev: TagActionState,
  formData: FormData
): Promise<TagActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const tagId = String(formData.get("tag_id") ?? "");
  if (!UUID_PATTERN.test(ticketId) || !UUID_PATTERN.test(tagId)) {
    return { kind: "error", message: "不正な ID です。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await detachTag(projectId, ticketId, tagId);
    revalidateTicket(ticketId);
    return { kind: "ok" };
  } catch (error) {
    return { kind: "error", message: mapTagError(error) };
  }
}

export async function createTagAndAttachAction(
  _prev: TagActionState,
  formData: FormData
): Promise<TagActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const colorParsed = TagColorEnum.safeParse(formData.get("color"));
  if (!UUID_PATTERN.test(ticketId)) {
    return { kind: "error", message: "不正なチケット ID です。" };
  }
  if (name.length === 0 || name.length > 50) {
    return { kind: "error", message: "タグ名は 1〜50 文字で入力してください。" };
  }
  if (!colorParsed.success) {
    return { kind: "error", message: "色を選択してください。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    const tag = await createTag(projectId, { name, color: colorParsed.data });
    await attachTag(projectId, ticketId, tag.id);
    revalidateTicket(ticketId);
    return { kind: "ok" };
  } catch (error) {
    return { kind: "error", message: mapTagError(error) };
  }
}

export async function renameTagAction(
  _prev: TagActionState,
  formData: FormData
): Promise<TagActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const tagId = String(formData.get("tag_id") ?? "");
  const name = String(formData.get("name") ?? "").trim();
  const colorParsed = TagColorEnum.safeParse(formData.get("color"));
  if (!UUID_PATTERN.test(tagId)) {
    return { kind: "error", message: "不正なタグ ID です。" };
  }
  if (name.length === 0 || name.length > 50) {
    return { kind: "error", message: "タグ名は 1〜50 文字で入力してください。" };
  }
  if (!colorParsed.success) {
    return { kind: "error", message: "色を選択してください。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await renameTag(projectId, tagId, { name, color: colorParsed.data });
    if (UUID_PATTERN.test(ticketId)) revalidateTicket(ticketId);
    else revalidatePath("/tickets");
    return { kind: "ok" };
  } catch (error) {
    return { kind: "error", message: mapTagError(error) };
  }
}

export async function deleteTagAction(
  _prev: TagActionState,
  formData: FormData
): Promise<TagActionState> {
  const ticketId = String(formData.get("ticket_id") ?? "");
  const tagId = String(formData.get("tag_id") ?? "");
  if (!UUID_PATTERN.test(tagId)) {
    return { kind: "error", message: "不正なタグ ID です。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await deleteTag(projectId, tagId);
    if (UUID_PATTERN.test(ticketId)) revalidateTicket(ticketId);
    else revalidatePath("/tickets");
    return { kind: "ok" };
  } catch (error) {
    return { kind: "error", message: mapTagError(error) };
  }
}
