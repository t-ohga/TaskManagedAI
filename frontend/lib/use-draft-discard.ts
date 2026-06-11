"use client";

import { useCallback, useEffect, useRef, type RefObject } from "react";

import { DRAFT_DISCARD_EVENT } from "@/lib/full-reload";

/**
 * R10 (Codex adversarial HIGH): discardDrafts() (lib/full-reload.ts) の DOM reset は
 * React state を正本とする draft を破棄できないため、guard 要素に dispatch される
 * DRAFT_DISCARD_EVENT を受けて **component 自身が state を破棄**するための callback ref。
 *
 * - 返り値を guard 要素の ref に渡す。conditional render (タグ作成 panel / rename 行) でも
 *   mount 時に attach / unmount 時に cleanup される (React 19 callback ref cleanup)。
 * - `mirrorRef` には既存の object ref (except 渡し用、例: createGuardRef) を渡すと同じ要素を
 *   mirror する (1 要素 1 ref 制約の merge)。
 */
export function useDraftDiscardRef<T extends HTMLElement>(
  onDiscard: () => void,
  mirrorRef?: RefObject<T | null>
): (node: T | null) => (() => void) | undefined {
  const callbackRef = useRef(onDiscard);
  useEffect(() => {
    callbackRef.current = onDiscard;
  });
  return useCallback(
    (node: T | null) => {
      if (mirrorRef) mirrorRef.current = node;
      if (!node) return undefined;
      const handler = () => callbackRef.current();
      node.addEventListener(DRAFT_DISCARD_EVENT, handler);
      return () => {
        node.removeEventListener(DRAFT_DISCARD_EVENT, handler);
        if (mirrorRef) mirrorRef.current = null;
      };
    },
    [mirrorRef]
  );
}
