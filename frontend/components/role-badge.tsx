const ROLE_CONFIG: Record<string, { color: string; label: string }> = {
  orchestrator: { color: "bg-indigo-100 dark:bg-indigo-900/40 text-indigo-700 dark:text-indigo-300", label: "指揮" },
  dispatcher: { color: "bg-blue-100 dark:bg-blue-900/40 text-blue-700 dark:text-blue-300", label: "配分" },
  implementer: { color: "bg-green-100 dark:bg-green-900/40 text-green-700 dark:text-green-300", label: "実装" },
  reviewer: { color: "bg-amber-100 dark:bg-amber-900/40 text-amber-700 dark:text-amber-300", label: "レビュー" },
  researcher: { color: "bg-purple-100 dark:bg-purple-900/40 text-purple-700 dark:text-purple-300", label: "調査" },
  tester: { color: "bg-cyan-100 dark:bg-cyan-900/40 text-cyan-700 dark:text-cyan-300", label: "テスト" },
  security_agent: { color: "bg-red-100 dark:bg-red-900/40 text-red-700 dark:text-red-300", label: "セキュリティ" },
  repair_specialist: { color: "bg-orange-100 dark:bg-orange-900/40 text-orange-700 dark:text-orange-300", label: "修復" },
  curator: { color: "bg-pink-100 dark:bg-pink-900/40 text-pink-700 dark:text-pink-300", label: "整理" },
  observer: { color: "bg-gray-100 dark:bg-gray-800 text-gray-700 dark:text-gray-300", label: "観察" },
};

export function RoleBadge({ role }: { role: string | null | undefined }) {
  if (!role) return null;
  const config = ROLE_CONFIG[role] ?? { color: "bg-gray-100 dark:bg-gray-800 text-gray-600 dark:text-gray-300", label: role };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${config.color}`}>
      {config.label}
    </span>
  );
}
