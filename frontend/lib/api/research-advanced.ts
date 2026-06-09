/**
 * SP-032 (ADR-00052): research advanced の **server-only** fetch helper (cookies 依存)。
 *
 * Client Component からは import しない (next/headers が client graph に混入するため)。
 * schema / 型 / 表示 helper は `@/lib/domain/research-advanced` (client-safe) を使う。
 * Server Component / Server Action からのみ呼ぶ。conflict groups は project/research-task scoped、
 * domain trust は tenant-scoped (`/api/v1/domain-trust`)。
 */

import { fetchBackendJson, fetchBackendNoContent } from "@/lib/api/client";
import {
  ConflictGroupSchema,
  DomainTrustListResponseSchema,
  DomainTrustSchema,
  ResearchAdvancedSummarySchema,
  type ConflictGroup,
  type DomainTrust,
  type DomainTrustListResponse,
  type ResearchAdvancedSummary,
  type TrustTier
} from "@/lib/domain/research-advanced";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function assertUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) {
    throw new Error(`invalid ${label} format`);
  }
}

/** fail-closed loader 結果。取得失敗 (—) と空集合を区別する。 */
export type LoadResult<T> = { ok: true; data: T } | { ok: false };

// --- research advanced summary (read) ---

export async function getResearchAdvancedSummary(
  projectId: string,
  researchTaskId: string
): Promise<ResearchAdvancedSummary> {
  assertUuid(projectId, "project id");
  assertUuid(researchTaskId, "research task id");
  return fetchBackendJson<ResearchAdvancedSummary>(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/research-advanced` as `/${string}`,
    ResearchAdvancedSummarySchema
  );
}

export async function loadResearchAdvancedSummary(
  projectId: string,
  researchTaskId: string
): Promise<LoadResult<ResearchAdvancedSummary>> {
  try {
    return { ok: true, data: await getResearchAdvancedSummary(projectId, researchTaskId) };
  } catch {
    return { ok: false };
  }
}

// --- conflict groups (mutations) ---

export async function createConflictGroup(
  projectId: string,
  researchTaskId: string,
  body: { title: string }
): Promise<ConflictGroup> {
  assertUuid(projectId, "project id");
  assertUuid(researchTaskId, "research task id");
  return fetchBackendJson<ConflictGroup>(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/conflict-groups` as `/${string}`,
    ConflictGroupSchema,
    { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
  );
}

export async function updateConflictGroup(
  projectId: string,
  researchTaskId: string,
  groupId: string,
  patch: { title?: string; status?: ConflictGroup["status"]; resolution_note?: string | null }
): Promise<ConflictGroup> {
  assertUuid(projectId, "project id");
  assertUuid(researchTaskId, "research task id");
  assertUuid(groupId, "conflict group id");
  return fetchBackendJson<ConflictGroup>(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/conflict-groups/${groupId}` as `/${string}`,
    ConflictGroupSchema,
    { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) }
  );
}

export async function assignClaimToConflictGroup(
  projectId: string,
  researchTaskId: string,
  groupId: string,
  claimId: string
): Promise<void> {
  assertUuid(projectId, "project id");
  assertUuid(researchTaskId, "research task id");
  assertUuid(groupId, "conflict group id");
  assertUuid(claimId, "claim id");
  return fetchBackendNoContent(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/conflict-groups/${groupId}/claims/${claimId}` as `/${string}`,
    { method: "POST" }
  );
}

export async function unassignClaimFromConflictGroup(
  projectId: string,
  researchTaskId: string,
  groupId: string,
  claimId: string
): Promise<void> {
  assertUuid(projectId, "project id");
  assertUuid(researchTaskId, "research task id");
  assertUuid(groupId, "conflict group id");
  assertUuid(claimId, "claim id");
  return fetchBackendNoContent(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/conflict-groups/${groupId}/claims/${claimId}` as `/${string}`,
    { method: "DELETE" }
  );
}

// --- domain trust registry (tenant-scoped) ---

export async function listDomainTrust(): Promise<DomainTrustListResponse> {
  return fetchBackendJson<DomainTrustListResponse>(
    "/api/v1/domain-trust",
    DomainTrustListResponseSchema
  );
}

export async function loadDomainTrustList(): Promise<LoadResult<DomainTrustListResponse>> {
  try {
    return { ok: true, data: await listDomainTrust() };
  } catch {
    return { ok: false };
  }
}

export async function createDomainTrust(body: {
  domain: string;
  trust_tier: TrustTier;
  rationale?: string | null;
}): Promise<DomainTrust> {
  return fetchBackendJson<DomainTrust>("/api/v1/domain-trust", DomainTrustSchema, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(body)
  });
}

export async function updateDomainTrust(
  entryId: string,
  patch: { trust_tier?: TrustTier; rationale?: string | null }
): Promise<DomainTrust> {
  assertUuid(entryId, "domain trust id");
  return fetchBackendJson<DomainTrust>(
    `/api/v1/domain-trust/${entryId}` as `/${string}`,
    DomainTrustSchema,
    { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(patch) }
  );
}

export async function deleteDomainTrust(entryId: string): Promise<void> {
  assertUuid(entryId, "domain trust id");
  return fetchBackendNoContent(`/api/v1/domain-trust/${entryId}` as `/${string}`, {
    method: "DELETE"
  });
}
