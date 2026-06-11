"use client";

import { useCallback, useState } from "react";

import { ApprovalDecideForm } from "./approval-decide-form";
import { ApprovalRevisionRequestForm } from "./approval-revision-request-form";

type ApprovalPendingActionsProps = {
  approvalId: string;
  initialStatus: string;
};

/**
 * Codex auto-review P2: 判定 form と修正依頼 form は同一 pending approval に対する sibling。
 * 片方が terminal mutation (判定 / 修正依頼) に成功すると approval は approved/rejected/invalidated
 * へ動くため、もう片方も即座に無効化しないと、stale UI から二度目の terminal action を発行して
 * 回避可能な conflict を踏む。共有の terminal state を親で保持し、両 form へ配る。
 *
 * full reload が成功すれば page 自体が status != "pending" で両 form を unmount するが、
 * reload が別 draft の破棄確認でキャンセルされた場合でも、この共有 state で sibling が無効化される。
 */
export function ApprovalPendingActions({ approvalId, initialStatus }: ApprovalPendingActionsProps) {
  const [terminal, setTerminal] = useState(false);
  const markTerminal = useCallback(() => setTerminal(true), []);

  return (
    <div className="no-print grid gap-4">
      <ApprovalDecideForm
        approvalId={approvalId}
        initialStatus={initialStatus}
        siblingTerminal={terminal}
        onTerminal={markTerminal}
      />
      <ApprovalRevisionRequestForm
        approvalId={approvalId}
        initialStatus={initialStatus}
        siblingTerminal={terminal}
        onTerminal={markTerminal}
      />
    </div>
  );
}
