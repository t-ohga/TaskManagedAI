import { listNotifications } from "@/lib/api/notifications";

import { NotificationListItem } from "./_components/notification-list-item";

export const dynamic = "force-dynamic";

export default async function NotificationsPage() {
  const notifications = await listNotifications();

  return (
    <section aria-label="Notifications" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Notifications</h1>
      </header>

      {notifications.length === 0 ? (
        <p className="rounded-md bg-emerald-50 p-3 text-sm text-emerald-700">
          No notifications.
        </p>
      ) : (
        <ul className="grid gap-3" data-testid="notification-list">
          {notifications.map((notification) => (
            <NotificationListItem key={notification.id} notification={notification} />
          ))}
        </ul>
      )}
    </section>
  );
}

