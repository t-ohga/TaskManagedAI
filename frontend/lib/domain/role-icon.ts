export const STANDARD_ROLE_IDS = [
  "orchestrator",
  "implementer",
  "reviewer",
  "tester",
  "security_agent",
  "researcher",
  "observer",
  "curator",
  "dispatcher",
  "repair_specialist"
] as const;

export type RoleId = (typeof STANDARD_ROLE_IDS)[number];

export type RoleGroup = "coordination" | "delivery" | "assurance" | "knowledge";

export type RoleVisual = {
  id: RoleId | "unknown";
  rawId: string;
  label: string;
  icon: string;
  group: RoleGroup;
  description: string;
  standard: boolean;
};

export const ROLE_GROUP_LABELS: Record<RoleGroup, string> = {
  coordination: "統制",
  delivery: "実行",
  assurance: "品質",
  knowledge: "知識"
};

const ROLE_VISUALS: Record<RoleId, RoleVisual> = {
  orchestrator: {
    id: "orchestrator",
    rawId: "orchestrator",
    label: "司令塔",
    icon: "🧭",
    group: "coordination",
    description: "実行順序、依存関係、全体進行を監督します。",
    standard: true
  },
  implementer: {
    id: "implementer",
    rawId: "implementer",
    label: "実装",
    icon: "🛠️",
    group: "delivery",
    description: "承認済みタスクを実装成果物へ落とし込みます。",
    standard: true
  },
  reviewer: {
    id: "reviewer",
    rawId: "reviewer",
    label: "レビュー",
    icon: "🔎",
    group: "assurance",
    description: "差分、設計、テスト不足、回帰リスクを確認します。",
    standard: true
  },
  tester: {
    id: "tester",
    rawId: "tester",
    label: "テスト",
    icon: "✅",
    group: "assurance",
    description: "振る舞いの確認と regression fixture を担当します。",
    standard: true
  },
  security_agent: {
    id: "security_agent",
    rawId: "security_agent",
    label: "セキュリティ",
    icon: "🛡️",
    group: "assurance",
    description: "境界、秘密情報、最小権限、監査性を確認します。",
    standard: true
  },
  researcher: {
    id: "researcher",
    rawId: "researcher",
    label: "調査",
    icon: "📚",
    group: "knowledge",
    description: "背景情報、証拠、外部仕様を収集します。",
    standard: true
  },
  observer: {
    id: "observer",
    rawId: "observer",
    label: "観測",
    icon: "📡",
    group: "knowledge",
    description: "進行ログ、状態変化、異常兆候を観測します。",
    standard: true
  },
  curator: {
    id: "curator",
    rawId: "curator",
    label: "整理",
    icon: "🗂️",
    group: "knowledge",
    description: "証跡、判断、handoff を再利用しやすく整理します。",
    standard: true
  },
  dispatcher: {
    id: "dispatcher",
    rawId: "dispatcher",
    label: "割り振り",
    icon: "📮",
    group: "coordination",
    description: "タスクの配送、再試行、担当分配を扱います。",
    standard: true
  },
  repair_specialist: {
    id: "repair_specialist",
    rawId: "repair_specialist",
    label: "修復",
    icon: "🧯",
    group: "delivery",
    description: "失敗した実行や検証結果から修正案を作ります。",
    standard: true
  }
};

export function isStandardRoleId(value: string | null | undefined): value is RoleId {
  return STANDARD_ROLE_IDS.includes(value as RoleId);
}

export function getRoleVisual(value: string | null | undefined): RoleVisual {
  if (isStandardRoleId(value)) {
    return ROLE_VISUALS[value];
  }

  return {
    id: "unknown",
    rawId: value && value.trim().length > 0 ? value : "unassigned",
    label: "未分類",
    icon: "□",
    group: "knowledge",
    description: "standard role catalog に存在しない role_id です。",
    standard: false
  };
}

export function listRoleVisuals(): RoleVisual[] {
  return STANDARD_ROLE_IDS.map((roleId) => ROLE_VISUALS[roleId]);
}
