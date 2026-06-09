/**
 * SP-032 (ADR-00052): research advanced の client-safe pure schema / 型 / 表示 helper。
 *
 * conflict groups + conflict candidates + per-claim computed_freshness + domain trust registry。
 * 本 module は next/headers を import しない (Client Component から安全に import 可能)。
 * server fetch は `@/lib/api/research-advanced` を使う。
 */

import { z } from "zod";

export const ConflictGroupStatusEnum = z.enum(["open", "resolved", "dismissed"]);
export type ConflictGroupStatus = z.infer<typeof ConflictGroupStatusEnum>;

export const TrustTierEnum = z.enum(["low", "medium", "high"]);
export type TrustTier = z.infer<typeof TrustTierEnum>;

export const DomainTrustMatchTypeEnum = z.enum(["exact", "none", "invalid"]);
export type DomainTrustMatchType = z.infer<typeof DomainTrustMatchTypeEnum>;

export const ConflictGroupSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int(),
  project_id: z.string().uuid(),
  research_task_id: z.string().uuid(),
  title: z.string(),
  status: ConflictGroupStatusEnum,
  resolution_note: z.string().nullable(),
  created_by_actor_id: z.string().uuid(),
  created_at: z.string(),
  updated_at: z.string()
});
export type ConflictGroup = z.infer<typeof ConflictGroupSchema>;

export const ConflictCandidateSchema = z.object({
  claim_id: z.string().uuid(),
  contradicting_count: z.number().int(),
  supporting_count: z.number().int(),
  context_count: z.number().int(),
  conflict_group_id: z.string().uuid().nullable()
});
export type ConflictCandidate = z.infer<typeof ConflictCandidateSchema>;

export const ClaimFreshnessSchema = z.object({
  claim_id: z.string().uuid(),
  computed_freshness: z.number().nullable(),
  newest_evidence_at: z.string().nullable()
});
export type ClaimFreshness = z.infer<typeof ClaimFreshnessSchema>;

export const EvidenceDomainTrustSchema = z.object({
  evidence_source_id: z.string().uuid(),
  domain: z.string().nullable(),
  trust_tier: TrustTierEnum.nullable(),
  match_type: DomainTrustMatchTypeEnum
});
export type EvidenceDomainTrust = z.infer<typeof EvidenceDomainTrustSchema>;

export const ResearchAdvancedSummarySchema = z.object({
  research_task_id: z.string().uuid(),
  conflict_groups: z.array(ConflictGroupSchema),
  conflict_candidates: z.array(ConflictCandidateSchema),
  relation_coverage: z.number(),
  claim_freshness: z.array(ClaimFreshnessSchema),
  evidence_domain_trust: z.array(EvidenceDomainTrustSchema)
});
export type ResearchAdvancedSummary = z.infer<typeof ResearchAdvancedSummarySchema>;

export const DomainTrustSchema = z.object({
  id: z.string().uuid(),
  tenant_id: z.number().int(),
  domain: z.string(),
  trust_tier: TrustTierEnum,
  rationale: z.string().nullable(),
  created_by_actor_id: z.string().uuid(),
  created_at: z.string(),
  updated_at: z.string()
});
export type DomainTrust = z.infer<typeof DomainTrustSchema>;

export const DomainTrustListResponseSchema = z.object({
  items: z.array(DomainTrustSchema)
});
export type DomainTrustListResponse = z.infer<typeof DomainTrustListResponseSchema>;

// --- display helpers (pure) ---

export function conflictStatusLabel(status: ConflictGroupStatus): string {
  switch (status) {
    case "open":
      return "未解決";
    case "resolved":
      return "解決済み";
    case "dismissed":
      return "却下";
  }
}

export function conflictStatusTone(status: ConflictGroupStatus): "warning" | "success" | "muted" {
  switch (status) {
    case "open":
      return "warning";
    case "resolved":
      return "success";
    case "dismissed":
      return "muted";
  }
}

export function trustTierLabel(tier: TrustTier): string {
  switch (tier) {
    case "low":
      return "低";
    case "medium":
      return "中";
    case "high":
      return "高";
  }
}

export function trustTierTone(tier: TrustTier): "danger" | "warning" | "success" {
  switch (tier) {
    case "low":
      return "danger";
    case "medium":
      return "warning";
    case "high":
      return "success";
  }
}

export function matchTypeLabel(match: DomainTrustMatchType): string {
  switch (match) {
    case "exact":
      return "登録済み";
    case "none":
      return "未登録";
    case "invalid":
      return "ドメイン判定不能";
  }
}

/** computed_freshness (0-1) を percentage 表示。null は "—"。 */
export function formatFreshness(value: number | null): string {
  if (value === null) {
    return "—";
  }
  const clamped = Math.max(0, Math.min(1, value));
  return `${Math.round(clamped * 100)}%`;
}
