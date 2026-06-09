"use server";

import { revalidatePath } from "next/cache";

import { BackendApiError } from "@/lib/api/client";
import { getCurrentProjectId } from "@/lib/api/session";
import { loadClaimProvenance, setEvidenceSourceTrust } from "@/lib/api/source-trust";
import type { ProvenanceView } from "@/lib/domain/source-trust";
import { TrustTierEnum } from "@/lib/domain/research-advanced";

// adversarial R2 F-001: provenance は mode=provenance のときだけ lazy 取得し、1 request あたりの
// claim 数を hard cap する (page load 時の全 claim prefetch DoS を防ぐ)。
const MAX_PROVENANCE_CLAIMS = 50;
const PROVENANCE_CONCURRENCY = 8;

/**
 * SP-027 (ADR-00053): evidence source の manual trust set/clear Server Action (owner-gated)。
 * owner gate / tenant boundary / domain 正規化は backend が enforce。
 */

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type SourceTrustActionState =
  | { kind: "idle" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

function mapError(error: unknown): string {
  if (error instanceof BackendApiError) {
    switch (error.status) {
      case 400:
        return "信頼度の設定が不正です。";
      case 404:
        return "対象の証拠ソースが見つかりません。";
      case 422:
        return "入力値が不正です。";
      case 403:
        return "この操作を行う権限がありません (オーナーのみ)。";
      default:
        return `操作に失敗しました (${error.status})。`;
    }
  }
  return error instanceof Error ? error.message : "操作に失敗しました。";
}

export type ProvenanceFetchResult = {
  items: { claimId: string; view: ProvenanceView }[];
  capped: boolean;
};

export async function fetchClaimProvenanceAction(
  researchTaskId: string,
  claimIds: readonly string[]
): Promise<ProvenanceFetchResult> {
  if (!UUID_PATTERN.test(researchTaskId)) {
    return { items: [], capped: false };
  }
  const valid = claimIds.filter((id) => UUID_PATTERN.test(id));
  const capped = valid.length > MAX_PROVENANCE_CLAIMS;
  const limited = valid.slice(0, MAX_PROVENANCE_CLAIMS);
  const projectId = await getCurrentProjectId();

  const items: { claimId: string; view: ProvenanceView }[] = [];
  for (let i = 0; i < limited.length; i += PROVENANCE_CONCURRENCY) {
    const chunk = limited.slice(i, i + PROVENANCE_CONCURRENCY);
    const results = await Promise.all(
      chunk.map(async (claimId) => {
        const result = await loadClaimProvenance(projectId, researchTaskId, claimId);
        return result.ok ? { claimId, view: result.data } : null;
      })
    );
    for (const r of results) {
      if (r !== null) items.push(r);
    }
  }
  return { items, capped };
}

export async function setSourceTrustAction(
  _prev: SourceTrustActionState,
  formData: FormData
): Promise<SourceTrustActionState> {
  const researchTaskId = String(formData.get("research_task_id") ?? "");
  const sourceId = String(formData.get("evidence_source_id") ?? "");
  const rawLevel = String(formData.get("trust_level") ?? "");
  const rawScore = String(formData.get("trust_score") ?? "").trim();
  if (!UUID_PATTERN.test(sourceId)) {
    return { kind: "error", message: "不正な証拠ソース ID です。" };
  }

  // 空 = clear (level null + score null)。
  const isClear = rawLevel === "" || rawLevel === "clear";
  const levelParsed = isClear ? null : TrustTierEnum.safeParse(rawLevel);
  if (levelParsed !== null && !levelParsed.success) {
    return { kind: "error", message: "信頼度を選択してください。" };
  }

  let trustScore: number | null = null;
  if (!isClear && rawScore !== "") {
    const n = Number(rawScore);
    if (!Number.isFinite(n) || n < 0 || n > 1) {
      return { kind: "error", message: "スコアは 0.0〜1.0 の数値で入力してください。" };
    }
    trustScore = n;
  }

  try {
    await setEvidenceSourceTrust(sourceId, {
      trust_level: levelParsed === null ? null : levelParsed.data,
      trust_score: trustScore
    });
    if (UUID_PATTERN.test(researchTaskId)) {
      revalidatePath(`/research/${researchTaskId}`);
    } else {
      revalidatePath("/research");
    }
    return { kind: "ok", message: isClear ? "信頼度をクリアしました。" : "信頼度を設定しました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}
