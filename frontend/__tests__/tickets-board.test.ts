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

import { loadProjectTags, loadProjects, loadTickets } from "@/lib/api/tickets-board";

const PID = "00000000-0000-4000-8000-000000000004";
const TAG_ID = "00000000-0000-4000-8000-00000000a001";

beforeEach(() => {
  fetchBackendRaw.mockReset();
  listTags.mockReset();
});

describe("loadTickets fail-closed boundary (Codex frontend R2 HIGH)", () => {
  it("uses ?tag_id= query when a tag is given", async () => {
    fetchBackendRaw.mockResolvedValue({ items: [], total: 0 });
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

  it("always rethrows on failure (caller decides fail-soft vs fail-closed), even unfiltered", async () => {
    // loadTickets 自身は [] に潰さない (Codex R5 HIGH)。fail-soft は all view caller の責務。
    fetchBackendRaw.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadTickets(PID)).rejects.toBeInstanceOf(BackendApiError);
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

  it("throws on malformed tag metadata instead of silently dropping it (R6 HIGH)", async () => {
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
    // palette 外 color (magenta) は version skew / drift。[] に潰すと tag 付き ticket を「タグなし」と
    // silent 誤表示するため fail-closed で throw する (不完全を完全と見せない)。
    await expect(loadTickets(PID)).rejects.toThrow();
  });

  it("accepts an explicit empty tags array as a valid no-tag ticket (not malformed)", async () => {
    fetchBackendRaw.mockResolvedValue({
      items: [
        { id: "t1", title: "x", status: "open", priority: null, description: null, due_date: null, created_at: null, tags: [] }
      ],
      total: 1
    });
    const result = await loadTickets(PID);
    expect(result.items[0]?.tags).toEqual([]);
  });

  it("throws when tags metadata is omitted (version skew / degraded), distinct from explicit [] (R7 HIGH)", async () => {
    fetchBackendRaw.mockResolvedValue({
      items: [
        { id: "t1", title: "x", status: "open", priority: null, description: null, due_date: null, created_at: null }
      ],
      total: 1
    });
    await expect(loadTickets(PID)).rejects.toThrow();
  });

  it("throws when tags metadata is null (degraded serializer)", async () => {
    fetchBackendRaw.mockResolvedValue({
      items: [
        { id: "t1", title: "x", status: "open", priority: null, description: null, due_date: null, created_at: null, tags: null }
      ],
      total: 1
    });
    await expect(loadTickets(PID)).rejects.toThrow();
  });

  it("throws when items envelope is omitted or null (degraded board response, R8 HIGH)", async () => {
    fetchBackendRaw.mockResolvedValueOnce({ total: 0 });
    await expect(loadTickets(PID, TAG_ID)).rejects.toThrow();
    fetchBackendRaw.mockResolvedValueOnce({ items: null, total: 0 });
    await expect(loadTickets(PID, TAG_ID)).rejects.toThrow();
  });

  it("throws when total is omitted or non-numeric (R8 HIGH)", async () => {
    fetchBackendRaw.mockResolvedValueOnce({ items: [] });
    await expect(loadTickets(PID, TAG_ID)).rejects.toThrow();
    fetchBackendRaw.mockResolvedValueOnce({ items: [], total: "5" });
    await expect(loadTickets(PID, TAG_ID)).rejects.toThrow();
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

describe("loadProjects fail-closed boundary (Codex frontend R5 HIGH)", () => {
  it("rethrows when failClosed (specific project / tag filter) so a /me/projects outage cannot render an empty board as complete", async () => {
    fetchBackendRaw.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadProjects(true)).rejects.toBeInstanceOf(BackendApiError);
  });

  it("returns [] when not failClosed (all view aggregation)", async () => {
    fetchBackendRaw.mockRejectedValue(new BackendApiError(500, "boom"));
    await expect(loadProjects(false)).resolves.toEqual([]);
  });

  it("returns projects on success", async () => {
    fetchBackendRaw.mockResolvedValue({ projects: [{ id: PID, slug: "p", name: "P" }] });
    await expect(loadProjects(true)).resolves.toHaveLength(1);
  });

  it("captures project status when present (A-7: archived 強調ゲート用)", async () => {
    fetchBackendRaw.mockResolvedValue({
      projects: [
        { id: PID, slug: "active-p", name: "A", status: "active" },
        { id: PID, slug: "archived-p", name: "B", status: "archived" }
      ]
    });
    const projects = await loadProjects(true);
    expect(projects.map((p) => p.status)).toEqual(["active", "archived"]);
  });

  it("status は optional (欠落 row も成功扱い、後方互換)", async () => {
    fetchBackendRaw.mockResolvedValue({ projects: [{ id: PID, slug: "p", name: "P" }] });
    const projects = await loadProjects(true);
    expect(projects[0]?.status).toBeUndefined();
  });

  it("throws when failClosed and a project row is missing slug (degraded response)", async () => {
    // slug 欠落 row を成功扱いすると selectedProject が解決できず空 board を誤表示する (R6 HIGH)
    fetchBackendRaw.mockResolvedValue({ projects: [{ id: PID, name: "P" }] });
    await expect(loadProjects(true)).rejects.toThrow();
  });

  it("throws when failClosed and a project row has neither project_id nor id", async () => {
    fetchBackendRaw.mockResolvedValue({ projects: [{ slug: "p", name: "P" }] });
    await expect(loadProjects(true)).rejects.toThrow();
  });

  it("returns [] for malformed project rows when not failClosed (all view)", async () => {
    fetchBackendRaw.mockResolvedValue({ projects: [{ name: "P" }] });
    await expect(loadProjects(false)).resolves.toEqual([]);
  });

  it("throws when the projects/items envelope is absent or null (failClosed, R8 HIGH)", async () => {
    fetchBackendRaw.mockResolvedValueOnce({});
    await expect(loadProjects(true)).rejects.toThrow();
    fetchBackendRaw.mockResolvedValueOnce({ projects: null });
    await expect(loadProjects(true)).rejects.toThrow();
  });

  it("accepts an explicit empty projects array", async () => {
    fetchBackendRaw.mockResolvedValue({ projects: [] });
    await expect(loadProjects(true)).resolves.toEqual([]);
  });
});
