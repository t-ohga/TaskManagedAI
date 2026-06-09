import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ refresh: vi.fn(), push: vi.fn() }))
}));

import { SourceTrustSection } from "@/app/(admin)/research/[id]/_source-trust-components";
import type { EffectiveSourceTrust } from "@/lib/domain/source-trust";

const SOURCE_ID = "00000000-0000-4000-8000-000000047006";

function manualTrust(score: number | null): EffectiveSourceTrust {
  return {
    evidence_source_id: SOURCE_ID,
    trust_level: "high",
    trust_score: score,
    origin: "manual",
    domain: null,
    match_type: "none"
  };
}

afterEach(() => {
  localStorage.clear();
  vi.restoreAllMocks();
});

describe("SourceTrustSection manual score round-trip (F-3)", () => {
  it("prepopulates the score input with the existing manual score", () => {
    render(
      <SourceTrustSection
        researchTaskId="00000000-0000-4000-8000-000000047004"
        sourceTrust={[manualTrust(0.95)]}
        claimIds={[]}
      />
    );
    // detailed mode (default) で ManualTrustForm が render される。
    const scoreInput = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(scoreInput.value).toBe("0.95");
  });

  it("leaves the score input empty when no manual score is set", () => {
    render(
      <SourceTrustSection
        researchTaskId="00000000-0000-4000-8000-000000047004"
        sourceTrust={[manualTrust(null)]}
        claimIds={[]}
      />
    );
    const scoreInput = screen.getByRole("spinbutton") as HTMLInputElement;
    expect(scoreInput.value).toBe("");
  });

  it("renders the citation render mode toggle", () => {
    render(
      <SourceTrustSection
        researchTaskId="00000000-0000-4000-8000-000000047004"
        sourceTrust={[]}
        claimIds={[]}
      />
    );
    expect(screen.getByRole("button", { name: "簡易" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "詳細" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "来歴" })).toBeInTheDocument();
  });
});
