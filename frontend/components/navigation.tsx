import Link from "next/link";

import { NotificationBadge } from "@/components/notification-badge";
import { NavLink } from "@/components/nav-link";
import { ThemeToggle } from "@/components/theme-toggle";
import { FeatureTourTrigger } from "@/components/feature-tour-trigger";
import { MobileNav } from "@/components/mobile-nav";

const navItems = [
  { href: "/dashboard", label: "ダッシュボード" },
  { href: "/onboarding", label: "導入" },
  { href: "/today", label: "Today" },
  { href: "/timeline", label: "実行ログ" },
  { href: "/tickets", label: "チケット" },
  { href: "/eval-dashboard", label: "評価ダッシュボード" },
  { href: "/approvals", label: "承認待ち" },
  { href: "/runs", label: "AI 実行" },
  { href: "/orchestrator/board", label: "AI 組織" },
  { href: "/webhook-events", label: "Webhook" },
  { href: "/domain-trust", label: "ドメイン信頼度" },
  { href: "/audit", label: "監査ログ" },
  { href: "/settings", label: "設定" },
] as const;

type NavigationProps = {
  actorLabel: string;
};

export function Navigation({ actorLabel }: NavigationProps) {
  return (
    <header className="no-print border-b border-line bg-panel">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="text-base font-semibold tracking-normal outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            href="/dashboard"
          >
            TaskManagedAI
          </Link>
          <div className="flex items-center gap-2">
            <p className="rounded-md border border-line px-2 py-1 font-mono text-xs text-muted-foreground">
              {actorLabel}
            </p>
            <FeatureTourTrigger />
            <ThemeToggle />
            <NotificationBadge />
          </div>
        </div>

        <MobileNav>
        <nav aria-label="管理ナビゲーション">
          <ul className="flex flex-wrap items-center gap-1">
            {navItems.map((item) => (
              <li key={item.href}>
                <NavLink href={item.href} label={item.label} />
              </li>
            ))}
            <li>
              <Link
                className="block rounded-md px-3 py-2 text-sm font-medium text-muted-foreground outline-offset-2 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                href="/login"
              >
                ログアウト
              </Link>
            </li>
          </ul>
        </nav>
        </MobileNav>
      </div>
    </header>
  );
}
