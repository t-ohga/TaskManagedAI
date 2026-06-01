import { cookies } from "next/headers";
import type { ReactNode } from "react";

import { Navigation } from "@/components/navigation";
import { CommandPalette } from "@/components/command-palette";
import { ToastProvider } from "@/components/toast";
import {
  DEV_SESSION_COOKIE_NAME,
  readDevLoginCookieSecret,
  verifyDevSessionCookie
} from "@/lib/auth/dev-login";

export const dynamic = "force-dynamic";

async function readActorLabel(): Promise<string> {
  const cookieStore = await cookies();
  const sessionCookie = cookieStore.get(DEV_SESSION_COOKIE_NAME);

  if (!sessionCookie) {
    return "session pending";
  }

  try {
    const session = await verifyDevSessionCookie(
      sessionCookie.value,
      readDevLoginCookieSecret()
    );
    return session?.actor.actorId ?? "session pending";
  } catch {
    return "session pending";
  }
}

export default async function AdminLayout({ children }: { children: ReactNode }) {
  const actorLabel = await readActorLabel();

  return (
    <div className="min-h-dvh bg-canvas">
      {/* E-1/O-1 (UI 監査 fix): ToastProvider を mount し共通トースト通知を有効化 (これまで orphan だった) */}
      <ToastProvider>
        <Navigation actorLabel={actorLabel} />
        <CommandPalette />
        <main className="mx-auto w-full max-w-6xl px-4 py-6 sm:px-6 lg:px-8">{children}</main>
      </ToastProvider>
    </div>
  );
}

