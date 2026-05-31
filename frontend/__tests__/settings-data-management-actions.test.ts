import { afterEach, describe, expect, it, vi } from "vitest";

import { BackendApiError } from "@/lib/api/client";
import type * as SessionModule from "@/lib/api/session";

import {
  archiveProjectAction,
  bulkSoftDeleteAction,
  importTicketsAction,
  restoreBatchAction,
  type ImportActionState,
  type SettingsActionState
} from "../app/(admin)/settings/actions";

vi.mock("next/cache", () => ({
  revalidatePath: vi.fn()
}));

const archiveProjectMock = vi.fn();
const bulkSoftDeleteTicketsMock = vi.fn();
const restoreTicketBatchMock = vi.fn();
const importTicketsMock = vi.fn();

// TicketImportItemSchema (実 Zod schema) は import action の validation に必要なため
// importOriginal で本物を保ち、network 関数のみ mock で差し替える。
vi.mock("@/lib/api/session", async (importOriginal) => {
  const actual = await importOriginal<typeof SessionModule>();
  return {
    ...actual,
    archiveProject: (...args: unknown[]) => archiveProjectMock(...args),
    bulkSoftDeleteTickets: (...args: unknown[]) => bulkSoftDeleteTicketsMock(...args),
    restoreTicketBatch: (...args: unknown[]) => restoreTicketBatchMock(...args),
    importTickets: (...args: unknown[]) => importTicketsMock(...args)
  };
});

const PROJECT_ID = "00000000-0000-4000-8000-0000000cc001";
const BATCH_ID = "00000000-0000-4000-8000-0000000cc099";
const IDLE: SettingsActionState = { kind: "idle" };
const IDLE_IMPORT: ImportActionState = { kind: "idle" };

function buildFormData(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) {
    data.set(key, value);
  }
  return data;
}

function projectItem(overrides: Record<string, unknown> = {}) {
  return {
    tenant_id: 1,
    project_id: PROJECT_ID,
    workspace_id: "00000000-0000-4000-8000-0000000cc002",
    slug: "p",
    name: "P",
    description: null,
    status: "active",
    policy_profile: "default",
    autonomy_level: "L0",
    ...overrides
  };
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("archiveProjectAction (Q-4 / ADR-00037)", () => {
  it("archives with CAS baseline and reports success", async () => {
    archiveProjectMock.mockResolvedValueOnce(projectItem({ status: "archived" }));
    const result = await archiveProjectAction(
      IDLE,
      buildFormData({
        project_id: PROJECT_ID,
        archived: "true",
        expected_status: "active"
      })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.message).toContain("アーカイブしました");
    expect(archiveProjectMock).toHaveBeenCalledWith(PROJECT_ID, true, "active");
  });

  it("unarchives and reports the解除 message", async () => {
    archiveProjectMock.mockResolvedValueOnce(projectItem({ status: "active" }));
    const result = await archiveProjectAction(
      IDLE,
      buildFormData({
        project_id: PROJECT_ID,
        archived: "false",
        expected_status: "archived"
      })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.message).toContain("解除");
    expect(archiveProjectMock).toHaveBeenCalledWith(PROJECT_ID, false, "archived");
  });

  it("maps a 409 CAS mismatch to a reload prompt", async () => {
    archiveProjectMock.mockRejectedValueOnce(new BackendApiError(409, "conflict"));
    const result = await archiveProjectAction(
      IDLE,
      buildFormData({
        project_id: PROJECT_ID,
        archived: "true",
        expected_status: "active"
      })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("再読み込み");
  });

  it("maps a 404 to a not-found message", async () => {
    archiveProjectMock.mockRejectedValueOnce(new BackendApiError(404, "not found"));
    const result = await archiveProjectAction(
      IDLE,
      buildFormData({
        project_id: PROJECT_ID,
        archived: "true",
        expected_status: "active"
      })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("見つかりません");
  });

  it("rejects a malformed project_id without calling the API", async () => {
    const result = await archiveProjectAction(
      IDLE,
      buildFormData({ project_id: "nope", archived: "true", expected_status: "active" })
    );
    expect(result.kind).toBe("error");
    expect(archiveProjectMock).not.toHaveBeenCalled();
  });
});

describe("bulkSoftDeleteAction (Q-3 / ADR-00037)", () => {
  it("deletes with the CAS count and reports the batch id", async () => {
    bulkSoftDeleteTicketsMock.mockResolvedValueOnce({
      deleted_batch_id: BATCH_ID,
      soft_deleted_count: 3
    });
    const result = await bulkSoftDeleteAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, expected_active_count: "3" })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") {
      expect(result.message).toContain("3 件");
      expect(result.message).toContain(BATCH_ID);
    }
    expect(bulkSoftDeleteTicketsMock).toHaveBeenCalledWith(PROJECT_ID, 3);
  });

  it("reports a no-op (null batch, 0 deleted) without a batch id", async () => {
    bulkSoftDeleteTicketsMock.mockResolvedValueOnce({
      deleted_batch_id: null,
      soft_deleted_count: 0
    });
    const result = await bulkSoftDeleteAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, expected_active_count: "0" })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.message).toContain("削除対象");
  });

  it("maps a 409 (count mismatch or archived) to a reload prompt", async () => {
    bulkSoftDeleteTicketsMock.mockRejectedValueOnce(new BackendApiError(409, "conflict"));
    const result = await bulkSoftDeleteAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, expected_active_count: "3" })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("再読み込み");
  });

  it("rejects a non-numeric expected_active_count", async () => {
    const result = await bulkSoftDeleteAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, expected_active_count: "abc" })
    );
    expect(result.kind).toBe("error");
    expect(bulkSoftDeleteTicketsMock).not.toHaveBeenCalled();
  });
});

describe("restoreBatchAction (Q-3 / ADR-00037)", () => {
  it("restores and reports the count", async () => {
    restoreTicketBatchMock.mockResolvedValueOnce({ restored_count: 2 });
    const result = await restoreBatchAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, deleted_batch_id: BATCH_ID })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.message).toContain("2 件");
    expect(restoreTicketBatchMock).toHaveBeenCalledWith(PROJECT_ID, BATCH_ID);
  });

  it("reports an idempotent no-op when restored_count is 0", async () => {
    restoreTicketBatchMock.mockResolvedValueOnce({ restored_count: 0 });
    const result = await restoreBatchAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, deleted_batch_id: BATCH_ID })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.message).toContain("復元対象がありません");
  });

  it("maps a 409 (archived) to an unarchive prompt", async () => {
    restoreTicketBatchMock.mockRejectedValueOnce(new BackendApiError(409, "archived"));
    const result = await restoreBatchAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, deleted_batch_id: BATCH_ID })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("アーカイブ");
  });

  it("rejects a malformed batch id", async () => {
    const result = await restoreBatchAction(
      IDLE,
      buildFormData({ project_id: PROJECT_ID, deleted_batch_id: "not-a-uuid" })
    );
    expect(result.kind).toBe("error");
    expect(restoreTicketBatchMock).not.toHaveBeenCalled();
  });
});

describe("importTicketsAction (Q-2 / ADR-00037)", () => {
  const validJson = JSON.stringify([
    { slug: "a-1", title: "A" },
    { slug: "a-2", title: "B" }
  ]);

  it("returns a preview (no insert) on dry_run with a valid payload", async () => {
    importTicketsMock.mockResolvedValueOnce({
      dry_run: true,
      valid: true,
      imported_count: 0,
      in_payload_duplicate_slugs: [],
      existing_conflict_slugs: []
    });
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "true", tickets_json: validJson })
    );
    expect(result.kind).toBe("preview");
    if (result.kind === "preview") {
      expect(result.valid).toBe(true);
      expect(result.parsedCount).toBe(2);
      expect(result.json).toBe(validJson);
    }
    expect(importTicketsMock).toHaveBeenCalledWith(
      PROJECT_ID,
      [
        { slug: "a-1", title: "A" },
        { slug: "a-2", title: "B" }
      ],
      true
    );
  });

  it("surfaces conflict slugs in the preview", async () => {
    importTicketsMock.mockResolvedValueOnce({
      dry_run: true,
      valid: false,
      imported_count: 0,
      in_payload_duplicate_slugs: ["dup"],
      existing_conflict_slugs: ["taken"]
    });
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "true", tickets_json: validJson })
    );
    expect(result.kind).toBe("preview");
    if (result.kind === "preview") {
      expect(result.valid).toBe(false);
      expect(result.inPayloadDuplicateSlugs).toEqual(["dup"]);
      expect(result.existingConflictSlugs).toEqual(["taken"]);
    }
  });

  it("commits and reports the imported count on dry_run=false", async () => {
    importTicketsMock.mockResolvedValueOnce({
      dry_run: false,
      valid: true,
      imported_count: 2,
      in_payload_duplicate_slugs: [],
      existing_conflict_slugs: []
    });
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "false", tickets_json: validJson })
    );
    expect(result.kind).toBe("ok");
    if (result.kind === "ok") expect(result.message).toContain("2 件");
  });

  it("rejects invalid JSON without calling the API", async () => {
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "true", tickets_json: "{not json" })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("JSON");
    expect(importTicketsMock).not.toHaveBeenCalled();
  });

  it("rejects schema-invalid items (bad slug) without calling the API", async () => {
    const badJson = JSON.stringify([{ slug: "Bad Slug", title: "x" }]);
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "true", tickets_json: badJson })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("不正");
    expect(importTicketsMock).not.toHaveBeenCalled();
  });

  it("rejects an empty array (min 1)", async () => {
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "true", tickets_json: "[]" })
    );
    expect(result.kind).toBe("error");
    expect(importTicketsMock).not.toHaveBeenCalled();
  });

  it("rejects an item with an overlong title (payload size bound, ADR-00037 / R8)", async () => {
    const json = JSON.stringify([{ slug: "ok", title: "t".repeat(201) }]);
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "true", tickets_json: json })
    );
    expect(result.kind).toBe("error");
    expect(importTicketsMock).not.toHaveBeenCalled();
  });

  it("maps a 422 slug conflict on commit to a conflict message", async () => {
    importTicketsMock.mockRejectedValueOnce(new BackendApiError(422, "conflict"));
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "false", tickets_json: validJson })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("衝突");
  });

  it("maps a 409 (archived / concurrent) on commit to a reload prompt", async () => {
    importTicketsMock.mockRejectedValueOnce(new BackendApiError(409, "archived"));
    const result = await importTicketsAction(
      IDLE_IMPORT,
      buildFormData({ project_id: PROJECT_ID, dry_run: "false", tickets_json: validJson })
    );
    expect(result.kind).toBe("error");
    if (result.kind === "error") expect(result.message).toContain("再読み込み");
  });
});
