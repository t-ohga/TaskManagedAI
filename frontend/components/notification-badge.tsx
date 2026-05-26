import Link from "next/link";

import { getBadgeCount } from "@/lib/api/notifications";

export async function NotificationBadge() {
  let count = 0;

  try {
    const result = await getBadgeCount();
    count = result.unread_count;
  } catch {
    count = 0;
  }

  return (
    <Link
      href="/notifications"
      className="relative inline-flex items-center gap-2 rounded-md px-3 py-1 text-sm font-semibold text-muted hover:text-foreground"
      data-testid="notification-badge-link"
    >
      <span aria-hidden="true">🔔</span>
      <span className="sr-only">Notifications</span>
      {count > 0 ? (
        <span
          className="absolute -right-1 -top-1 inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-rose-600 px-1 text-xs font-bold text-white"
          data-testid="notification-unread-count"
        >
          {count > 99 ? "99+" : count}
        </span>
      ) : null}
    </Link>
  );
}

