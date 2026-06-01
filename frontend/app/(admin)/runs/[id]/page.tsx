import { notFound } from "next/navigation";

import { fetchBackendRaw } from "@/lib/api/client";
import { fetchRunArtifacts, type RunArtifact } from "@/lib/api/agent-runs";
import { RunDetailLive, type RunDetailSeed, type TimelineEvent } from "./run-detail-live";
import { RunArtifactsSection } from "./run-artifacts-section";

export const dynamic = "force-dynamic";

type RawRunEvent = {
  id: string;
  event_type: string;
  seq_no: number;
  payload_keys: string[];
  created_at: string | null;
};

async function loadRun(
  id: string
): Promise<{ run: RunDetailSeed; events: TimelineEvent[] } | null> {
  try {
    const res = await fetchBackendRaw(`/api/v1/agent_runs/${id}` as `/${string}`);
    const raw = res as Record<string, unknown>;
    const events = ((raw?.events ?? []) as RawRunEvent[]).map((event) => ({
      id: event.id,
      event_type: event.event_type,
      seq_no: event.seq_no,
      payload_keys: event.payload_keys,
      created_at: event.created_at,
    }));
    return { run: raw as unknown as RunDetailSeed, events };
  } catch {
    return null;
  }
}

// ADR-00042 L-2: artifact metadata inventory を取得 (degraded handling)。
// 取得失敗 (backend 障害 / 一時 5xx) は run 詳細全体を落とさず section 単位で degrade。
async function loadArtifacts(
  id: string
): Promise<{ artifacts: RunArtifact[] | null; degraded: boolean }> {
  try {
    const res = await fetchRunArtifacts(id);
    return { artifacts: res.artifacts, degraded: false };
  } catch {
    return { artifacts: null, degraded: true };
  }
}

type Props = {
  params: Promise<{ id: string }>;
};

export default async function RunDetailPage({ params }: Props) {
  const { id } = await params;
  const data = await loadRun(id);

  if (!data) {
    notFound();
  }

  const { artifacts, degraded } = await loadArtifacts(id);

  // key={run.id} で run 切替時に live state (events/status/seenSeq) を remount リセット (Codex #301 P2-3 関連)。
  return (
    <div className="grid gap-6">
      <RunDetailLive key={data.run.id} run={data.run} initialEvents={data.events} />
      <RunArtifactsSection artifacts={artifacts} degraded={degraded} />
    </div>
  );
}
