"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";

import { BackendApiError } from "@/lib/api/client";
import { updateProjectAutonomyLevel, updateProjectProfile } from "@/lib/api/session";

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type SettingsActionState =
  | { kind: "idle" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

// M-3 (ADR-00035): name / description はそれぞれ「送信された場合のみ」更新対象とする。
// field が FormData に存在しない (= ユーザーが編集していない) 場合は省略し、変更なしとして
// 扱う。これにより stale な画面から未編集 field を送って他方の更新を巻き戻す lost update
// を防ぐ (Codex adversarial R4 MEDIUM、touched-field のみ送信する設計)。送信された name が
// blank の場合は必ず検証エラー (Codex adversarial R2 MEDIUM: silent な name 未反映を防ぐ)。
// description は `""` で explicit clear (null)。実際に送る field の絞り込みは Client 側
// (ProjectSettingsForm) が初期値との差分で行い、本 action は present/absent と blank を判定する。
const ProjectProfileFormSchema = z.object({
  project_id: z.string().regex(UUID_PATTERN, "project_id の形式が不正です"),
  name: z.string().trim().min(1, "プロジェクト名を入力してください").optional(),
  description: z.string().nullable().optional()
});

const AutonomyFormSchema = z.object({
  project_id: z.string().regex(UUID_PATTERN, "project_id の形式が不正です"),
  autonomy_level: z.enum(["L0", "L1", "L2", "L3"]),
  // Codex adversarial R7/R8 (HIGH): compare-and-swap の baseline (必須)。ユーザーが編集の基に
  // した現在の autonomy_level を宣言し、backend が DB current と比較する (不一致なら 409)。
  // form は常に hidden field で送る。
  expected_autonomy_level: z.enum(["L0", "L1", "L2", "L3"])
});

function clearableField(
  value: FormDataEntryValue | null
): string | null | undefined {
  if (typeof value !== "string") return undefined;
  return value === "" ? null : value;
}

export async function updateProjectProfileAction(
  _prevState: SettingsActionState,
  formData: FormData
): Promise<SettingsActionState> {
  const rawName = formData.get("name");
  const parsed = ProjectProfileFormSchema.safeParse({
    project_id:
      typeof formData.get("project_id") === "string" ? formData.get("project_id") : "",
    // present (string) → 検証 (blank は min(1) でエラー)。absent → undefined (= 変更なし、省略)。
    name: typeof rawName === "string" ? rawName : undefined,
    description: clearableField(formData.get("description"))
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  const { project_id, name, description } = parsed.data;
  // 送信された (= 編集された) field だけを payload に含める。両方 absent なら更新なし。
  const payload: { name?: string; description?: string | null } = {};
  if (name !== undefined) payload.name = name;
  if (description !== undefined) payload.description = description;

  if (Object.keys(payload).length === 0) {
    return { kind: "error", message: "変更する項目がありません" };
  }

  try {
    await updateProjectProfile(project_id, payload);
    revalidatePath("/settings");
    return { kind: "ok", message: "プロジェクト基本情報を更新しました" };
  } catch (error: unknown) {
    const message =
      error instanceof Error ? error.message : "設定の更新に失敗しました。";
    return { kind: "error", message };
  }
}

export async function updateAutonomyLevelAction(
  _prevState: SettingsActionState,
  formData: FormData
): Promise<SettingsActionState> {
  const rawExpected = formData.get("expected_autonomy_level");
  const parsed = AutonomyFormSchema.safeParse({
    project_id:
      typeof formData.get("project_id") === "string" ? formData.get("project_id") : "",
    autonomy_level: formData.get("autonomy_level"),
    expected_autonomy_level: typeof rawExpected === "string" ? rawExpected : undefined
  });

  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  try {
    const updated = await updateProjectAutonomyLevel(
      parsed.data.project_id,
      parsed.data.autonomy_level,
      parsed.data.expected_autonomy_level
    );
    revalidatePath("/settings");
    return {
      kind: "ok",
      message: `AI 自律レベルを ${updated.autonomy_level} に更新しました`
    };
  } catch (error: unknown) {
    // Codex adversarial R7: compare-and-swap mismatch (別タブ / retry で値が変わった)
    if (error instanceof BackendApiError && error.status === 409) {
      return {
        kind: "error",
        message:
          "自律レベルが別の操作で変更されました。最新の状態を再読み込みしてから操作してください。"
      };
    }
    const message =
      error instanceof Error ? error.message : "自律レベルの更新に失敗しました。";
    return { kind: "error", message };
  }
}
