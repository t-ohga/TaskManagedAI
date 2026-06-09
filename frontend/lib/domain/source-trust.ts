/**
 * SP-027 (ADR-00053): source trust + provenance view の client-safe pure schema / 型 / 表示 helper。
 * next/headers を import しない (Client Component から安全)。server fetch は `@/lib/api/source-trust`。
 */

import { z } from "zod";

import { TrustTierEnum, DomainTrustMatchTypeEnum } from "@/lib/domain/research-advanced";

export const SourceTrustOriginEnum = z.enum(["manual", "domain", "none", "invalid"]);
export type SourceTrustOrigin = z.infer<typeof SourceTrustOriginEnum>;

export const EffectiveSourceTrustSchema = z.object({
  evidence_source_id: z.string().uuid(),
  trust_level: TrustTierEnum.nullable(),
  trust_score: z.number().nullable(),
  origin: SourceTrustOriginEnum,
  domain: z.string().nullable(),
  match_type: DomainTrustMatchTypeEnum
});
export type EffectiveSourceTrust = z.infer<typeof EffectiveSourceTrustSchema>;

export const SourceTrustListResponseSchema = z.object({
  items: z.array(EffectiveSourceTrustSchema)
});
export type SourceTrustListResponse = z.infer<typeof SourceTrustListResponseSchema>;

export const ProvRelationKindEnum = z.enum([
  "wasGeneratedBy",
  "used",
  "wasAttributedTo",
  "wasInformedBy",
  "wasDerivedFrom"
]);
export type ProvRelationKind = z.infer<typeof ProvRelationKindEnum>;

export const ProvNodeViewSchema = z.object({ id: z.string(), type: z.string() });
export type ProvNodeView = z.infer<typeof ProvNodeViewSchema>;

export const ProvRelationViewSchema = z.object({
  relation: ProvRelationKindEnum,
  from_id: z.string(),
  to_id: z.string()
});
export type ProvRelationView = z.infer<typeof ProvRelationViewSchema>;

export const ProvenanceViewSchema = z.object({
  valid: z.boolean(),
  reason: z.enum(["invalid_schema", "too_large"]).nullable(),
  activities: z.array(ProvNodeViewSchema),
  entities: z.array(ProvNodeViewSchema),
  agents: z.array(ProvNodeViewSchema),
  relations: z.array(ProvRelationViewSchema),
  truncated: z.boolean()
});
export type ProvenanceView = z.infer<typeof ProvenanceViewSchema>;

// --- display helpers ---

export function sourceTrustOriginLabel(origin: SourceTrustOrigin): string {
  switch (origin) {
    case "manual":
      return "手動設定";
    case "domain":
      return "ドメイン由来";
    case "none":
      return "未設定";
    case "invalid":
      return "判定不能";
  }
}

export function provRelationLabel(relation: ProvRelationKind): string {
  switch (relation) {
    case "wasGeneratedBy":
      return "生成元";
    case "used":
      return "使用";
    case "wasAttributedTo":
      return "帰属";
    case "wasInformedBy":
      return "由来";
    case "wasDerivedFrom":
      return "派生元";
  }
}
