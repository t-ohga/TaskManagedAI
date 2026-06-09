"use client";

import { OPEN_FEATURE_TOUR_EVENT } from "@/components/feature-tour";

/** ナビの「ガイド」ボタン。機能ツアーを手動で再表示する (P-2)。 */
export function FeatureTourTrigger() {
  return (
    <button
      type="button"
      onClick={() => window.dispatchEvent(new Event(OPEN_FEATURE_TOUR_EVENT))}
      className="rounded-md border border-line px-2.5 py-1.5 text-sm font-medium text-muted-foreground hover:bg-canvas hover:text-ink"
      aria-label="機能ツアーを表示"
    >
      ガイド
    </button>
  );
}
