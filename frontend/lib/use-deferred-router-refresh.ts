"use client";

import { useCallback, useEffect, useState } from "react";

/**
 * C-5 root cause workaround (Playwright 実測 + Next.js 既知 regression):
 * Next.js 16 (16.2.6 / 16.2.9 で実測) / React 19 では、Server Action 完了直後の
 * - action 内 `revalidatePath()` (server)
 * - transition 内 / effect 内 / deferred の `router.refresh()` (client)
 * - 同 URL への `router.replace()` (client)
 * が **確率的に commit されない** (RSC GET は飛び応答 200 でも適用されず、表示が古いまま固着。
 * 同一 build で成功 1/3 程度を 3-run × refresh / replace / 16.2.9 の各構成で実測)。
 * 参照: https://github.com/vercel/next.js/discussions/82289 /
 *       https://github.com/vercel/next.js/discussions/88767
 *
 * mutation 後に「ヘッダー / 基本情報 / 上部ボタン / 編集フォームが同じ DB truth に揃う」ことは
 * 本 app の絶対要件 (人間 UX + DOM を SoT として読む AI agent の巻き戻し防止) のため、
 * **唯一 100% 成功を実測できた full reload** に倒す。Next 側の修正後は本 hook の effect を
 * `router.refresh()` へ戻すだけで全 mutation 経路が一括で滑らかな更新に復帰する。
 *
 * 返す `requestRefresh()` は transition 内 (action 結果ハンドラ) から安全に呼べる —
 * setState で次 render に意図を運び、effect (transition 外) が reload を行う。
 */
export function useDeferredRouterRefresh(): () => void {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (tick > 0) {
      window.location.reload();
    }
  }, [tick]);

  return useCallback(() => {
    setTick((current) => current + 1);
  }, []);
}
