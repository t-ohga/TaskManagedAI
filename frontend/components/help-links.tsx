const HELP_ITEMS = [
  { label: "チケット管理", href: "/tickets", desc: "看板ボードでチケットを管理" },
  { label: "AI 実行", href: "/runs", desc: "AI エージェントの実行状況を確認" },
  { label: "承認ワークフロー", href: "/approvals", desc: "承認待ちの項目をレビュー" },
  { label: "監査ログ", href: "/audit", desc: "全操作の監査証跡を確認" },
  { label: "評価ダッシュボード", href: "/eval-dashboard", desc: "Hard Gates と KPI の達成状況" },
  { label: "設定", href: "/settings", desc: "プロバイダー準拠マトリクスとポリシー" },
];

export function HelpLinks() {
  return (
    <div className="grid gap-2 sm:grid-cols-2">
      {HELP_ITEMS.map((item) => (
        <a
          key={item.href}
          href={item.href}
          className="rounded-lg border border-line bg-panel p-3 transition-all hover:border-accent/40 hover:shadow-sm"
        >
          <p className="text-sm font-medium">{item.label}</p>
          <p className="mt-0.5 text-xs text-muted-foreground">{item.desc}</p>
        </a>
      ))}
    </div>
  );
}
