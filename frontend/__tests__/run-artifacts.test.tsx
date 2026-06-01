import { render, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { fetchRunArtifacts, RunArtifactSchema } from "../lib/api/agent-runs";
import { RunArtifactsSection } from "../app/(admin)/runs/[id]/run-artifacts-section";

vi.mock("next/headers", () => ({
  cookies: vi.fn(async () => ({ get: () => undefined })),
}));

afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

const RUN_ID = "00000000-0000-4000-8000-0000000bb001";

describe("RunArtifactSchema (ADR-00042 metadata-only)", () => {
  it("strips any content / content_hash body if backend leaks it", () => {
    const parsed = RunArtifactSchema.parse({
      id: "00000000-0000-4000-8000-0000000cc001",
      kind: "plan",
      payload_data_class: "internal",
      trust_level: "validated_artifact",
      exportable: true,
      parent_artifact_id: null,
      created_at: "2026-06-01T10:00:00+00:00",
      // backend が万一返しても schema に無いため drop される。
      content: { stdout: "sk-should-not-appear" },
      content_hash: "a".repeat(64),
    });
    expect(parsed).not.toHaveProperty("content");
    expect(parsed).not.toHaveProperty("content_hash");
    expect(JSON.stringify(parsed)).not.toContain("sk-should-not-appear");
  });
});

describe("fetchRunArtifacts", () => {
  it("rejects an invalid run id before hitting backend", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch");
    await expect(fetchRunArtifacts("../secrets")).rejects.toThrow();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("GETs the run artifacts endpoint and parses metadata-only rows", async () => {
    vi.stubEnv("INTERNAL_API_URL", "http://backend.test");
    const backend = {
      artifacts: [
        {
          id: "00000000-0000-4000-8000-0000000cc001",
          kind: "plan",
          payload_data_class: "internal",
          trust_level: "validated_artifact",
          exportable: true,
          parent_artifact_id: null,
          created_at: "2026-06-01T10:00:00+00:00",
        },
      ],
    };
    const fetchMock = vi
      .spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify(backend), { status: 200 }));

    const result = await fetchRunArtifacts(RUN_ID);
    expect(result.artifacts).toHaveLength(1);
    expect(result.artifacts[0]?.kind).toBe("plan");
    const call = fetchMock.mock.calls[0];
    if (call === undefined) throw new Error("fetch not called");
    expect(String(call[0])).toBe(`http://backend.test/api/v1/agent_runs/${RUN_ID}/artifacts`);
  });
});

describe("RunArtifactsSection (ADR-00042 L-2)", () => {
  const sample = [
    {
      id: "00000000-0000-4000-8000-0000000cc001",
      kind: "plan",
      payload_data_class: "internal",
      trust_level: "validated_artifact",
      exportable: true,
      parent_artifact_id: "00000000-0000-4000-8000-0000000dd001",
      created_at: "2026-06-01T10:00:00+00:00",
    },
  ];

  it("renders artifact metadata badges (kind / trust / class) but no content or hash", () => {
    render(<RunArtifactsSection artifacts={sample} degraded={false} />);
    const list = screen.getByRole("list", { name: "生成物一覧" });
    expect(within(list).getByText("計画")).toBeInTheDocument();
    expect(within(list).getByText("検証済")).toBeInTheDocument();
    expect(within(list).getByText("internal")).toBeInTheDocument();
    // content body / hash / 64-hex digest が DOM に出ない (metadata-only must-ship)。
    const html = list.innerHTML;
    expect(html).not.toMatch(/[0-9a-f]{64}/);
    expect(html).not.toContain("content_hash");
    expect(html).not.toContain("stdout");
  });

  it("renders empty state when there are no artifacts", () => {
    render(<RunArtifactsSection artifacts={[]} degraded={false} />);
    expect(screen.getByText("生成物はまだありません。")).toBeInTheDocument();
  });

  it("renders a degraded notice without crashing the run detail", () => {
    render(<RunArtifactsSection artifacts={null} degraded={true} />);
    expect(screen.getByText("生成物を読み込めませんでした。")).toBeInTheDocument();
  });
});
