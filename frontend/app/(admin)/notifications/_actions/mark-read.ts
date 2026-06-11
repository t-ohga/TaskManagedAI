"use server";

import { markNotificationRead } from "@/lib/api/notifications";

export async function markNotificationReadAction(formData: FormData) {
  const id = formData.get("notification_id");
  if (typeof id !== "string") {
    return;
  }

  await markNotificationRead(id);
  // C-5 系統適用: Server Action 内 revalidatePath() は client transition の isPending を解除せず
  // 確率的に未 commit になる Next.js 16 (16.2.6) + React 19 regression。撤去し、表示更新は
  // 呼び出し側の full reload (useDeferredRouterRefresh) に委譲する。navbar 通知バッジは
  // full reload の layout 再取得で更新される (撤去前: revalidatePath("/notifications") +
  // revalidatePath("/", "layout"))。参照: vercel/next.js discussions #82289 / #88767。
  // Next 修正後は呼び出し側 hook を router.refresh() へ戻すだけで復帰する。
}

