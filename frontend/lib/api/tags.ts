/**
 * ADR-00044 (A-5): ticket タグ/ラベルの API client (Zod schema + fetch helper)。
 *
 * backend は全 endpoint project-scoped (`/api/v1/projects/{project_id}/...`)。
 * server-owned-boundary §1: tenant_id / project_id は Server Component / Server Action で
 * session から resolve し caller-supplied 経路を持たない。response は Zod で strict validate。
 *
 * - color palette は backend `TAG_COLORS` (migration DB CHECK / ORM / Pydantic) と 5+ source 整合。
 *   drift した場合 Zod parse が落ちるため UI 側で不正 color を握りつぶさない。
 * - cross-project / nonexistent tag_id を指す read/mutate は backend が 404 (BackendApiError) を返す
 *   (path/target mismatch を fail-closed)。呼び出し側は status で分岐する。
 */

import { z } from "zod";

import { fetchBackendJson, fetchBackendNoContent } from "@/lib/api/client";

// backend/app/db/models/tag.py TAG_COLORS と完全一致 (順序込み、test_ticket_tags.py で drift 検証)。
export const TagColorEnum = z.enum([
  "slate",
  "red",
  "orange",
  "amber",
  "green",
  "teal",
  "blue",
  "purple",
  "pink"
]);

export type TagColor = z.infer<typeof TagColorEnum>;

export const TAG_COLORS: readonly TagColor[] = TagColorEnum.options;

export const TagReadSchema = z.object({
  id: z.string().uuid(),
  name: z.string(),
  color: TagColorEnum
});

export type TagRead = z.infer<typeof TagReadSchema>;

export const TagListResponseSchema = z.object({
  items: z.array(TagReadSchema)
});

export type TagListResponse = z.infer<typeof TagListResponseSchema>;

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function assertUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) {
    throw new Error(`invalid ${label} format`);
  }
}

export async function listTags(projectId: string): Promise<TagListResponse> {
  assertUuid(projectId, "project id");
  return fetchBackendJson<TagListResponse>(
    `/api/v1/projects/${projectId}/tags` as `/${string}`,
    TagListResponseSchema
  );
}

export async function createTag(
  projectId: string,
  body: { name: string; color: TagColor }
): Promise<TagRead> {
  assertUuid(projectId, "project id");
  return fetchBackendJson<TagRead>(
    `/api/v1/projects/${projectId}/tags` as `/${string}`,
    TagReadSchema,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body)
    }
  );
}

export async function renameTag(
  projectId: string,
  tagId: string,
  patch: { name?: string; color?: TagColor }
): Promise<TagRead> {
  assertUuid(projectId, "project id");
  assertUuid(tagId, "tag id");
  return fetchBackendJson<TagRead>(
    `/api/v1/projects/${projectId}/tags/${tagId}` as `/${string}`,
    TagReadSchema,
    {
      method: "PATCH",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(patch)
    }
  );
}

export async function deleteTag(projectId: string, tagId: string): Promise<void> {
  assertUuid(projectId, "project id");
  assertUuid(tagId, "tag id");
  return fetchBackendNoContent(
    `/api/v1/projects/${projectId}/tags/${tagId}` as `/${string}`,
    { method: "DELETE" }
  );
}

export async function attachTag(
  projectId: string,
  ticketId: string,
  tagId: string
): Promise<void> {
  assertUuid(projectId, "project id");
  assertUuid(ticketId, "ticket id");
  assertUuid(tagId, "tag id");
  return fetchBackendNoContent(
    `/api/v1/projects/${projectId}/tickets/${ticketId}/tags` as `/${string}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ tag_id: tagId })
    }
  );
}

export async function detachTag(
  projectId: string,
  ticketId: string,
  tagId: string
): Promise<void> {
  assertUuid(projectId, "project id");
  assertUuid(ticketId, "ticket id");
  assertUuid(tagId, "tag id");
  return fetchBackendNoContent(
    `/api/v1/projects/${projectId}/tickets/${ticketId}/tags/${tagId}` as `/${string}`,
    { method: "DELETE" }
  );
}
