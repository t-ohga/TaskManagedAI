import type { EvidenceRelation, ResearchTaskStatus } from "@/lib/api/research";

export const RESEARCH_STATUS_LABELS: Record<ResearchTaskStatus, string> = {
  queued: "待機中",
  running: "実行中",
  completed: "完了",
  failed: "失敗"
};

export const EVIDENCE_RELATION_LABELS: Record<EvidenceRelation, string> = {
  supports: "支持",
  contradicts: "反証",
  context: "文脈"
};

export function formatResearchStatus(status: ResearchTaskStatus): string {
  return `${RESEARCH_STATUS_LABELS[status]} (${status})`;
}

export function formatEvidenceRelation(relation: EvidenceRelation): string {
  return `${EVIDENCE_RELATION_LABELS[relation]} (${relation})`;
}
