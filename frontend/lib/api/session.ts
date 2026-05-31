/**
 * Current session resolve helpers (SP-012-11.1 BL-TCU-014).
 *
 * Codex PR #121 R1 F-PR121-002/003 (P1) carry-over fix:
 * `DEFAULT_PROJECT_ID` hardcode を排除し、backend `/api/v1/me/current_project`
 * 経由で current actor's project_id を session 経由 resolve。
 *
 * server-owned-boundary §1:
 * - project_id / tenant_id は server (backend) で session cookie から resolve
 * - frontend は caller-supplied 経路なし、API 経由 fetch のみ
 */

import { z } from "zod";

import { fetchBackendJson } from "@/lib/api/client";

export const CurrentProjectSchema = z.object({
  tenant_id: z.number().int(),
  project_id: z.string().uuid(),
  workspace_id: z.string().uuid(),
  slug: z.string(),
  name: z.string()
});

export type CurrentProject = z.infer<typeof CurrentProjectSchema>;

export const AutonomyLevelSchema = z.enum(["L0", "L1", "L2", "L3"]);
export type AutonomyLevel = z.infer<typeof AutonomyLevelSchema>;

export const ProjectListItemSchema = z.object({
  tenant_id: z.number().int(),
  project_id: z.string().uuid(),
  workspace_id: z.string().uuid(),
  slug: z.string(),
  name: z.string(),
  // M-3 (ADR-00035): backend ProjectListItem は description を必須 nullable で返す
  description: z.string().nullable(),
  status: z.string(),
  policy_profile: z.string(),
  autonomy_level: AutonomyLevelSchema
});

export type ProjectListItem = z.infer<typeof ProjectListItemSchema>;

export const ProjectListResponseSchema = z.object({
  current_project_id: z.string().uuid(),
  projects: z.array(ProjectListItemSchema)
});

export type ProjectListResponse = z.infer<typeof ProjectListResponseSchema>;

// R-3 (ADR-00036): secret_refs read-only インベントリ。backend は公開 metadata のみ返す
// (secret_uri / allowed_consumers / allowed_operations / owner_actor_id / metadata_ /
// runner_injectable は含めない)。raw secret は一切返らない。
export const SecretRefStatusSchema = z.enum([
  "pending",
  "active",
  "deprecated",
  "revoked"
]);
export type SecretRefStatus = z.infer<typeof SecretRefStatusSchema>;

export const SecretRefListItemSchema = z.object({
  id: z.string().uuid(),
  scope: z.string(),
  name: z.string(),
  version: z.string(),
  status: SecretRefStatusSchema,
  rotated: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
  deprecated_at: z.string().nullable(),
  revoked_at: z.string().nullable()
});

export type SecretRefListItem = z.infer<typeof SecretRefListItemSchema>;

export const SecretRefListResponseSchema = z.object({
  secret_refs: z.array(SecretRefListItemSchema)
});

export type SecretRefListResponse = z.infer<typeof SecretRefListResponseSchema>;

/**
 * GET /api/v1/me/current_project — backend が session 経由で resolve した
 * current actor's project を返す。
 *
 * Server Component から call、Client Component には resolved project_id のみ渡す
 * (session cookie 等を Client に露出させない、server-owned-boundary §1)。
 */
export async function getCurrentProject(): Promise<CurrentProject> {
  return fetchBackendJson(
    "/api/v1/me/current_project",
    CurrentProjectSchema
  );
}

/**
 * Convenience helper: current project_id 文字列のみ返す。
 *
 * Server Component で `await getCurrentProjectId()` で使用、Client Component に
 * props として渡す。
 */
export async function getCurrentProjectId(): Promise<string> {
  const project = await getCurrentProject();
  return project.project_id;
}

export async function listCurrentProjects(): Promise<ProjectListResponse> {
  return fetchBackendJson("/api/v1/me/projects", ProjectListResponseSchema);
}

/**
 * R-3 (ADR-00036): tenant 内 secret_refs の read-only インベントリ。
 * backend は公開 metadata のみ返す (raw secret / security topology は非含有)。
 */
export async function listSecretRefs(): Promise<SecretRefListResponse> {
  return fetchBackendJson("/api/v1/me/secret-refs", SecretRefListResponseSchema);
}

/**
 * M-3 (ADR-00035): autonomy_level を更新。
 *
 * Codex adversarial R7/R8 (HIGH): `expectedAutonomyLevel` (編集の基にした現在値) は
 * **必須**。backend が compare-and-swap を行い、別タブ / retry で値が変わっていた場合
 * 409 を返す。stale な baseline からの AI 権限 re-escalation を防ぐ。
 */
export async function updateProjectAutonomyLevel(
  projectId: string,
  autonomyLevel: AutonomyLevel,
  expectedAutonomyLevel: AutonomyLevel
): Promise<ProjectListItem> {
  return fetchBackendJson(
    `/api/v1/me/projects/${projectId}/autonomy` as `/${string}`,
    ProjectListItemSchema,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        autonomy_level: autonomyLevel,
        expected_autonomy_level: expectedAutonomyLevel
      })
    }
  );
}

/**
 * M-3 (ADR-00035): プロジェクト基本情報 (name / description) のみ更新。
 * policy_profile / autonomy_level は本経路で扱わない (server-owned-boundary §1、
 * backend ProjectRepository が caller-supplied policy controls を reject)。
 */
export async function updateProjectProfile(
  projectId: string,
  update: { name?: string; description?: string | null }
): Promise<ProjectListItem> {
  return fetchBackendJson(
    `/api/v1/me/projects/${projectId}/profile` as `/${string}`,
    ProjectListItemSchema,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(update)
    }
  );
}

// =====================================================================
// Q-2〜Q-4 (ADR-00037): データ管理 (破壊的操作、owner-only)。
// すべて owner gate (authenticated + human + 構成済み owner) を backend で enforce。
// tenant_id / project_id は server resolve、caller-supplied 経路なし。
// =====================================================================

export const ProjectStatusSchema = z.enum(["active", "archived"]);
export type ProjectStatus = z.infer<typeof ProjectStatusSchema>;

// Q-2 import の caller 入力 1 件。created_by_actor_id / metadata / tenant_id / project_id は
// server 注入 (server-owned-boundary §1)。slug 一意性は backend が検証 + DB unique で最終防衛。
// ADR-00037 DoD / Codex adversarial R8: payload size 上限を backend (schemas/ticket.py の
// IMPORT_*_MAX_LENGTH) と同値でミラーする。
export const TicketImportItemSchema = z.object({
  slug: z
    .string()
    .min(1)
    .max(100)
    .regex(/^[a-z0-9]+(-[a-z0-9]+)*$/, "slug は小文字英数字とハイフンのみ"),
  title: z.string().min(1).max(200),
  description: z.string().max(10000).nullable().optional(),
  status: z
    .enum(["open", "in_progress", "blocked", "review", "closed", "cancelled"])
    .optional(),
  priority: z.enum(["low", "medium", "high", "critical"]).nullable().optional()
});
export type TicketImportItem = z.infer<typeof TicketImportItemSchema>;

export const BulkSoftDeleteResponseSchema = z.object({
  // no-op (active 0 件) は batch を発行しないため null (ADR-00037 / Codex adversarial #3)。
  deleted_batch_id: z.string().uuid().nullable(),
  soft_deleted_count: z.number().int().nonnegative()
});
export type BulkSoftDeleteResponse = z.infer<typeof BulkSoftDeleteResponseSchema>;

export const RestoreBatchResponseSchema = z.object({
  restored_count: z.number().int().nonnegative()
});
export type RestoreBatchResponse = z.infer<typeof RestoreBatchResponseSchema>;

export const ImportTicketsResponseSchema = z.object({
  dry_run: z.boolean(),
  valid: z.boolean(),
  imported_count: z.number().int().nonnegative(),
  in_payload_duplicate_slugs: z.array(z.string()),
  existing_conflict_slugs: z.array(z.string())
});
export type ImportTicketsResponse = z.infer<typeof ImportTicketsResponseSchema>;

/**
 * Q-4 (ADR-00037): プロジェクトを archive/unarchive。reversible soft toggle (hard delete なし)。
 * `expectedStatus` は If-Match 相当の compare-and-swap baseline (必須)。別操作で status が
 * 変わっていれば backend が 409 を返す (二重 archive / 競合 unarchive 防止)。
 */
export async function archiveProject(
  projectId: string,
  archived: boolean,
  expectedStatus: ProjectStatus
): Promise<ProjectListItem> {
  return fetchBackendJson(
    `/api/v1/me/projects/${projectId}/archive` as `/${string}`,
    ProjectListItemSchema,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ archived, expected_status: expectedStatus })
    }
  );
}

/**
 * Q-3 (ADR-00037): project 内 active 全 ticket を一括 soft-delete (batch 発行)。
 * `expectedActiveCount` は二段階確認の最終 CAS: UI が表示した active 件数を宣言し、backend の
 * current と不一致なら 409 (concurrent 変更で意図しない件数を削除しない)。復元は restore で可能。
 */
export async function bulkSoftDeleteTickets(
  projectId: string,
  expectedActiveCount: number
): Promise<BulkSoftDeleteResponse> {
  return fetchBackendJson(
    `/api/v1/me/projects/${projectId}/tickets/bulk-soft-delete` as `/${string}`,
    BulkSoftDeleteResponseSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ expected_active_count: expectedActiveCount })
    }
  );
}

/**
 * Q-3 (ADR-00037): 特定 deletion batch を復元。tenant + project + batch で限定 (越境復活なし)。
 * 再 restore / 別 project / 空 batch は restored_count=0 (idempotent)。
 */
export async function restoreTicketBatch(
  projectId: string,
  deletedBatchId: string
): Promise<RestoreBatchResponse> {
  return fetchBackendJson(
    `/api/v1/me/projects/${projectId}/tickets/restore` as `/${string}`,
    RestoreBatchResponseSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ deleted_batch_id: deletedBatchId })
    }
  );
}

/**
 * Q-2 (ADR-00037): validated JSON から ticket を一括インポート。
 * `dryRun=true` は validation 結果のみ返し insert しない (preview)。実 import は all-or-nothing:
 * in-payload / 既存 slug 衝突が 1 件でもあれば全体 reject (422)。AI 出力直結はしない。
 */
export async function importTickets(
  projectId: string,
  tickets: TicketImportItem[],
  dryRun: boolean
): Promise<ImportTicketsResponse> {
  return fetchBackendJson(
    `/api/v1/me/projects/${projectId}/tickets/import` as `/${string}`,
    ImportTicketsResponseSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ tickets, dry_run: dryRun })
    }
  );
}
