"use client";

import { useEffect, useState } from "react";

type ApprovalTimerProps = {
  requestedAt: string;
  timeoutMinutes?: number;
};

export function ApprovalTimer({ requestedAt, timeoutMinutes = 60 }: ApprovalTimerProps) {
  const [remaining, setRemaining] = useState("");
  const [expired, setExpired] = useState(false);

  useEffect(() => {
    function update() {
      const deadline = new Date(requestedAt).getTime() + timeoutMinutes * 60 * 1000;
      const now = Date.now();
      const diff = deadline - now;

      if (diff <= 0) {
        setRemaining("期限切れ");
        setExpired(true);
        return;
      }

      const hours = Math.floor(diff / 3600000);
      const mins = Math.floor((diff % 3600000) / 60000);
      setRemaining(hours > 0 ? `${hours}時間${mins}分` : `${mins}分`);
      setExpired(false);
    }

    update();
    const id = setInterval(update, 60000);
    return () => clearInterval(id);
  }, [requestedAt, timeoutMinutes]);

  return (
    <span className={`text-xs font-medium ${expired ? "text-danger" : "text-muted-foreground"}`}>
      {expired ? "⚠ " : "⏱ "}{remaining}
    </span>
  );
}
