"use server";

import { z } from "zod";

import { BackendApiError } from "@/lib/api/client";
import {
  clearEmergencyStop,
  clearGlobalKillSwitch,
  engageEmergencyStop,
  engageGlobalKillSwitch
} from "@/lib/api/emergency-stop";

/**
 * 緊急停止 (emergency-stop latch + budget global kill switch) の operator 操作 (SP-PHASE1 B6)。
 * owner gate は backend で enforce (authenticated + human + configured owner)。403/409 を
 * user-facing message に写像する。AI 出力を直接 mutation に接続しない。
 */
export type EmergencyStopActionState =
  | { kind: "idle" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

const EngageFormSchema = z.object({
  // operator reason は任意。raw secret は backend (service) の broad scanner で fail-closed reject。
  reason: z.string().max(1000).optional()
});

const ClearFormSchema = z.object({
  // generation CAS: 表示していた active latch generation。不一致なら 409 (stale clear reject)。
  expected_generation: z.coerce.number().int().min(1)
});

function ownerOrGenericError(error: unknown, fallback: string): EmergencyStopActionState {
  if (error instanceof BackendApiError && error.status === 401) {
    return {
      kind: "error",
      message: "ログインセッションが必要です。再度ログインしてください。"
    };
  }
  if (error instanceof BackendApiError && error.status === 403) {
    return {
      kind: "error",
      message: "この操作はプロジェクトのオーナーのみが実行できます。"
    };
  }
  if (error instanceof BackendApiError && error.status === 409) {
    return {
      kind: "error",
      message:
        "緊急停止の状態が別の操作で変更されました。最新の状態を再読み込みしてから操作してください。"
    };
  }
  const message = error instanceof Error ? error.message : fallback;
  return { kind: "error", message };
}

export async function engageEmergencyStopAction(
  _prev: EmergencyStopActionState,
  formData: FormData
): Promise<EmergencyStopActionState> {
  const rawReason = formData.get("reason");
  const parsed = EngageFormSchema.safeParse({
    reason: typeof rawReason === "string" && rawReason.trim() !== "" ? rawReason : undefined
  });
  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }
  try {
    const result = await engageEmergencyStop(parsed.data.reason ?? null);
    if (result.already_engaged) {
      return {
        kind: "ok",
        message: `緊急停止は既に有効です (世代 ${result.generation})。`
      };
    }
    return {
      kind: "ok",
      message: `緊急停止を有効にしました (世代 ${result.generation}、${result.blocked_run_count} 件の実行を停止)。解除には世代番号 ${result.generation} を使います。`
    };
  } catch (error: unknown) {
    return ownerOrGenericError(error, "緊急停止の有効化に失敗しました。");
  }
}

export async function clearEmergencyStopAction(
  _prev: EmergencyStopActionState,
  formData: FormData
): Promise<EmergencyStopActionState> {
  const parsed = ClearFormSchema.safeParse({
    expected_generation: formData.get("expected_generation")
  });
  if (!parsed.success) {
    return {
      kind: "error",
      message: "解除に必要な世代番号が不正です。状態を再読み込みしてください。"
    };
  }
  try {
    const result = await clearEmergencyStop(parsed.data.expected_generation);
    const skippedNote =
      result.skipped_run_count > 0
        ? ` (${result.skipped_run_count} 件は対象外のため停止のまま)`
        : "";
    return {
      kind: "ok",
      message: `緊急停止を解除しました (${result.resumed_run_count} 件の実行を再開${skippedNote})。`
    };
  } catch (error: unknown) {
    return ownerOrGenericError(error, "緊急停止の解除に失敗しました。");
  }
}

// budget kill switch は入力 form を持たない (engage/clear のみ)。useActionState の (prevState,
// formData) signature は固定だが両 param とも未使用のため、after-used unused-vars を抑止する。
/* eslint-disable @typescript-eslint/no-unused-vars */
export async function engageGlobalKillSwitchAction(
  _prev: EmergencyStopActionState,
  _formData: FormData
): Promise<EmergencyStopActionState> {
  try {
    await engageGlobalKillSwitch();
    return { kind: "ok", message: "コスト緊急停止 (グローバルキルスイッチ) を有効にしました。" };
  } catch (error: unknown) {
    return ownerOrGenericError(error, "コスト緊急停止の有効化に失敗しました。");
  }
}

export async function clearGlobalKillSwitchAction(
  _prev: EmergencyStopActionState,
  _formData: FormData
): Promise<EmergencyStopActionState> {
  try {
    await clearGlobalKillSwitch();
    return { kind: "ok", message: "コスト緊急停止 (グローバルキルスイッチ) を解除しました。" };
  } catch (error: unknown) {
    return ownerOrGenericError(error, "コスト緊急停止の解除に失敗しました。");
  }
}
/* eslint-enable @typescript-eslint/no-unused-vars */
