import { beforeEach, describe, expect, it, vi } from "vitest";

import { BackendApiError } from "@/lib/api/client";
import type * as ClientModule from "@/lib/api/client";

// fetchBackendRaw を mock し、loadTickets の fail-closed / fail-soft 境界を検証する。
const fetchBackendRaw = vi.fn();
vi.mock("@/lib/api/client", async () => {
  const actual = await vi.importActual<typeof ClientModule>("@/lib/api/client");
  return {
    ...actual,
    fetchBackendRaw: (...args: unknown[]) => fetchBackendRaw(...args)
  };
});

// listTags を mock し、loadProjectTags の fail-closed / fail-soft 境界を検証する。
const listTags = vi.fn();
vi.mock("@/lib/api/tags", () => ({
  listTags: (...args: unknown[]) => listTags(...args)
}));

import { loadProjectTags, loadTickets } from "@/lib/api/tickets-board";

const PID = "00000000-0000-4000-8000-000000000004";
const TAG_ID = "00000000-0000-4000-8000-00000000a001";

beforeEach(() => {
  fetchBackendRaw.mockReset();
  listTags.mockReset();
});

describe("loadTickets fail-closed boundary (Codex frontend R2 HIGH)", () => {
  it("uses ?tag_id= query when a tag is given", async () => {
    fetchBackendRaw.mockResolvedValue({ items: [] });
    await loadTickets(PID, TAG_ID);
    expect(fetchBackendRaw).toHaveBeenCalledWith(
      `/api/v1/projects/${PID}/tickets?limit=200&tag_id=${TAG_ID}`
    );
  });

  it("rethrows 404 for an invalid tag (caller clears the filter)", async () => {
    fetchBackendRaw.mockRejectedValue(new BackendApiError(404, "not found"));
    await expect(loadTickets(PID, TAG_ID)).rejects.toBeInstanceOf(BackendApiError);
  });

  it("rethrows 403/500 during a tag-filtered request instead of returning []", async () => {
    for (const status of [403, 500, 503]) {
      fetchBackendRaw.mockRejectedValueOnce(new BackendApiError(status, "boom"));
      await expect(loadTickets(PID, TAG_ID)).rejects.toBeInstanceOf(BackendApiError);
    }
  });

  it("rethrows network errors during a tag-filtered request", async () => {
    fetchBackendRaw.mockRejectedValue(new TypeError("network failure"));
    await expect(loadTickets(PID, TAG_ID)).rejects.toThrow("network failure");
  });

  it("fails soft (empty result) for unfiltered requests so one project outage does not break all view", async () => {
    fetchBackendRaw.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadTickets(PID)).resolves.toEqual({ items: [], total: 0, truncated: false });
  });

  it("flags truncated=true when total exceeds the returned page (200 items, total 201)", async () => {
    const items = Array.from({ length: 200 }, (_v, i) => ({
      id: `t${i}`,
      title: "x",
      status: "open",
      priority: null,
      description: null,
      due_date: null,
      created_at: null,
      tags: []
    }));
    fetchBackendRaw.mockResolvedValue({ items, total: 201 });
    const result = await loadTickets(PID, TAG_ID);
    // 不完全 (201 件中 200 件) を完全な結果として見せないため truncated を立てる (Codex R3 HIGH)
    expect(result.total).toBe(201);
    expect(result.items).toHaveLength(200);
    expect(result.truncated).toBe(true);
  });

  it("reports truncated=false when the full filtered set fits in one page", async () => {
    fetchBackendRaw.mockResolvedValue({
      items: [
        { id: "t1", title: "x", status: "open", priority: null, description: null, due_date: null, created_at: null, tags: [] }
      ],
      total: 1
    });
    const result = await loadTickets(PID, TAG_ID);
    expect(result.truncated).toBe(false);
  });

  it("validates per-ticket tags and drops palette-drifted entries", async () => {
    fetchBackendRaw.mockResolvedValue({
      items: [
        {
          id: "t1",
          title: "x",
          status: "open",
          priority: null,
          description: null,
          due_date: null,
          created_at: null,
          tags: [
            { id: TAG_ID, name: "bug", color: "red" },
            { id: "00000000-0000-4000-8000-00000000b002", name: "bad", color: "magenta" }
          ]
        }
      ],
      total: 1
    });
    const result = await loadTickets(PID);
    // palette 外 color (magenta) を含む配列は strict validate 失敗 → [] に倒す
    expect(result.items[0]?.tags).toEqual([]);
  });
});

describe("loadProjectTags fail-closed boundary (Codex frontend R4 HIGH)", () => {
  it("rethrows when failClosed (tag filter active) so a degraded tag list cannot hide the filter", async () => {
    listTags.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadProjectTags(PID, true)).rejects.toBeInstanceOf(BackendApiError);
  });

  it("returns [] when not failClosed (no tag filter) so tag UI degrades softly", async () => {
    listTags.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadProjectTags(PID, false)).resolves.toEqual([]);
  });

  it("returns tag items on success", async () => {
    listTags.mockResolvedValue({ items: [{ id: TAG_ID, name: "bug", color: "red" }] });
    await expect(loadProjectTags(PID, true)).resolves.toHaveLength(1);
  });
});
