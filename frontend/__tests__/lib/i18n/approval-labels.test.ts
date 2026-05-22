import { describe, expect, it } from "vitest";

import {
  APPROVAL_ACTION_CLASS_LABELS,
  APPROVAL_STATUS_LABELS,
  formatApprovalActionClass,
  formatApprovalStatus,
  formatRiskLevel,
  RISK_LEVEL_LABELS
} from "@/lib/i18n/approval-labels";

describe("approval i18n labels", () => {
  it("keeps action_class values visible with Japanese labels", () => {
    expect(APPROVAL_ACTION_CLASS_LABELS).toEqual({
      task_write: "タスク更新",
      repo_write: "リポジトリ書込",
      pr_open: "PR 作成",
      secret_access: "Secret 参照",
      merge: "マージ",
      deploy: "デプロイ",
      provider_call: "Provider 呼び出し"
    });
    expect(formatApprovalActionClass("secret_access")).toBe("Secret 参照 (secret_access)");
  });

  it("keeps approval status values visible with Japanese labels", () => {
    expect(APPROVAL_STATUS_LABELS).toEqual({
      pending: "承認待ち",
      approved: "承認済み",
      rejected: "却下済み",
      expired: "期限切れ",
      invalidated: "無効化済み"
    });
    expect(formatApprovalStatus("approved")).toBe("承認済み (approved)");
    expect(formatApprovalStatus("unknown_status")).toBe("unknown_status");
  });

  it("keeps risk level values visible with Japanese labels", () => {
    expect(RISK_LEVEL_LABELS).toEqual({
      low: "低",
      medium: "中",
      high: "高",
      critical: "緊急"
    });
    expect(formatRiskLevel("critical")).toBe("緊急 (critical)");
  });
});
