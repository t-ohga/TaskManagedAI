import { z } from "zod";

import { BackendApiError, fetchBackendJson } from "@/lib/api/client";

const DEFAULT_ADMIN_PROJECT_ID = "00000000-0000-4000-8000-000000000004";
const UUID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/iu;
const SHA256_HEX_PATTERN = /^[a-f0-9]{64}$/u;
const SECRETISH_PATTERN =
  /(secret:\/\/|secret_ref|capability[_-]?token|api[_-]?key|authorization|bearer|sk-[A-Za-z0-9_-]{8,})/iu;

function readAdminProjectId(): string {
  const value =
    process.env.TASKMANAGEDAI_ADMIN_PROJECT_ID ??
    process.env.TASKMANAGEDAI_PROJECT_ID ??
    DEFAULT_ADMIN_PROJECT_ID;

  if (!UUID_PATTERN.test(value)) {
    throw new Error("TASKMANAGEDAI_ADMIN_PROJECT_ID must be a UUID.");
  }

  return value.toLowerCase();
}

export function getAdminResearchProjectId(): string {
  return readAdminProjectId();
}

function assertUuid(value: string, label: string): void {
  if (!UUID_PATTERN.test(value)) {
    throw new Error(`${label} must be a UUID.`);
  }
}

function collectionPath(path: string, params: URLSearchParams): `/${string}` {
  const query = params.toString();
  return (query.length > 0 ? `${path}?${query}` : path) as `/${string}`;
}

function paginationParams(limit: number, offset: number): URLSearchParams {
  const params = new URLSearchParams();
  params.set("limit", String(limit));
  params.set("offset", String(offset));
  return params;
}

function sanitizeFrontendUrl(value: string): string {
  if (SECRETISH_PATTERN.test(value) && !value.includes("://")) {
    return "[redacted]";
  }

  try {
    const url = new URL(value);
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return SECRETISH_PATTERN.test(value) ? "[redacted]" : value;
  }
}

const SafeMetadataSchema = z.record(z.string(), z.unknown()).transform((value) => ({
  rls_ready: value.rls_ready === true
}));

export type SafeMetadata = z.infer<typeof SafeMetadataSchema>;

export const ResearchTaskStatusSchema = z.enum([
  "queued",
  "running",
  "completed",
  "failed"
]);

export type ResearchTaskStatus = z.infer<typeof ResearchTaskStatusSchema>;

const ResearchEvidenceAttachmentMetricSchema = z.object({
  metric_kind: z.literal("research_evidence_attachment"),
  research_task_id: z.string().uuid(),
  numerator: z.number().int().nonnegative(),
  denominator: z.number().int().nonnegative(),
  computed_at: z.string(),
  attachment_rate: z.number().min(0).max(1).nullable()
});

export type ResearchEvidenceAttachmentMetric = z.infer<
  typeof ResearchEvidenceAttachmentMetricSchema
>;

export const ResearchTaskSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int().positive(),
  project_id: z.string().uuid(),
  title: z.string(),
  status: ResearchTaskStatusSchema,
  created_by_actor_id: z.string().uuid(),
  created_at: z.string(),
  updated_at: z.string(),
  metadata: SafeMetadataSchema
});

export type ResearchTask = z.infer<typeof ResearchTaskSchema>;

export const ResearchTaskDetailSchema = ResearchTaskSchema.extend({
  evidence_set_hash: z.string().regex(SHA256_HEX_PATTERN),
  research_evidence_attachment: ResearchEvidenceAttachmentMetricSchema
});

export type ResearchTaskDetail = z.infer<typeof ResearchTaskDetailSchema>;

export const ResearchTaskListResponseSchema = z.object({
  items: z.array(ResearchTaskSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative()
});

export type ResearchTaskListResponse = z.infer<typeof ResearchTaskListResponseSchema>;

const ProvNodeSchema = z.object({
  id: z.string(),
  type: z.enum(["prov:Activity", "prov:Entity", "prov:Agent"])
});

const ProvWasGeneratedBySchema = z.object({
  entity: z.string(),
  activity: z.string()
});

const ProvUsedSchema = z.object({
  activity: z.string(),
  entity: z.string()
});

const ProvWasAttributedToSchema = z.object({
  entity: z.string(),
  agent: z.string()
});

const ProvWasInformedBySchema = z.object({
  informed: z.string(),
  informant: z.string()
});

const ProvWasDerivedFromSchema = z.object({
  generated: z.string(),
  used: z.string()
});

export const ProvBundleSchema = z.object({
  activities: z.array(ProvNodeSchema).default([]),
  entities: z.array(ProvNodeSchema).default([]),
  agents: z.array(ProvNodeSchema).default([]),
  wasGeneratedBy: z.array(ProvWasGeneratedBySchema).default([]),
  used: z.array(ProvUsedSchema).default([]),
  wasAttributedTo: z.array(ProvWasAttributedToSchema).default([]),
  wasInformedBy: z.array(ProvWasInformedBySchema).default([]),
  wasDerivedFrom: z.array(ProvWasDerivedFromSchema).default([])
});

export type ProvBundle = z.infer<typeof ProvBundleSchema>;

export const ClaimSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int().positive(),
  project_id: z.string().uuid(),
  research_task_id: z.string().uuid(),
  claim_text: z.string(),
  provenance_json: ProvBundleSchema,
  freshness_score: z.number().min(0).max(1).nullable(),
  metadata: SafeMetadataSchema,
  created_at: z.string(),
  updated_at: z.string()
});

export type Claim = z.infer<typeof ClaimSchema>;

export const EvidenceRelationSchema = z.enum(["supports", "contradicts", "context"]);

export type EvidenceRelation = z.infer<typeof EvidenceRelationSchema>;

export const EvidenceItemSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int().positive(),
  project_id: z.string().uuid(),
  claim_id: z.string().uuid(),
  source_id: z.string().uuid(),
  locator: z.string(),
  relation: EvidenceRelationSchema,
  relevance_score: z.number().min(0).max(1).nullable(),
  metadata: SafeMetadataSchema,
  created_at: z.string(),
  updated_at: z.string()
});

export type EvidenceItem = z.infer<typeof EvidenceItemSchema>;

export const EvidenceSourceSchema = z
  .object({
    id: z.string().uuid(),
    tenant_id: z.number().int().positive(),
    canonical_url: z.string(),
    content_hash: z.string().regex(SHA256_HEX_PATTERN),
    retrieved_at: z.string(),
    published_at: z.string().nullable(),
    created_at: z.string(),
    updated_at: z.string(),
    metadata: SafeMetadataSchema
  })
  .transform((source) => ({
    ...source,
    canonical_url: sanitizeFrontendUrl(source.canonical_url)
  }));

export type EvidenceSource = z.infer<typeof EvidenceSourceSchema>;

export const EvidenceSourceListResponseSchema = z.object({
  items: z.array(EvidenceSourceSchema),
  total: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
  offset: z.number().int().nonnegative()
});

export type EvidenceSourceListResponse = z.infer<typeof EvidenceSourceListResponseSchema>;

export async function listResearchTasks(
  options: { limit?: number; offset?: number } = {}
): Promise<ResearchTaskListResponse> {
  const projectId = readAdminProjectId();
  const limit = options.limit ?? 50;
  const offset = options.offset ?? 0;
  const path = collectionPath(
    `/api/v1/projects/${projectId}/research-tasks`,
    paginationParams(limit, offset)
  );

  return fetchBackendJson(path, ResearchTaskListResponseSchema, {
    headers: { accept: "application/json" }
  });
}

export async function getResearchTask(researchTaskId: string): Promise<ResearchTaskDetail> {
  assertUuid(researchTaskId, "researchTaskId");
  const projectId = readAdminProjectId();

  return fetchBackendJson(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}`,
    ResearchTaskDetailSchema,
    {
      headers: { accept: "application/json" }
    }
  );
}

export async function listClaims(researchTaskId: string): Promise<Claim[]> {
  assertUuid(researchTaskId, "researchTaskId");
  const projectId = readAdminProjectId();

  return fetchBackendJson(
    `/api/v1/projects/${projectId}/research-tasks/${researchTaskId}/claims`,
    z.array(ClaimSchema),
    {
      headers: { accept: "application/json" }
    }
  );
}

export async function getClaim(researchTaskId: string, claimId: string): Promise<Claim> {
  assertUuid(claimId, "claimId");
  const claims = await listClaims(researchTaskId);
  const claim = claims.find((item) => item.id === claimId);
  if (!claim) {
    throw new BackendApiError(404, "Claim not found.");
  }
  return claim;
}

export async function listEvidenceItems(claimId: string): Promise<EvidenceItem[]> {
  assertUuid(claimId, "claimId");
  const projectId = readAdminProjectId();

  return fetchBackendJson(
    `/api/v1/projects/${projectId}/claims/${claimId}/evidence-items`,
    z.array(EvidenceItemSchema),
    {
      headers: { accept: "application/json" }
    }
  );
}

export async function listEvidenceSources(
  options: { limit?: number; offset?: number } = {}
): Promise<EvidenceSourceListResponse> {
  const limit = options.limit ?? 100;
  const offset = options.offset ?? 0;
  const path = collectionPath("/api/v1/evidence-sources", paginationParams(limit, offset));

  return fetchBackendJson(path, EvidenceSourceListResponseSchema, {
    headers: { accept: "application/json" }
  });
}
