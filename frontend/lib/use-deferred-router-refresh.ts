"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

/**
 * C-5 root cause workaround (Playwright 実測 + Next.js 既知 regression):
 * Next.js 16 / React 19 では、Server Action の transition 内で `revalidatePath()` (server) や
 * `router.refresh()` (client) を実行すると、RSC 適用は成功するのに **transition の isPending が
 * 永遠に解除されない** (POST は 200 / body 完結済でも UI が「更新中...」で固着する)。
 * 参照: https://github.com/vercel/next.js/discussions/82289 /
 *       https://github.com/vercel/next.js/discussions/88767
 *
 * 本 hook は「transition の外で router.refresh() を実行する」ための deferral を提供する。
 * 返す `requestRefresh()` は transition 内 (action 結果ハンドラ) から安全に呼べる —
 * setState で次 render に意図を運び、effect (transition 外) が実際の refresh を行う。
 * 対象 page は全て force-dynamic のため、refresh は常に最新 server state を取得する。
 */
export function useDeferredRouterRefresh(): () => void {
  const router = useRouter();
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (tick > 0) {
      router.refresh();
    }
  }, [tick, router]);

  return useCallback(() => {
    setTick((current) => current + 1);
  }, []);
}
