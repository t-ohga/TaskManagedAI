"use server";

import { revalidatePath } from "next/cache";

import { BackendApiError } from "@/lib/api/client";
import { getCurrentProjectId } from "@/lib/api/session";
import {
  assignClaimToConflictGroup,
  createConflictGroup,
  unassignClaimFromConflictGroup,
  updateConflictGroup
} from "@/lib/api/research-advanced";
import { ConflictGroupStatusEnum } from "@/lib/domain/research-advanced";

/**
 * SP-032 (ADR-00052): research detail の conflict group 管理 Server Action (owner-gated)。
 *
 * project_id は server-owned (getCurrentProjectId、session current_project)。research_task_id /
 * claim_id / group_id は formData だが、backend が project/research_task 境界を 404/FK で enforce。
 * owner gate は backend (require_project_owner)。
 */

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type ConflictActionState =
  | { kind: "idle" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

function mapError(error: unknown): string {
  if (error instanceof BackendApiError) {
    switch (error.status) {
      case 400:
        return "入力値が不正です (解決済みにするには解決メモが必要です)。";
      case 404:
        return "対象のリサーチ・主張・グループが見つかりません。";
      case 422:
        return "入力値が不正です。";
      case 403:
        return "この操作を行う権限がありません (オーナーのみ)。";
      default:
        return `操作に失敗しました (${error.status})。`;
    }
  }
  return error instanceof Error ? error.message : "操作に失敗しました。";
}

function revalidate(researchTaskId: string): void {
  revalidatePath(`/research/${researchTaskId}`);
}

export async function createConflictGroupAction(
  _prev: ConflictActionState,
  formData: FormData
): Promise<ConflictActionState> {
  const researchTaskId = String(formData.get("research_task_id") ?? "");
  const title = String(formData.get("title") ?? "").trim();
  if (!UUID_PATTERN.test(researchTaskId)) {
    return { kind: "error", message: "不正なリサーチ ID です。" };
  }
  if (title.length === 0 || title.length > 200) {
    return { kind: "error", message: "グループ名を 1〜200 文字で入力してください。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await createConflictGroup(projectId, researchTaskId, { title });
    revalidate(researchTaskId);
    return { kind: "ok", message: "矛盾グループを作成しました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}

export async function setConflictGroupStatusAction(
  _prev: ConflictActionState,
  formData: FormData
): Promise<ConflictActionState> {
  const researchTaskId = String(formData.get("research_task_id") ?? "");
  const groupId = String(formData.get("group_id") ?? "");
  const statusParsed = ConflictGroupStatusEnum.safeParse(formData.get("status"));
  const noteRaw = String(formData.get("resolution_note") ?? "").trim();
  if (!UUID_PATTERN.test(researchTaskId) || !UUID_PATTERN.test(groupId)) {
    return { kind: "error", message: "不正な ID です。" };
  }
  if (!statusParsed.success) {
    return { kind: "error", message: "状態を選択してください。" };
  }
  if (statusParsed.data === "resolved" && noteRaw.length === 0) {
    return { kind: "error", message: "「解決済み」にするには解決メモが必要です。" };
  }
  if (noteRaw.length > 2000) {
    return { kind: "error", message: "解決メモは 2000 文字以内で入力してください。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await updateConflictGroup(projectId, researchTaskId, groupId, {
      status: statusParsed.data,
      resolution_note: noteRaw.length > 0 ? noteRaw : null
    });
    revalidate(researchTaskId);
    return { kind: "ok", message: "矛盾グループの状態を更新しました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}

export async function assignClaimAction(
  _prev: ConflictActionState,
  formData: FormData
): Promise<ConflictActionState> {
  const researchTaskId = String(formData.get("research_task_id") ?? "");
  const groupId = String(formData.get("group_id") ?? "");
  const claimId = String(formData.get("claim_id") ?? "");
  if (![researchTaskId, groupId, claimId].every((value) => UUID_PATTERN.test(value))) {
    return { kind: "error", message: "不正な ID です。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await assignClaimToConflictGroup(projectId, researchTaskId, groupId, claimId);
    revalidate(researchTaskId);
    return { kind: "ok", message: "主張を矛盾グループに割り当てました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}

export async function unassignClaimAction(
  _prev: ConflictActionState,
  formData: FormData
): Promise<ConflictActionState> {
  const researchTaskId = String(formData.get("research_task_id") ?? "");
  const groupId = String(formData.get("group_id") ?? "");
  const claimId = String(formData.get("claim_id") ?? "");
  if (![researchTaskId, groupId, claimId].every((value) => UUID_PATTERN.test(value))) {
    return { kind: "error", message: "不正な ID です。" };
  }
  try {
    const projectId = await getCurrentProjectId();
    await unassignClaimFromConflictGroup(projectId, researchTaskId, groupId, claimId);
    revalidate(researchTaskId);
    return { kind: "ok", message: "主張をグループから外しました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}
