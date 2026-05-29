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
