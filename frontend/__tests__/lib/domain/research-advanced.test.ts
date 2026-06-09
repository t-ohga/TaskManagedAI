import { describe, expect, it } from "vitest";

import {
  ConflictGroupStatusEnum,
  DomainTrustMatchTypeEnum,
  ResearchAdvancedSummarySchema,
  TrustTierEnum,
  conflictStatusLabel,
  conflictStatusTone,
  formatFreshness,
  matchTypeLabel,
  trustTierLabel,
  trustTierTone
} from "@/lib/domain/research-advanced";

const UUID = "00000000-0000-4000-8000-000000000001";

describe("research-advanced enums", () => {
  it("conflict status enum is exactly open/resolved/dismissed", () => {
    expect(new Set(ConflictGroupStatusEnum.options)).toEqual(
      new Set(["open", "resolved", "dismissed"])
    );
  });

  it("trust tier enum is exactly low/medium/high", () => {
    expect(new Set(TrustTierEnum.options)).toEqual(new Set(["low", "medium", "high"]));
  });

  it("match type enum is exactly exact/none/invalid", () => {
    expect(new Set(DomainTrustMatchTypeEnum.options)).toEqual(
      new Set(["exact", "none", "invalid"])
    );
  });
});

describe("display helpers", () => {
  it("labels conflict status in Japanese", () => {
    expect(conflictStatusLabel("open")).toBe("未解決");
    expect(conflictStatusLabel("resolved")).toBe("解決済み");
    expect(conflictStatusLabel("dismissed")).toBe("却下");
  });

  it("maps conflict status tone", () => {
    expect(conflictStatusTone("open")).toBe("warning");
    expect(conflictStatusTone("resolved")).toBe("success");
    expect(conflictStatusTone("dismissed")).toBe("muted");
  });

  it("labels and tones trust tier", () => {
    expect(trustTierLabel("high")).toBe("高");
    expect(trustTierTone("low")).toBe("danger");
    expect(trustTierTone("medium")).toBe("warning");
    expect(trustTierTone("high")).toBe("success");
  });

  it("labels match type", () => {
    expect(matchTypeLabel("exact")).toBe("登録済み");
    expect(matchTypeLabel("none")).toBe("未登録");
    expect(matchTypeLabel("invalid")).toBe("ドメイン判定不能");
  });

  it("formats freshness as percentage and dash for null", () => {
    expect(formatFreshness(null)).toBe("—");
    expect(formatFreshness(1)).toBe("100%");
    expect(formatFreshness(0.5)).toBe("50%");
    expect(formatFreshness(0)).toBe("0%");
    // clamps out-of-range
    expect(formatFreshness(1.4)).toBe("100%");
    expect(formatFreshness(-0.2)).toBe("0%");
  });
});

describe("ResearchAdvancedSummarySchema", () => {
  it("parses a valid summary", () => {
    const parsed = ResearchAdvancedSummarySchema.parse({
      research_task_id: UUID,
      conflict_groups: [
        {
          id: UUID,
          tenant_id: 1,
          project_id: UUID,
          research_task_id: UUID,
          title: "矛盾グループ",
          status: "open",
          resolution_note: null,
          created_by_actor_id: UUID,
          created_at: "2026-06-09T00:00:00Z",
          updated_at: "2026-06-09T00:00:00Z"
        }
      ],
      conflict_candidates: [
        {
          claim_id: UUID,
          contradicting_count: 1,
          supporting_count: 2,
          context_count: 0,
          conflict_group_id: null
        }
      ],
      relation_coverage: 0.5,
      claim_freshness: [
        { claim_id: UUID, computed_freshness: 0.9, newest_evidence_at: "2026-01-01T00:00:00Z" }
      ],
      evidence_domain_trust: [
        { evidence_source_id: UUID, domain: "example.com", trust_tier: "high", match_type: "exact" }
      ]
    });
    expect(parsed.conflict_candidates[0]?.contradicting_count).toBe(1);
    expect(parsed.evidence_domain_trust[0]?.match_type).toBe("exact");
  });

  it("rejects an invalid trust tier", () => {
    expect(() =>
      ResearchAdvancedSummarySchema.parse({
        research_task_id: UUID,
        conflict_groups: [],
        conflict_candidates: [],
        relation_coverage: 0,
        claim_freshness: [],
        evidence_domain_trust: [
          { evidence_source_id: UUID, domain: "x.com", trust_tier: "ultra", match_type: "exact" }
        ]
      })
    ).toThrow();
  });
});
