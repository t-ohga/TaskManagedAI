const ROLE_CONFIG: Record<string, { color: string; label: string }> = {
  orchestrator: { color: "bg-indigo-100 text-indigo-700", label: "指揮" },
  dispatcher: { color: "bg-blue-100 text-blue-700", label: "配分" },
  implementer: { color: "bg-green-100 text-green-700", label: "実装" },
  reviewer: { color: "bg-amber-100 text-amber-700", label: "レビュー" },
  researcher: { color: "bg-purple-100 text-purple-700", label: "調査" },
  tester: { color: "bg-cyan-100 text-cyan-700", label: "テスト" },
  security_agent: { color: "bg-red-100 text-red-700", label: "セキュリティ" },
  repair_specialist: { color: "bg-orange-100 text-orange-700", label: "修復" },
  curator: { color: "bg-pink-100 text-pink-700", label: "整理" },
  observer: { color: "bg-gray-100 text-gray-700", label: "観察" },
};

export function RoleBadge({ role }: { role: string | null | undefined }) {
  if (!role) return null;
  const config = ROLE_CONFIG[role] ?? { color: "bg-gray-100 text-gray-600", label: role };
  return (
    <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${config.color}`}>
      {config.label}
    </span>
  );
}
