import Link from "next/link";
import type { Route } from "next";

import { NotificationBadge } from "@/components/notification-badge";

const navItems = [
  { href: "/dashboard", label: "ダッシュボード", current: true },
  { href: "/onboarding", label: "導入", current: false },
  { href: "/today", label: "Today", current: false },
  { href: "/timeline", label: "実行ログ", current: false },
  { href: "/tickets", label: "チケット", current: false },
  { href: "/eval-dashboard", label: "評価ダッシュボード", current: false },
  { href: "/approvals", label: "承認待ち", current: false },
  { href: "/runs", label: "AI 実行", current: false },
  { href: "/orchestrator/board", label: "AI 組織", current: false },
  { href: "/audit", label: "監査ログ", current: false },
  { href: "/settings", label: "設定", current: false }
] as const;

type NavigationProps = {
  actorLabel: string;
};

export function Navigation({ actorLabel }: NavigationProps) {
  return (
    <header className="border-b border-line bg-panel">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-4 px-4 py-4 sm:px-6 lg:flex-row lg:items-center lg:justify-between lg:px-8">
        <div className="flex items-center justify-between gap-4">
          <Link
            className="text-base font-semibold tracking-normal outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
            href="/dashboard"
          >
            TaskManagedAI
          </Link>
          <div className="flex items-center gap-2">
            <p className="rounded-md border border-line px-2 py-1 font-mono text-xs text-muted">
              {actorLabel}
            </p>
            <NotificationBadge />
          </div>
        </div>

        <nav aria-label="管理ナビゲーション">
          <ul className="flex flex-wrap items-center gap-1">
            {navItems.map((item) => (
              <li key={item.href}>
                <Link
                  aria-current={item.current ? "page" : undefined}
                  className={
                    item.current
                      ? "block rounded-md bg-teal-50 px-3 py-2 text-sm font-semibold text-accent outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                      : "block rounded-md px-3 py-2 text-sm font-medium text-muted outline-offset-2 hover:bg-slate-50 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                  }
                  href={item.href as Route}
                >
                  {item.label}
                </Link>
              </li>
            ))}
            <li>
              <Link
                className="block rounded-md px-3 py-2 text-sm font-medium text-muted outline-offset-2 hover:bg-slate-50 hover:text-ink focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
                href="/login"
              >
                ログアウト
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}
