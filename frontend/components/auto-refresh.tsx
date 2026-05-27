"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";

type AutoRefreshProps = {
  intervalMs?: number;
  enabled?: boolean;
};

export function AutoRefresh({ intervalMs = 30000, enabled = true }: AutoRefreshProps) {
  const router = useRouter();

  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => router.refresh(), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled, router]);

  return null;
}
