import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type * as ResearchApiModule_ from "@/lib/api/research";
type ResearchApiModule = typeof ResearchApiModule_;


import ResearchDetailPage from "@/app/(admin)/research/[id]/page";

const apiMocks = vi.hoisted(() => ({
  getResearchTask: vi.fn(),
  listClaims: vi.fn(),
  listEvidenceItems: vi.fn(),
  getEvidenceSource: vi.fn()
}));

vi.mock("next/navigation", () => ({
  notFound: vi.fn(() => {
    throw new Error("NEXT_NOT_FOUND");
  })
}));

vi.mock("@/lib/api/research", async (importOriginal) => {
  const actual = await importOriginal<ResearchApiModule>();
  return {
    ...actual,
    getResearchTask: apiMocks.getResearchTask,
    listClaims: apiMocks.listClaims,
    listEvidenceItems: apiMocks.listEvidenceItems,
    getEvidenceSource: apiMocks.getEvidenceSource
  };
});

afterEach(() => {
  apiMocks.getResearchTask.mockReset();
  apiMocks.listClaims.mockReset();
  apiMocks.listEvidenceItems.mockReset();
  apiMocks.getEvidenceSource.mockReset();
});

describe("ResearchDetailPage", () => {
  it("renders claims, evidence items, evidence_set_hash, and attachment rate", async () => {
    const researchTaskId = "00000000-0000-4000-8000-000000042001";
    const claimId = "00000000-0000-4000-8000-000000042002";
    const sourceId = "00000000-0000-4000-8000-000000042003";

    apiMocks.getResearchTask.mockResolvedValue({
      id: researchTaskId,
      tenant_id: 1,
      project_id: "00000000-0000-4000-8000-000000000004",
      title: "Research UI detail",
      status: "completed",
      created_by_actor_id: "00000000-0000-4000-8000-000000042004",
      created_at: "2026-05-16T00:00:00Z",
      updated_at: "2026-05-16T00:01:00Z",
      metadata: { rls_ready: true },
      evidence_set_hash: "a".repeat(64),
      research_evidence_attachment: {
        metric_kind: "research_evidence_attachment",
        research_task_id: researchTaskId,
        numerator: 1,
        denominator: 1,
        computed_at: "2026-05-16T00:02:00Z",
        attachment_rate: 1
      }
    });
    apiMocks.listClaims.mockResolvedValue([
      {
        id: claimId,
        tenant_id: 1,
        project_id: "00000000-0000-4000-8000-000000000004",
        research_task_id: researchTaskId,
        claim_text: "Claim with attached evidence",
        provenance_json: {
          activities: [{ id: "activity:research", type: "prov:Activity" }],
          entities: [{ id: "entity:claim", type: "prov:Entity" }],
          agents: [],
          wasGeneratedBy: [{ entity: "entity:claim", activity: "activity:research" }],
          used: [],
          wasAttributedTo: [],
          wasInformedBy: [],
          wasDerivedFrom: []
        },
        freshness_score: 0.9,
        metadata: { rls_ready: true, secret_ref: "secret://sops/app/token#v1" },
        created_at: "2026-05-16T00:03:00Z",
        updated_at: "2026-05-16T00:04:00Z"
      }
    ]);
    apiMocks.listEvidenceItems.mockResolvedValue([
      {
        id: "00000000-0000-4000-8000-000000042005",
        tenant_id: 1,
        project_id: "00000000-0000-4000-8000-000000000004",
        claim_id: claimId,
        source_id: sourceId,
        locator: "paragraph 4",
        relation: "supports",
        relevance_score: 0.8,
        metadata: { rls_ready: true, capability_token: "capability-token-raw" },
        created_at: "2026-05-16T00:05:00Z",
        updated_at: "2026-05-16T00:06:00Z"
      }
    ]);
    apiMocks.getEvidenceSource.mockResolvedValue({
      id: sourceId,
      tenant_id: 1,
      canonical_url: "https://example.com/source",
      content_hash: "b".repeat(64),
      retrieved_at: "2026-05-16T00:07:00Z",
      published_at: null,
      created_at: "2026-05-16T00:08:00Z",
      updated_at: "2026-05-16T00:09:00Z",
      metadata: { rls_ready: true }
    });

    render(await ResearchDetailPage({ params: Promise.resolve({ id: researchTaskId }) }));

    expect(screen.getByRole("heading", { name: "リサーチ詳細" })).toBeVisible();
    expect(screen.getByText("Research UI detail")).toBeVisible();
    expect(screen.getByText("完了 (completed)")).toBeVisible();
    expect(screen.getByText("Claim with attached evidence")).toBeVisible();
    expect(screen.getByText("paragraph 4")).toBeVisible();
    expect(screen.getAllByText("支持 (supports)").length).toBeGreaterThan(0);
    expect(screen.getByText("a".repeat(64))).toBeVisible();
    expect(screen.getByText("100%")).toBeVisible();
    expect(screen.getByRole("link", { name: "https://example.com/source" })).toHaveAttribute(
      "href",
      "https://example.com/source"
    );

    const bodyText = document.body.textContent ?? "";
    expect(bodyText).not.toContain("secret://sops");
    expect(bodyText).not.toContain("capability-token-raw");
    expect(bodyText).not.toContain("raw-secret-key");
    expect(bodyText).not.toContain("api_key");
  });
});
