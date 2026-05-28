"use client";

import { useCallback, useEffect, useRef, useState } from "react";

type ConfirmDialogProps = {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  variant?: "danger" | "default";
  onConfirm: () => void | Promise<void>;
  children: (open: () => void) => React.ReactNode;
};

export function ConfirmDialog({
  title,
  message,
  confirmLabel = "確認",
  cancelLabel = "キャンセル",
  variant = "default",
  onConfirm,
  children,
}: ConfirmDialogProps) {
  const [isOpen, setIsOpen] = useState(false);
  const [isPending, setIsPending] = useState(false);
  const dialogRef = useRef<HTMLDialogElement>(null);

  const open = useCallback(() => {
    setIsOpen(true);
  }, []);

  useEffect(() => {
    if (isOpen && dialogRef.current && !dialogRef.current.open) {
      dialogRef.current.showModal();
    }
  }, [isOpen]);

  const close = useCallback(() => {
    setIsOpen(false);
    dialogRef.current?.close();
  }, []);

  const confirm = useCallback(async () => {
    setIsPending(true);
    try {
      await onConfirm();
    } finally {
      setIsPending(false);
      close();
    }
  }, [onConfirm, close]);

  const confirmClass =
    variant === "danger"
      ? "bg-danger text-white hover:bg-danger/90"
      : "bg-accent text-white hover:bg-accent/90";

  return (
    <>
      {children(open)}
      {isOpen && (
        <dialog
          ref={dialogRef}
          className="fixed inset-0 z-50 m-auto rounded-lg border border-line bg-panel p-0 shadow-2xl backdrop:bg-black/40"
          onClose={close}
        >
          <div className="grid gap-4 p-6">
            <h2 className="text-lg font-semibold">{title}</h2>
            <p className="text-sm text-muted-foreground">{message}</p>
            <div className="flex justify-end gap-3">
              <button
                type="button"
                onClick={close}
                disabled={isPending}
                className="rounded-md border border-line px-4 py-2 text-sm font-medium text-muted-foreground hover:bg-slate-50"
              >
                {cancelLabel}
              </button>
              <button
                type="button"
                onClick={confirm}
                disabled={isPending}
                className={`rounded-md px-4 py-2 text-sm font-medium ${confirmClass} disabled:opacity-50`}
              >
                {isPending ? "処理中..." : confirmLabel}
              </button>
            </div>
          </div>
        </dialog>
      )}
    </>
  );
}
