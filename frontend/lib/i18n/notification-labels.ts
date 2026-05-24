import type {
  NotificationRequiredAction,
  NotificationSeverity,
  NotificationTriageState
} from "@/lib/api/notifications";

export function formatNotificationSeverity(severity: NotificationSeverity): string {
  switch (severity) {
    case "critical":
      return "重大";
    case "high":
      return "高";
    case "medium":
      return "中";
    case "low":
      return "低";
    case "info":
      return "情報";
  }
}

export function formatNotificationRequiredAction(action: NotificationRequiredAction): string {
  switch (action) {
    case "review_approval":
      return "承認確認";
    case "inspect_run":
      return "実行確認";
    case "resolve_blocker":
      return "ブロッカー解消";
    case "external_followup":
      return "外部確認";
    case "acknowledge":
      return "確認";
  }
}

export function formatNotificationTriageState(state: NotificationTriageState): string {
  switch (state) {
    case "open":
      return "未解決";
    case "snoozed":
      return "スヌーズ中";
    case "resolved":
      return "解決済み";
    case "all":
      return "すべて";
  }
}
