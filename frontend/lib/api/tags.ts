/**
 * ADR-00044 (A-5): ticket タグ/ラベルの **server-only** fetch helper (cookies 依存)。
 *
 * Client Component からは import しない (next/headers が client graph に混入するため、
 * Codex frontend R1 HIGH)。palette / schema / 型は `@/lib/domain/tag` (client-safe) を使う。
 * 本 module は Server Component / Server Action からのみ呼ぶ。
 *
 * - 全 endpoint project-scoped。tenant_id / project_id は server 側で resolve (caller-supplied なし)。
 * - cross-project / nonexistent / soft-deleted target は backend が 404 (BackendApiError) を返す。
 */

import { fetchBackendJson, fetchBackendNoContent } from "@/lib/api/client";
import {
  TagListResponseSchema,
  TagReadSchema,
  type TagColor,
  type TagListResponse,
  type TagRead
} from "@/lib/domain/tag";

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

/**
 * 新規 tag を作成して同一 backend transaction で ticket に付与する (ADR-00044、Codex R5 HIGH)。
 * create + attach を 1 endpoint に集約し、部分成功で孤立 tag が残るのを防ぐ。
 */
export async function createAndAttachTag(
  projectId: string,
  ticketId: string,
  body: { name: string; color: TagColor }
): Promise<void> {
  assertUuid(projectId, "project id");
  assertUuid(ticketId, "ticket id");
  return fetchBackendNoContent(
    `/api/v1/projects/${projectId}/tickets/${ticketId}/tags` as `/${string}`,
    {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ name: body.name, color: body.color })
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
