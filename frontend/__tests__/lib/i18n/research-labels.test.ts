import { describe, expect, it } from "vitest";

import {
  EVIDENCE_RELATION_LABELS,
  formatEvidenceRelation,
  formatResearchStatus,
  RESEARCH_STATUS_LABELS
} from "@/lib/i18n/research-labels";

describe("research i18n labels", () => {
  it("keeps every research status value visible with a Japanese label", () => {
    expect(RESEARCH_STATUS_LABELS).toEqual({
      queued: "待機中",
      running: "実行中",
      completed: "完了",
      failed: "失敗"
    });
    expect(formatResearchStatus("completed")).toBe("完了 (completed)");
  });

  it("keeps every evidence relation value visible with a Japanese label", () => {
    expect(EVIDENCE_RELATION_LABELS).toEqual({
      supports: "支持",
      contradicts: "反証",
      context: "文脈"
    });
    expect(formatEvidenceRelation("supports")).toBe("支持 (supports)");
  });
});
