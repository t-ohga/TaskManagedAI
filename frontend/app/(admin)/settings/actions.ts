"use server";

import { z } from "zod";

import { BackendApiError } from "@/lib/api/client";
import {
  archiveProject,
  bulkSoftDeleteTickets,
  importTickets,
  restoreTicketBatch,
  TicketImportItemSchema,
  updateProjectAutonomyLevel,
  updateProjectProfile
} from "@/lib/api/session";

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

// =====================================================================
// Q-2〜Q-4 (ADR-00037): データ管理 (破壊的操作)。owner gate は backend で enforce。
// C-5 系統適用: revalidatePath は撤去 (Next.js 16 + React 19 の isPending 固着 regression、表示更新は
// client full reload に委譲、参照 #82289/#88767)。CAS / archived は 409 を user-facing message に写像。
// =====================================================================

const ArchiveFormSchema = z.object({
  project_id: z.string().regex(UUID_PATTERN, "project_id の形式が不正です"),
  archived: z.enum(["true", "false"]),
  expected_status: z.enum(["active", "archived"])
});

export async function archiveProjectAction(
  _prevState: SettingsActionState,
  formData: FormData
): Promise<SettingsActionState> {
  const parsed = ArchiveFormSchema.safeParse({
    project_id: formData.get("project_id"),
    archived: formData.get("archived"),
    expected_status: formData.get("expected_status")
  });
  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  const archived = parsed.data.archived === "true";
  try {
    const updated = await archiveProject(
      parsed.data.project_id,
      archived,
      parsed.data.expected_status
    );
    return {
      kind: "ok",
      message:
        updated.status === "archived"
          ? "プロジェクトをアーカイブしました"
          : "プロジェクトのアーカイブを解除しました"
    };
  } catch (error: unknown) {
    if (error instanceof BackendApiError && error.status === 409) {
      return {
        kind: "error",
        message:
          "プロジェクトの状態が別の操作で変更されました。最新の状態を再読み込みしてから操作してください。"
      };
    }
    if (error instanceof BackendApiError && error.status === 404) {
      return { kind: "error", message: "プロジェクトが見つかりませんでした。" };
    }
    const message =
      error instanceof Error ? error.message : "アーカイブ操作に失敗しました。";
    return { kind: "error", message };
  }
}

const BulkSoftDeleteFormSchema = z.object({
  project_id: z.string().regex(UUID_PATTERN, "project_id の形式が不正です"),
  expected_active_count: z.coerce.number().int().nonnegative()
});

export async function bulkSoftDeleteAction(
  _prevState: SettingsActionState,
  formData: FormData
): Promise<SettingsActionState> {
  const parsed = BulkSoftDeleteFormSchema.safeParse({
    project_id: formData.get("project_id"),
    expected_active_count: formData.get("expected_active_count")
  });
  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  try {
    const result = await bulkSoftDeleteTickets(
      parsed.data.project_id,
      parsed.data.expected_active_count
    );
    if (result.soft_deleted_count === 0 || result.deleted_batch_id === null) {
      // no-op (active 0 件): batch は発行されない。
      return { kind: "ok", message: "削除対象のアクティブ ticket はありませんでした。" };
    }
    return {
      kind: "ok",
      message: `${result.soft_deleted_count} 件の ticket を削除しました (バッチ ${result.deleted_batch_id})。復元バッチ ID を控えてください。`
    };
  } catch (error: unknown) {
    // 409: CAS 件数不一致 または archived project (どちらも再読み込みで解消)
    if (error instanceof BackendApiError && error.status === 409) {
      return {
        kind: "error",
        message:
          "ticket 件数が変わったか、プロジェクトがアーカイブされています。最新の状態を再読み込みしてから操作してください。"
      };
    }
    const message =
      error instanceof Error ? error.message : "一括削除に失敗しました。";
    return { kind: "error", message };
  }
}

const RestoreFormSchema = z.object({
  project_id: z.string().regex(UUID_PATTERN, "project_id の形式が不正です"),
  deleted_batch_id: z
    .string()
    .regex(UUID_PATTERN, "復元バッチ ID (UUID) の形式が不正です")
});

export async function restoreBatchAction(
  _prevState: SettingsActionState,
  formData: FormData
): Promise<SettingsActionState> {
  const parsed = RestoreFormSchema.safeParse({
    project_id: formData.get("project_id"),
    deleted_batch_id:
      typeof formData.get("deleted_batch_id") === "string"
        ? (formData.get("deleted_batch_id") as string).trim()
        : ""
  });
  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  try {
    const result = await restoreTicketBatch(
      parsed.data.project_id,
      parsed.data.deleted_batch_id
    );
    if (result.restored_count === 0) {
      return {
        kind: "ok",
        message:
          "復元対象がありませんでした (バッチ ID が一致しない / 既に復元済み)。"
      };
    }
    return {
      kind: "ok",
      message: `${result.restored_count} 件の ticket を復元しました。`
    };
  } catch (error: unknown) {
    if (error instanceof BackendApiError && error.status === 409) {
      return {
        kind: "error",
        message:
          "プロジェクトがアーカイブされています。アーカイブを解除してから復元してください。"
      };
    }
    const message =
      error instanceof Error ? error.message : "復元に失敗しました。";
    return { kind: "error", message };
  }
}

export type ImportActionState =
  | { kind: "idle" }
  | {
      kind: "preview";
      valid: boolean;
      inPayloadDuplicateSlugs: string[];
      existingConflictSlugs: string[];
      parsedCount: number;
      json: string;
    }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

const ImportFormSchema = z.object({
  project_id: z.string().regex(UUID_PATTERN, "project_id の形式が不正です"),
  dry_run: z.enum(["true", "false"]),
  tickets_json: z.string()
});

export async function importTicketsAction(
  _prevState: ImportActionState,
  formData: FormData
): Promise<ImportActionState> {
  const parsed = ImportFormSchema.safeParse({
    project_id: formData.get("project_id"),
    dry_run: formData.get("dry_run"),
    tickets_json: formData.get("tickets_json")
  });
  if (!parsed.success) {
    return {
      kind: "error",
      message: parsed.error.issues.map((issue) => issue.message).join(", ")
    };
  }

  const dryRun = parsed.data.dry_run === "true";

  // JSON parse + client-side schema validation (untrusted boundary、AI 出力直結なし)。
  let rawItems: unknown;
  try {
    rawItems = JSON.parse(parsed.data.tickets_json);
  } catch {
    return {
      kind: "error",
      message: "JSON の解析に失敗しました。形式を確認してください。"
    };
  }
  const itemsParsed = z.array(TicketImportItemSchema).min(1).max(100).safeParse(rawItems);
  if (!itemsParsed.success) {
    return {
      kind: "error",
      message: `ticket データが不正です: ${itemsParsed.error.issues
        .slice(0, 5)
        .map((issue) => `${issue.path.join(".")} ${issue.message}`)
        .join(" / ")}`
    };
  }

  try {
    const result = await importTickets(
      parsed.data.project_id,
      itemsParsed.data,
      dryRun
    );
    if (dryRun) {
      return {
        kind: "preview",
        valid: result.valid,
        inPayloadDuplicateSlugs: result.in_payload_duplicate_slugs,
        existingConflictSlugs: result.existing_conflict_slugs,
        parsedCount: itemsParsed.data.length,
        json: parsed.data.tickets_json
      };
    }
    return {
      kind: "ok",
      message: `${result.imported_count} 件の ticket をインポートしました。`
    };
  } catch (error: unknown) {
    // 422: slug 衝突 (in-payload / 既存) で全体 reject。409: archived / 並行 unique violation。
    if (error instanceof BackendApiError && error.status === 422) {
      return {
        kind: "error",
        message:
          "slug の重複または既存 ticket との衝突によりインポートが拒否されました。先にプレビューで衝突を解消してください。"
      };
    }
    if (error instanceof BackendApiError && error.status === 409) {
      return {
        kind: "error",
        message:
          "プロジェクトがアーカイブされているか、並行操作と競合しました。再読み込みしてから操作してください。"
      };
    }
    const message =
      error instanceof Error ? error.message : "インポートに失敗しました。";
    return { kind: "error", message };
  }
}
