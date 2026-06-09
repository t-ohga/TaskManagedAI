import { describe, expect, it } from "vitest";

import {
  EffectiveSourceTrustSchema,
  ProvenanceViewSchema,
  SourceTrustOriginEnum,
  provRelationLabel,
  sourceTrustOriginLabel
} from "@/lib/domain/source-trust";

const UUID = "00000000-0000-4000-8000-000000000001";

describe("source trust enums + helpers", () => {
  it("origin enum is exactly manual/domain/none/invalid", () => {
    expect(new Set(SourceTrustOriginEnum.options)).toEqual(
      new Set(["manual", "domain", "none", "invalid"])
    );
  });

  it("labels origin in Japanese", () => {
    expect(sourceTrustOriginLabel("manual")).toBe("手動設定");
    expect(sourceTrustOriginLabel("domain")).toBe("ドメイン由来");
    expect(sourceTrustOriginLabel("none")).toBe("未設定");
    expect(sourceTrustOriginLabel("invalid")).toBe("判定不能");
  });

  it("labels prov relations", () => {
    expect(provRelationLabel("wasGeneratedBy")).toBe("生成元");
    expect(provRelationLabel("wasDerivedFrom")).toBe("派生元");
  });
});

describe("EffectiveSourceTrustSchema", () => {
  it("parses a manual trust", () => {
    const parsed = EffectiveSourceTrustSchema.parse({
      evidence_source_id: UUID,
      trust_level: "high",
      trust_score: 0.9,
      origin: "manual",
      domain: null,
      match_type: "none"
    });
    expect(parsed.origin).toBe("manual");
    expect(parsed.trust_level).toBe("high");
  });

  it("parses a domain-derived trust (score null)", () => {
    const parsed = EffectiveSourceTrustSchema.parse({
      evidence_source_id: UUID,
      trust_level: "medium",
      trust_score: null,
      origin: "domain",
      domain: "example.com",
      match_type: "exact"
    });
    expect(parsed.origin).toBe("domain");
    expect(parsed.trust_score).toBeNull();
  });

  it("rejects an invalid origin", () => {
    expect(() =>
      EffectiveSourceTrustSchema.parse({
        evidence_source_id: UUID,
        trust_level: null,
        trust_score: null,
        origin: "bogus",
        domain: null,
        match_type: "none"
      })
    ).toThrow();
  });
});

describe("ProvenanceViewSchema", () => {
  it("parses a valid structured view", () => {
    const parsed = ProvenanceViewSchema.parse({
      valid: true,
      reason: null,
      activities: [{ id: "activity:research", type: "prov:Activity" }],
      entities: [{ id: "entity:claim", type: "prov:Entity" }],
      agents: [],
      relations: [{ relation: "wasGeneratedBy", from_id: "entity:claim", to_id: "activity:research" }],
      truncated: false
    });
    expect(parsed.valid).toBe(true);
    expect(parsed.relations[0]?.relation).toBe("wasGeneratedBy");
  });

  it("parses an invalid view", () => {
    const parsed = ProvenanceViewSchema.parse({
      valid: false,
      reason: "invalid_schema",
      activities: [],
      entities: [],
      agents: [],
      relations: [],
      truncated: false
    });
    expect(parsed.valid).toBe(false);
    expect(parsed.reason).toBe("invalid_schema");
  });
});
