/**
 * SP-027 (ADR-00053): source trust + provenance の **server-only** fetch helper (cookies 依存)。
 * Client Component からは import しない。schema / 型 / 表示 helper は `@/lib/domain/source-trust`。
 */

import { fetchBackendJson } from "@/lib/api/client";
import {
  EffectiveSourceTrustSchema,
  ProvenanceViewSchema,
  SourceTrustListResponseSchema,
  type EffectiveSourceTrust,
  type ProvenanceView,
  type SourceTrustListResponse,
  type SourceTrustOrigin
} from "@/lib/domain/source-trust";
import type { TrustTier } from "@/lib/domain/research-advanced";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function assertUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) {
    throw new Error(`invalid ${label} format`);
  }
}

export type LoadResult<T> = { ok: true; data: T } | { ok: false };

export async function loadSourceTrust(
  projectId: string,
  researchTaskId: string
): Promise<LoadResult<SourceTrustListResponse>> {
  try {
    assertUuid(projectId, "project id");
    assertUuid(researchTaskId, "research task id");
    const data = await fetchBackendJson<SourceTrustListResponse>(
      `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/source-trust` as `/${string}`,
      SourceTrustListResponseSchema
    );
    return { ok: true, data };
  } catch {
    return { ok: false };
  }
}

export async function loadClaimProvenance(
  projectId: string,
  researchTaskId: string,
  claimId: string
): Promise<LoadResult<ProvenanceView>> {
  try {
    assertUuid(projectId, "project id");
    assertUuid(researchTaskId, "research task id");
    assertUuid(claimId, "claim id");
    const data = await fetchBackendJson<ProvenanceView>(
      `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/claims/${claimId}/provenance` as `/${string}`,
      ProvenanceViewSchema
    );
    return { ok: true, data };
  } catch {
    return { ok: false };
  }
}

export async function setEvidenceSourceTrust(
  evidenceSourceId: string,
  body: { trust_level: TrustTier | null; trust_score: number | null }
): Promise<EffectiveSourceTrust> {
  assertUuid(evidenceSourceId, "evidence source id");
  return fetchBackendJson<EffectiveSourceTrust>(
    `/api/v1/evidence-sources/${evidenceSourceId}/trust` as `/${string}`,
    EffectiveSourceTrustSchema,
    { method: "PATCH", headers: { "content-type": "application/json" }, body: JSON.stringify(body) }
  );
}

export type { SourceTrustOrigin };
