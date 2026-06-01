import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type * as ApiClient from "@/lib/api/client";

import AgentRunsPage from "../app/(admin)/runs/page";

const apiMocks = vi.hoisted(() => ({
  fetchBackendRaw: vi.fn(),
  getCostSummary: vi.fn()
}));

vi.mock("@/lib/api/agent-runs", () => ({
  getCostSummary: apiMocks.getCostSummary
}));

// RunsPage の loadRuns は fetchBackendRaw(/api/v1/agent_runs) で run list を取得する
// (per-resource listAgentRuns ではなく fetchBackendRaw 直接)。実 list データはこの mock
// から供給する。BackendApiError 等の実 export は importActual で残す。
vi.mock("@/lib/api/client", async (importActual) => ({
  ...(await importActual<typeof ApiClient>()),
  fetchBackendRaw: apiMocks.fetchBackendRaw
}));

// RunsPage は AutoRefresh client component を含み、これは useRouter().refresh() を
// interval で呼ぶ。App Router context のない RTL 環境では useRouter が "app router
// to be mounted" invariant を投げるため、refresh を no-op にした router を mock する。
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh: vi.fn() })
}));

afterEach(() => {
  apiMocks.fetchBackendRaw.mockReset();
  apiMocks.getCostSummary.mockReset();
});

describe("AgentRunsPage i18n", () => {
  it("renders Japanese page labels while preserving AgentRun raw state values", async () => {
    apiMocks.fetchBackendRaw.mockResolvedValue({
      items: [
        {
          id: "00000000-0000-4000-8000-00000000a001",
          tenant_id: 1,
          project_id: "00000000-0000-4000-8000-00000000a002",
          parent_run_id: null,
          status: "blocked",
          blocked_reason: "runtime_blocked",
          error_code: null,
          error_summary: null,
          completed_at: null,
          role_id: "reviewer",
          role_scope: "project",
          orchestrator_lease_expires_at: null,
          last_progress_at: "2026-05-22T00:00:00Z",
          progress_seq: 3,
          created_at: "2026-05-22T00:00:00Z",
          updated_at: "2026-05-22T00:01:00Z"
        }
      ],
      total: 1,
      limit: 50,
      offset: 0
    });
    // D-4 (PR #308) で追加された cost 集計。i18n ラベル検証では cost section は対象外
    // なので null を返し ``costSummary && run_count > 0`` 条件で非表示にする。
    apiMocks.getCostSummary.mockResolvedValue(null);

    // RunsPage は searchParams (status/role/page filter) を必須 prop に持つ async
    // Server Component。i18n ラベル検証なので空 filter で render する。
    render(await AgentRunsPage({ searchParams: Promise.resolve({}) }));

    // region / heading は i18n で日本語化済 (section aria-label="AI 実行一覧"、h1="AI 実行")。
    const region = screen.getByRole("region", { name: "AI 実行一覧" });
    expect(within(region).getByRole("heading", { name: "AI 実行" })).toBeVisible();
    // status="blocked" + blocked_reason="runtime_blocked" は v2 status indicator
    // (AgentRunStatusIndicator) が reason 固有の日本語ラベル "ランタイム拒否" として描画する。
    // status と blocked_reason を混同せず、blocked のときは reason を別ラベルで表示する契約。
    expect(within(region).getAllByText("ランタイム拒否").length).toBeGreaterThanOrEqual(1);
  });
});
