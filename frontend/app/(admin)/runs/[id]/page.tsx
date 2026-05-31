import { notFound } from "next/navigation";

import { fetchBackendRaw } from "@/lib/api/client";
import { RunDetailLive, type RunDetailSeed, type TimelineEvent } from "./run-detail-live";

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

type Props = {
  params: Promise<{ id: string }>;
};

export default async function RunDetailPage({ params }: Props) {
  const { id } = await params;
  const data = await loadRun(id);

  if (!data) {
    notFound();
  }

  // key={run.id} で run 切替時に live state (events/status/seenSeq) を remount リセット (Codex #301 P2-3 関連)。
  return <RunDetailLive key={data.run.id} run={data.run} initialEvents={data.events} />;
}
