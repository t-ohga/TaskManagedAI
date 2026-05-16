import { notFound } from "next/navigation";

import { BackendApiError } from "@/lib/api/client";
import {
  getResearchTask,
  listClaims,
  listEvidenceItems,
  listEvidenceSources,
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

async function loadResearchDetail(researchTaskId: string): Promise<ResearchDetailData> {
  const [task, claims, sources] = await Promise.all([
    getResearchTask(researchTaskId),
    listClaims(researchTaskId),
    listEvidenceSources({ limit: 200 })
  ]);

  const evidenceItemGroups = await Promise.all(
    claims.map(async (claim) => [claim.id, await listEvidenceItems(claim.id)] as const)
  );
  const evidenceItemsByClaimId = new Map<string, EvidenceItem[]>(evidenceItemGroups);
  const allEvidenceItems = evidenceItemGroups.flatMap(([, items]) => items);
  const sourcesById = new Map<string, EvidenceSource>(
    sources.items.map((source) => [source.id, source])
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
      description="The read-only Research detail API did not return a renderable response."
      title="Research detail load error"
      titleId="research-detail-load-error"
    >
      <p role="alert" className="rounded-md border border-rose-200 bg-rose-50 p-3 text-sm text-danger">
        Failed to load research detail: {error instanceof Error ? error.message : "unknown error"}
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
          Sprint 10 BL-0120 read-only detail for ResearchTask <code>{id}</code>.
          Claims, evidence items, evidence_set_hash, and attachment rate are rendered
          without mutation controls.
        </>
      }
      eyebrow="Admin / Research"
      regionLabel="Research detail"
      title="Research detail"
    >
      <KeyboardReadinessStrip current="Research" />

      {detail === null ? (
        <ErrorPanel error={loadError} />
      ) : (
        <>
          <Panel
            description="Server-owned project boundary and ResearchTask status. P0 does not expose create, edit, or delete controls."
            title="Research task"
            titleId="research-detail-task"
          >
            <ResearchTaskCard task={detail.task} />
          </Panel>

          <Panel
            description="Server-computed evidence_set_hash and per-research_task evidence attachment source metric. This is not the Sprint 11 final citation_coverage aggregator."
            title="Evidence metrics"
            titleId="research-detail-metrics"
          >
            <ResearchMetricSummary task={detail.task} />
          </Panel>

          <Panel
            description="PROV is rendered as a schema-validated summary only. Raw provenance_json is not expanded."
            title="Claims"
            titleId="research-detail-claims"
          >
            <ClaimList
              claims={detail.claims}
              evidenceItemsByClaimId={detail.evidenceItemsByClaimId}
            />
          </Panel>

          <Panel
            description="Evidence item rows show locator, relation, and a redacted source link. EvidenceSource query strings and credentials are stripped before rendering."
            title="Evidence items"
            titleId="research-detail-evidence-items"
          >
            <EvidenceItemList
              items={detail.allEvidenceItems}
              sourcesById={detail.sourcesById}
            />
          </Panel>

          <Panel
            description="SecretBroker values, capability tokens, provider raw payloads, and API keys are not part of this read-only DOM surface."
            title="Secret boundary"
            titleId="research-detail-secret-boundary"
          >
            <SecretBoundaryNotice title="Research evidence redaction boundary" />
          </Panel>
        </>
      )}
    </AdminPageShell>
  );
}
