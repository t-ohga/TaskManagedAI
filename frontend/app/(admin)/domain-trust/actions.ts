"use server";

import { revalidatePath } from "next/cache";

import { BackendApiError } from "@/lib/api/client";
import {
  createDomainTrust,
  deleteDomainTrust,
  updateDomainTrust
} from "@/lib/api/research-advanced";
import { TrustTierEnum } from "@/lib/domain/research-advanced";

/**
 * SP-032 (ADR-00052): domain trust registry の CRUD Server Action (tenant-scoped、owner-gated)。
 *
 * tenant_id は server 側 session で resolve (caller-supplied なし)。owner gate は backend が enforce
 * (非 owner / service / agent は 403)。domain の厳密正規化も backend (normalize_domain)。
 */

const UUID_PATTERN = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type DomainTrustActionState =
  | { kind: "idle" }
  | { kind: "ok"; message: string }
  | { kind: "error"; message: string };

function mapError(error: unknown): string {
  if (error instanceof BackendApiError) {
    switch (error.status) {
      case 400:
        return "ドメインの形式が不正です (scheme / path / port を含めず、ホスト名のみを入力してください)。";
      case 409:
        return "このドメインの信頼設定は既に登録されています。";
      case 404:
        return "対象の信頼設定が見つかりません。";
      case 422:
        return "入力値が不正です。";
      case 403:
        return "この操作を行う権限がありません (オーナーのみ)。";
      default:
        return `操作に失敗しました (${error.status})。`;
    }
  }
  return error instanceof Error ? error.message : "操作に失敗しました。";
}

export async function createDomainTrustAction(
  _prev: DomainTrustActionState,
  formData: FormData
): Promise<DomainTrustActionState> {
  const domain = String(formData.get("domain") ?? "").trim();
  const tierParsed = TrustTierEnum.safeParse(formData.get("trust_tier"));
  const rationaleRaw = String(formData.get("rationale") ?? "").trim();
  if (domain.length === 0 || domain.length > 253) {
    return { kind: "error", message: "ドメインを 1〜253 文字で入力してください。" };
  }
  if (!tierParsed.success) {
    return { kind: "error", message: "信頼度を選択してください。" };
  }
  if (rationaleRaw.length > 1000) {
    return { kind: "error", message: "理由は 1000 文字以内で入力してください。" };
  }
  try {
    await createDomainTrust({
      domain,
      trust_tier: tierParsed.data,
      rationale: rationaleRaw.length > 0 ? rationaleRaw : null
    });
    revalidatePath("/domain-trust");
    return { kind: "ok", message: `ドメイン ${domain} の信頼設定を登録しました。` };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}

export async function updateDomainTrustAction(
  _prev: DomainTrustActionState,
  formData: FormData
): Promise<DomainTrustActionState> {
  const entryId = String(formData.get("entry_id") ?? "");
  const tierParsed = TrustTierEnum.safeParse(formData.get("trust_tier"));
  const rationaleRaw = String(formData.get("rationale") ?? "").trim();
  if (!UUID_PATTERN.test(entryId)) {
    return { kind: "error", message: "不正な ID です。" };
  }
  if (!tierParsed.success) {
    return { kind: "error", message: "信頼度を選択してください。" };
  }
  if (rationaleRaw.length > 1000) {
    return { kind: "error", message: "理由は 1000 文字以内で入力してください。" };
  }
  try {
    await updateDomainTrust(entryId, {
      trust_tier: tierParsed.data,
      rationale: rationaleRaw.length > 0 ? rationaleRaw : null
    });
    revalidatePath("/domain-trust");
    return { kind: "ok", message: "信頼設定を更新しました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}

export async function deleteDomainTrustAction(
  _prev: DomainTrustActionState,
  formData: FormData
): Promise<DomainTrustActionState> {
  const entryId = String(formData.get("entry_id") ?? "");
  if (!UUID_PATTERN.test(entryId)) {
    return { kind: "error", message: "不正な ID です。" };
  }
  try {
    await deleteDomainTrust(entryId);
    revalidatePath("/domain-trust");
    return { kind: "ok", message: "信頼設定を削除しました。" };
  } catch (error) {
    return { kind: "error", message: mapError(error) };
  }
}
