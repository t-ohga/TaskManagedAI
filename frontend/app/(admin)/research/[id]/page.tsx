import { notFound } from "next/navigation";

import { Breadcrumb } from "@/components/breadcrumb";
import { BackendApiError } from "@/lib/api/client";
import {
  getResearchTask,
  listClaims,
  getEvidenceSource,
  listEvidenceItems,
  type Claim,
  type EvidenceItem,
  type EvidenceSource,
  type ResearchTaskDetail
} from "@/lib/api/research";

import { UUID_V1_TO_V5_PATTERN } from "../../_lib/route-id";
import {
  AdminPageShell,
  KeyboardReadinessStrip,
  Panel,
  SecretBoundaryNotice
} from "../../_components/sprint9-admin-ui";
import {
  ClaimList,
  EvidenceItemList,
  ResearchMetricSummary,
  ResearchTaskCard
} from "./_components";

export const dynamic = "force-dynamic";

type ResearchDetailPageProps = {
  params: Promise<{ id: string }>;
};

type ResearchDetailData = {
  task: ResearchTaskDetail;
  claims: Claim[];
  evidenceItemsByClaimId: Map<string, EvidenceItem[]>;
  allEvidenceItems: EvidenceItem[];
  sourcesById: Map<string, EvidenceSource>;
};

// F-PR26-R2-003 + F-PR26-R2-004 P2 adopt: bound the per-claim
// listEvidenceItems and per-source getEvidenceSource fan-out so a
// research task with hundreds of claims / sources does not exhaust
// server connection capacity. Process in chunks of CONCURRENCY_LIMIT.
const CONCURRENCY_LIMIT = 8;

async function mapWithConcurrency<T, R>(
  items: readonly T[],
  limit: number,
  fn: (item: T) => Promise<R>
): Promise<R[]> {
  const results: R[] = [];
  for (let i = 0; i < items.length; i += limit) {
    const chunk = items.slice(i, i + limit);
    const chunkResults = await Promise.all(chunk.map(fn));
    results.push(...chunkResults);
  }
  return results;
}

async function loadResearchDetail(researchTaskId: string): Promise<ResearchDetailData> {
  // F-PR26-R1-002 P2 adopt: resolve evidence_sources by the specific
  // ``source_id``s referenced from this research task's evidence_items,
  // NOT by fetching the tenant-wide first 200 rows. With >200 sources
  // per tenant the prior approach silently rendered out-of-page
  // references as "source unavailable" even though the backend
  // ``GET /api/v1/evidence-sources/{id}`` endpoint can resolve them.
  const [task, claims] = await Promise.all([
    getResearchTask(researchTaskId),
    listClaims(researchTaskId)
  ]);

  // F-PR26-R2-004 P2 adopt: bounded per-claim fan-out.
  const evidenceItemGroups = await mapWithConcurrency(
    claims,
    CONCURRENCY_LIMIT,
    async (claim) => [claim.id, await listEvidenceItems(claim.id)] as const
  );
  const evidenceItemsByClaimId = new Map<string, EvidenceItem[]>(evidenceItemGroups);
  const allEvidenceItems = evidenceItemGroups.flatMap(([, items]) => items);
  const referencedSourceIds = Array.from(
    new Set(allEvidenceItems.map((item) => item.source_id))
  );
  // F-PR26-R2-003 P2 adopt: bounded per-source fan-out.
  const resolvedSources = await mapWithConcurrency(
    referencedSourceIds,
    CONCURRENCY_LIMIT,
    async (sourceId) => {
      try {
        const source = await getEvidenceSource(sourceId);
        return [sourceId, source] as const;
      } catch {
        return null;
      }
    }
  );
  const sourcesById = new Map<string, EvidenceSource>(
    resolvedSources.filter((entry): entry is readonly [string, EvidenceSource] => entry !== null)
  );

  return {
    task,
    claims,
    evidenceItemsByClaimId,
    allEvidenceItems,
    sourcesById
  };
}

function ErrorPanel({ error }: { readonly error: unknown }) {
  return (
    <Panel
      description="read-only Research detail API が表示可能な response を返しませんでした。"
      title="リサーチ詳細読込エラー"
      titleId="research-detail-load-error"
    >
      <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-danger">
        リサーチ詳細の読込に失敗しました: {error instanceof Error ? error.message : "不明なエラー"}
      </p>
    </Panel>
  );
}

export default async function ResearchDetailPage({ params }: ResearchDetailPageProps) {
  const { id } = await params;

  if (!id || !UUID_V1_TO_V5_PATTERN.test(id)) {
    notFound();
  }

  let detail: ResearchDetailData | null = null;
  let loadError: unknown = null;

  try {
    detail = await loadResearchDetail(id);
  } catch (error) {
    if (error instanceof BackendApiError && error.status === 404) {
      notFound();
    }
    loadError = error;
  }

  return (
    <AdminPageShell
      description={
        <>
          ResearchTask <code>{id}</code> の read-only detail です。
          Claim、evidence item、evidence_set_hash、attachment rate を mutation control
          なしで表示します。
        </>
      }
      eyebrow="管理 / リサーチ"
      regionLabel="リサーチ詳細"
      title="リサーチ詳細"
    >
      {/* F-2 (nav 一貫化): drill-down 詳細 page に clickable back-nav を追加 (tickets/runs/approvals
          詳細と同じ Breadcrumb component。eyebrow は静的表示のため一覧へ戻れなかった)。 */}
      <Breadcrumb
        items={[
          { label: "ダッシュボード", href: "/dashboard" },
          { label: "リサーチ", href: "/research" },
          { label: "リサーチ詳細" },
        ]}
      />
      <KeyboardReadinessStrip current="リサーチ" />

      {detail === null ? (
        <ErrorPanel error={loadError} />
      ) : (
        <>
          <Panel
            description="Server-owned な project boundary と ResearchTask status です。P0 では create / edit / delete control を表示しません。"
            title="リサーチ task"
            titleId="research-detail-task"
          >
            <ResearchTaskCard task={detail.task} />
          </Panel>

          <Panel
            description="Server-computed な evidence_set_hash と per-research_task evidence attachment source metric です。Sprint 11 final citation_coverage aggregator ではありません。"
            title="証拠 metrics"
            titleId="research-detail-metrics"
          >
            <ResearchMetricSummary task={detail.task} />
          </Panel>

          <Panel
            description="PROV は schema-validated summary としてのみ表示し、raw provenance_json は展開しません。"
            title="Claim (主張)"
            titleId="research-detail-claims"
          >
            <ClaimList
              claims={detail.claims}
              evidenceItemsByClaimId={detail.evidenceItemsByClaimId}
            />
          </Panel>

          <Panel
            description="Evidence item row は locator、relation、redacted source link を表示します。EvidenceSource の query string と credential は表示前に除去します。"
            title="Evidence item (証拠 item)"
            titleId="research-detail-evidence-items"
          >
            <EvidenceItemList
              items={detail.allEvidenceItems}
              sourcesById={detail.sourcesById}
            />
          </Panel>

          <Panel
            description="SecretBroker value、capability token、provider raw payload、API key は、この read-only DOM surface に含めません。"
            title="Secret boundary (シークレット境界)"
            titleId="research-detail-secret-boundary"
          >
            <SecretBoundaryNotice title="Research evidence redaction boundary (リサーチ証拠 redaction 境界)" />
          </Panel>
        </>
      )}
    </AdminPageShell>
  );
}
