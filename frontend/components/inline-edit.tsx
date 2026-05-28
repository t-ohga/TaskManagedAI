"use client";

import { useCallback, useRef, useState, useTransition } from "react";

type InlineEditProps = {
  value: string;
  onSave: (value: string) => Promise<void>;
  as?: "h1" | "p" | "span";
  className?: string;
  placeholder?: string;
  multiline?: boolean;
};

export function InlineEdit({
  value,
  onSave,
  as: Tag = "span",
  className = "",
  placeholder = "クリックして編集",
  multiline = false,
}: InlineEditProps) {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value);
  const [isPending, startTransition] = useTransition();
  const inputRef = useRef<HTMLInputElement | HTMLTextAreaElement>(null);

  const startEdit = useCallback(() => {
    setDraft(value);
    setEditing(true);
    setTimeout(() => inputRef.current?.focus(), 0);
  }, [value]);

  const save = useCallback(() => {
    if (draft.trim() === value) {
      setEditing(false);
      return;
    }
    startTransition(async () => {
      await onSave(draft.trim());
      setEditing(false);
    });
  }, [draft, value, onSave]);

  const cancel = useCallback(() => {
    setDraft(value);
    setEditing(false);
  }, [value]);

  if (editing) {
    const sharedProps = {
      ref: inputRef as React.RefObject<HTMLInputElement>,
      value: draft,
      onChange: (e: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => setDraft(e.target.value),
      onBlur: save,
      onKeyDown: (e: React.KeyboardEvent) => {
        if (e.key === "Enter" && !multiline) save();
        if (e.key === "Escape") cancel();
      },
      disabled: isPending,
      className: `w-full rounded border border-accent/40 bg-transparent px-2 py-1 outline-none focus:border-accent ${className}`,
    };

    if (multiline) {
      return <textarea {...sharedProps} ref={inputRef as React.RefObject<HTMLTextAreaElement>} rows={4} />;
    }
    return <input type="text" {...sharedProps} />;
  }

  return (
    <Tag
      onClick={startEdit}
      className={`cursor-pointer rounded px-1 transition-colors hover:bg-accent/5 ${className}`}
      title="ダブルクリックで編集"
      role="button"
      tabIndex={0}
      onKeyDown={(e: React.KeyboardEvent) => { if (e.key === "Enter") startEdit(); }}
    >
      {value || <span className="italic text-muted-foreground">{placeholder}</span>}
    </Tag>
  );
}
