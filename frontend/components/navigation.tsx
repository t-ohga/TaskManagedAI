import Link from "next/link";

const navItems = [
  { href: "/dashboard", label: "Dashboard", current: true },
  { href: "/dashboard/tickets", label: "Tickets", current: false },
  { href: "/dashboard/approvals", label: "Approvals", current: false },
  { href: "/dashboard/agent-runs", label: "Agent Runs", current: false },
  { href: "/dashboard/audit", label: "Audit", current: false },
  { href: "/dashboard/settings", label: "Settings", current: false }
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
          <p className="rounded-md border border-line px-2 py-1 font-mono text-xs text-muted">
            {actorLabel}
          </p>
        </div>

        <nav aria-label="Admin">
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
                  href={item.href}
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
                Logout
              </Link>
            </li>
          </ul>
        </nav>
      </div>
    </header>
  );
}

