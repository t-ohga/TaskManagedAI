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

import { loadTickets } from "@/lib/api/tickets-board";

const PID = "00000000-0000-4000-8000-000000000004";
const TAG_ID = "00000000-0000-4000-8000-00000000a001";

beforeEach(() => {
  fetchBackendRaw.mockReset();
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

  it("fails soft (returns []) for unfiltered requests so one project outage does not break all view", async () => {
    fetchBackendRaw.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadTickets(PID)).resolves.toEqual([]);
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
      ]
    });
    const result = await loadTickets(PID);
    // palette 外 color (magenta) を含む配列は strict validate 失敗 → [] に倒す
    expect(result[0]?.tags).toEqual([]);
  });
});
