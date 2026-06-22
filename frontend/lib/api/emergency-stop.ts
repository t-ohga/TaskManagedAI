/**
 * Emergency-stop + budget global kill-switch API client (SP-PHASE1 B6、ADR-00048 §C/§D/§A-8)。
 *
 * human-only な「全 AI 即停止」安全弁の operator surface。すべて server fetch (cookie session 経由)
 * で backend owner gate を通る。caller-supplied 経路なし (tenant / actor は server resolve)。
 *
 * - emergency-stop latch (human 即時全停止): status / engage / clear。
 * - budget global kill switch (コスト緊急停止、A-8 で latch と OR): status / engage / clear。
 *
 * raw secret / token / pid は backend response に含まれない (latch / budget metadata のみ)。
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

// --- emergency-stop latch (human 即時全停止) ---

export const EmergencyStopStatusSchema = z.object({
  engaged: z.boolean(),
  generation: z.number().int().nullable(),
  engaged_at: z.string().nullable()
});
export type EmergencyStopStatus = z.infer<typeof EmergencyStopStatusSchema>;

export const EmergencyStopEngageSchema = z.object({
  engaged: z.boolean(),
  generation: z.number().int(),
  engaged_at: z.string(),
  blocked_run_count: z.number().int().nonnegative(),
  already_engaged: z.boolean()
});
export type EmergencyStopEngageResult = z.infer<typeof EmergencyStopEngageSchema>;

export const EmergencyStopClearSchema = z.object({
  cleared: z.boolean(),
  generation: z.number().int(),
  cleared_at: z.string(),
  resumed_run_count: z.number().int().nonnegative(),
  skipped_run_count: z.number().int().nonnegative()
});
export type EmergencyStopClearResult = z.infer<typeof EmergencyStopClearSchema>;

export async function getEmergencyStopStatus(): Promise<EmergencyStopStatus> {
  return fetchBackendJson(
    "/api/v1/superintendent/emergency-stop",
    EmergencyStopStatusSchema
  );
}

export async function engageEmergencyStop(
  reason: string | null
): Promise<EmergencyStopEngageResult> {
  return fetchBackendJson(
    "/api/v1/superintendent/emergency-stop",
    EmergencyStopEngageSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ reason })
    }
  );
}

export async function clearEmergencyStop(
  expectedGeneration: number
): Promise<EmergencyStopClearResult> {
  return fetchBackendJson(
    "/api/v1/superintendent/emergency-stop/clear",
    EmergencyStopClearSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ expected_generation: expectedGeneration })
    }
  );
}

// --- budget global kill switch (コスト緊急停止、A-8 で latch と OR) ---

export const GlobalKillSwitchStatusSchema = z.object({
  engaged: z.boolean(),
  budget_id: z.string().nullable(),
  // B6 P2-4 CAS token: clear が割込み engage を上書きしないための updated_at (budget 不在なら null)。
  updated_at: z.string().nullable()
});
export type GlobalKillSwitchStatus = z.infer<typeof GlobalKillSwitchStatusSchema>;

export const GlobalKillSwitchMutationSchema = z.object({
  engaged: z.boolean(),
  budget_id: z.string(),
  // B6 P2-4: mutation 後の最新 CAS token。
  updated_at: z.string()
});
export type GlobalKillSwitchMutationResult = z.infer<
  typeof GlobalKillSwitchMutationSchema
>;

export async function getGlobalKillSwitchStatus(): Promise<GlobalKillSwitchStatus> {
  return fetchBackendJson(
    "/api/v1/budget/global-kill-switch",
    GlobalKillSwitchStatusSchema
  );
}

export async function engageGlobalKillSwitch(): Promise<GlobalKillSwitchMutationResult> {
  return fetchBackendJson(
    "/api/v1/budget/global-kill-switch",
    GlobalKillSwitchMutationSchema,
    { method: "POST", headers: { "content-type": "application/json" } }
  );
}

export async function clearGlobalKillSwitch(
  expectedUpdatedAt: string
): Promise<GlobalKillSwitchMutationResult> {
  return fetchBackendJson(
    "/api/v1/budget/global-kill-switch/clear",
    GlobalKillSwitchMutationSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      // B6 P2-4 CAS: status GET が返した updated_at を返す。別 engage が割り込んでいれば 409。
      body: JSON.stringify({ expected_updated_at: expectedUpdatedAt })
    }
  );
}
