import { afterEach, describe, expect, it, vi } from "vitest";

import {
  updateProjectProfileAction,
  type SettingsActionState
} from "../app/(admin)/settings/actions";

vi.mock("next/cache", () => ({
  revalidatePath: vi.fn()
}));

const updateProjectProfileMock = vi.fn();
const updateProjectAutonomyLevelMock = vi.fn();

vi.mock("@/lib/api/session", () => ({
  updateProjectProfile: (...args: unknown[]) => updateProjectProfileMock(...args),
  updateProjectAutonomyLevel: (...args: unknown[]) =>
    updateProjectAutonomyLevelMock(...args)
}));

const PROJECT_ID = "00000000-0000-4000-8000-0000000cc001";
const IDLE: SettingsActionState = { kind: "idle" };

function buildFormData(values: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(values)) {
    data.set(key, value);
  }
  return data;
}

afterEach(() => {
  vi.clearAllMocks();
});

describe("updateProjectProfileAction (M-3 / ADR-00035, Codex R2 MEDIUM)", () => {
  it("rejects a blank name without calling the API (no silent description-only update)", async () => {
    const formData = buildFormData({
      project_id: PROJECT_ID,
      name: "   ",
      description: "新しい説明"
    });

    const result = await updateProjectProfileAction(IDLE, formData);

    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toContain("プロジェクト名を入力してください");
    }
    // blank name は検証エラーであり、description-only 更新として API を呼ばない
    expect(updateProjectProfileMock).not.toHaveBeenCalled();
  });

  it("rejects an empty (omitted-equivalent) name field", async () => {
    const formData = buildFormData({
      project_id: PROJECT_ID,
      name: "",
      description: "x"
    });

    const result = await updateProjectProfileAction(IDLE, formData);

    expect(result.kind).toBe("error");
    expect(updateProjectProfileMock).not.toHaveBeenCalled();
  });

  it("sends trimmed name + description (cleared to null on empty) on success", async () => {
    updateProjectProfileMock.mockResolvedValueOnce({
      tenant_id: 1,
      project_id: PROJECT_ID,
      workspace_id: "00000000-0000-4000-8000-0000000cc002",
      slug: "p",
      name: "My Project",
      description: null,
      status: "active",
      policy_profile: "default",
      autonomy_level: "L0"
    });

    const formData = buildFormData({
      project_id: PROJECT_ID,
      name: "  My Project  ",
      description: ""
    });

    const result = await updateProjectProfileAction(IDLE, formData);

    expect(result.kind).toBe("ok");
    expect(updateProjectProfileMock).toHaveBeenCalledTimes(1);
    expect(updateProjectProfileMock).toHaveBeenCalledWith(PROJECT_ID, {
      name: "My Project",
      description: null
    });
  });

  it("rejects a malformed project_id", async () => {
    const formData = buildFormData({
      project_id: "not-a-uuid",
      name: "Valid",
      description: "ok"
    });

    const result = await updateProjectProfileAction(IDLE, formData);

    expect(result.kind).toBe("error");
    expect(updateProjectProfileMock).not.toHaveBeenCalled();
  });

  // Codex adversarial R4 (MEDIUM): 未編集 (absent) の name は payload に含めない。
  it("updates description only when the name field is absent (no unintended name revert)", async () => {
    updateProjectProfileMock.mockResolvedValueOnce({
      tenant_id: 1,
      project_id: PROJECT_ID,
      workspace_id: "00000000-0000-4000-8000-0000000cc002",
      slug: "p",
      name: "Unchanged",
      description: "新説明",
      status: "active",
      policy_profile: "default",
      autonomy_level: "L0"
    });

    // name field 自体を送らない (= ユーザーが name を編集していない)
    const formData = buildFormData({
      project_id: PROJECT_ID,
      description: "新説明"
    });

    const result = await updateProjectProfileAction(IDLE, formData);

    expect(result.kind).toBe("ok");
    expect(updateProjectProfileMock).toHaveBeenCalledTimes(1);
    // payload は description のみ。name は含めない (他方の更新を巻き戻さない)
    expect(updateProjectProfileMock).toHaveBeenCalledWith(PROJECT_ID, {
      description: "新説明"
    });
  });

  it("returns a no-change result without calling the API when nothing is sent", async () => {
    const formData = buildFormData({ project_id: PROJECT_ID });

    const result = await updateProjectProfileAction(IDLE, formData);

    expect(result.kind).toBe("error");
    if (result.kind === "error") {
      expect(result.message).toContain("変更する項目がありません");
    }
    expect(updateProjectProfileMock).not.toHaveBeenCalled();
  });
});
