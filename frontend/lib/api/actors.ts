import { fetchBackendJson } from "@/lib/api/client";
import { AssignableActorsSchema, type AssignableActors } from "@/lib/domain/assignee";

// A-6 (ADR-00046): 担当者割当の **server-only** fetch。pure な schema / 表示 / 選択 helper は client-safe な
// `lib/domain/assignee.ts` に分離済 (Codex App F-C1: fetchBackendJson は next/headers を import するため、
// Client Component が import する pure helper と同居させると client bundle が壊れる)。
// 本 module は Server Component からのみ import する。

export async function fetchAssignableActors(): Promise<AssignableActors> {
  return fetchBackendJson("/api/v1/me/assignable-actors", AssignableActorsSchema);
}
