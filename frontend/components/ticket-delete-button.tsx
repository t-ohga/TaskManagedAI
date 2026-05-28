"use client";

import { useRouter } from "next/navigation";
import { useCallback, useEffect, useRef, useState, useTransition } from "react";

import { updateTicketAction, type UpdateTicketState } from "@/app/(admin)/tickets/[id]/actions";

type TicketDeleteButtonProps = {
  ticketId: string;
  projectId: string;
};

export function TicketDeleteButton({ ticketId, projectId }: TicketDeleteButtonProps) {
  const router = useRouter();
  const [isPending, startTransition] = useTransition();
  const [isOpen, setIsOpen] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  useEffect(() => {
    if (isOpen && dialogRef.current && !dialogRef.current.open) {
      dialogRef.current.showModal();
    }
  }, [isOpen]);

  const [error, setError] = useState<string | null>(null);

  const handleDelete = useCallback(() => {
    setError(null);
    startTransition(async () => {
      const fd = new FormData();
      fd.set("ticket_id", ticketId);
      fd.set("status", "cancelled");
      const result = await updateTicketAction({ kind: "idle" } as UpdateTicketState, fd);
      if (result.kind === "ok") {
        setIsOpen(false);
        dialogRef.current?.close();
        router.push("/tickets");
      } else if (result.kind === "error") {
        setError(result.message);
      }
    });
  }, [ticketId, router]);

  return (
    <>
      <button
        type="button"
        onClick={() => setIsOpen(true)}
        className="rounded-md border border-danger/30 px-4 py-2 text-center text-sm font-medium text-danger transition-colors hover:bg-red-50"
      >
        チケットを中止
      </button>
      {isOpen && (
        <dialog
          ref={dialogRef}
          className="fixed inset-0 z-50 m-auto rounded-lg border border-line bg-panel p-0 shadow-2xl backdrop:bg-black/40"
          onClose={() => setIsOpen(false)}
        >
          <div className="grid gap-4 p-6">
            <h2 className="text-lg font-semibold">チケットを中止しますか？</h2>
            <p className="text-sm text-muted-foreground">
              チケットのステータスが「中止」に変更されます。この操作は看板から非表示になります。
            </p>
            {error && <p className="text-sm text-danger">{error}</p>}
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={() => { setIsOpen(false); dialogRef.current?.close(); }}
                className="rounded-md border border-line px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-slate-50"
              >
                キャンセル
              </button>
              <button
                type="button"
                onClick={handleDelete}
                disabled={isPending}
                className="rounded-md bg-danger px-4 py-2 text-sm font-medium text-white hover:bg-danger/90 disabled:opacity-50"
              >
                {isPending ? "処理中..." : "中止する"}
              </button>
            </div>
          </div>
        </dialog>
      )}
    </>
  );
}
