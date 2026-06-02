"use client";

import { useLayoutEffect, useRef, useState } from "react";

import { MarkdownRenderer } from "@/components/markdown-renderer";

// G-4: ツールバー付き Markdown editor (新規依存なし)。textarea + 書式挿入ボタン + 編集/プレビュー
// タブ。プレビューは既存 MarkdownRenderer (DOMPurify allowlist sanitize 済) を再利用するため XSS
// 境界は J-4 と一貫。toolbar は renderer が描画できる syntax のみ (太字/斜体/見出し/箇条書き/
// 番号付き/インラインコード)。link は renderer の href サポート (follow-up) まで提供しない。
//
// controlled (value + onValueChange、comment-form の reset 用) / uncontrolled (defaultValue +
// name、FormData 用) の両対応。textarea は常に DOM に残し name を保持するため、プレビュー中の
// submit でもフィールドが欠落しない。

type MarkdownEditorProps = {
  name?: string;
  defaultValue?: string;
  value?: string;
  onValueChange?: (value: string) => void;
  placeholder?: string;
  rows?: number;
  id?: string;
  ariaLabel?: string;
  textareaClassName?: string;
};

type ToolbarAction =
  | { kind: "wrap"; label: string; title: string; before: string; after: string; placeholder: string }
  | { kind: "linePrefix"; label: string; title: string; prefix: string };

const TOOLBAR: ToolbarAction[] = [
  { kind: "wrap", label: "B", title: "太字", before: "**", after: "**", placeholder: "太字" },
  { kind: "wrap", label: "I", title: "斜体", before: "*", after: "*", placeholder: "斜体" },
  { kind: "linePrefix", label: "H", title: "見出し", prefix: "## " },
  { kind: "linePrefix", label: "•", title: "箇条書き", prefix: "- " },
  { kind: "linePrefix", label: "1.", title: "番号付きリスト", prefix: "1. " },
  { kind: "wrap", label: "</>", title: "インラインコード", before: "`", after: "`", placeholder: "code" }
];

export function MarkdownEditor({
  name,
  defaultValue,
  value,
  onValueChange,
  placeholder,
  rows = 5,
  id,
  ariaLabel,
  textareaClassName
}: MarkdownEditorProps) {
  const isControlled = value !== undefined;
  const [internal, setInternal] = useState(defaultValue ?? "");
  const current = isControlled ? value : internal;

  const [tab, setTab] = useState<"edit" | "preview">("edit");
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  // 書式挿入後に復元したい selection。render 後 (value 反映後) に useLayoutEffect で適用する。
  const pendingSelection = useRef<[number, number] | null>(null);

  useLayoutEffect(() => {
    if (pendingSelection.current && textareaRef.current) {
      const [start, end] = pendingSelection.current;
      textareaRef.current.focus();
      textareaRef.current.setSelectionRange(start, end);
      pendingSelection.current = null;
    }
  });

  function setCurrent(next: string): void {
    if (isControlled) {
      onValueChange?.(next);
    } else {
      setInternal(next);
    }
  }

  function applyWrap(before: string, after: string, ph: string): void {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    const selected = current.slice(start, end);
    const inner = selected || ph;
    const next = current.slice(0, start) + before + inner + after + current.slice(end);
    pendingSelection.current = [start + before.length, start + before.length + inner.length];
    setCurrent(next);
  }

  function applyLinePrefix(prefix: string): void {
    const ta = textareaRef.current;
    if (!ta) return;
    const start = ta.selectionStart;
    const end = ta.selectionEnd;
    // 選択範囲が跨ぐ全行の行頭に prefix を付与する (adversarial R1: 複数行選択で list/heading が
    // 1 行だけになり renderer 上で no-op 化するのを防ぐ)。
    const firstLineStart = current.lastIndexOf("\n", start - 1) + 1;
    // 選択末尾を含む行まで対象にする (selectionEnd が改行直後の場合は前行までに留める)。
    const selEnd = end > start ? end - 1 : end;
    const before = current.slice(0, firstLineStart);
    const region = current.slice(firstLineStart, current.indexOf("\n", selEnd) === -1
      ? current.length
      : current.indexOf("\n", selEnd));
    const after = current.slice(firstLineStart + region.length);
    const prefixedRegion = region
      .split("\n")
      .map((line) => prefix + line)
      .join("\n");
    const next = before + prefixedRegion + after;
    const addedTotal = prefixedRegion.length - region.length;
    pendingSelection.current = [start + prefix.length, end + addedTotal];
    setCurrent(next);
  }

  function onToolbarClick(action: ToolbarAction): void {
    if (action.kind === "wrap") {
      applyWrap(action.before, action.after, action.placeholder);
    } else {
      applyLinePrefix(action.prefix);
    }
  }

  return (
    <div className="grid gap-2">
      <div className="flex items-center justify-between gap-2">
        <div role="toolbar" aria-label="Markdown 書式" className="flex flex-wrap gap-1">
          {TOOLBAR.map((action) => (
            <button
              key={action.title}
              type="button"
              title={action.title}
              aria-label={action.title}
              // 編集タブのときのみ操作可能 (プレビュー中は書式挿入不可)。
              disabled={tab !== "edit"}
              onClick={() => onToolbarClick(action)}
              className="rounded border border-line px-2 py-1 text-xs font-medium text-muted-foreground transition-colors hover:bg-slate-50 disabled:opacity-40"
            >
              {action.label}
            </button>
          ))}
        </div>
        <div className="flex gap-1 text-xs">
          <button
            type="button"
            aria-pressed={tab === "edit"}
            onClick={() => setTab("edit")}
            className={`rounded px-2 py-1 font-medium transition-colors ${
              tab === "edit" ? "bg-accent/10 text-accent" : "text-muted-foreground hover:bg-slate-50"
            }`}
          >
            編集
          </button>
          <button
            type="button"
            aria-pressed={tab === "preview"}
            onClick={() => setTab("preview")}
            className={`rounded px-2 py-1 font-medium transition-colors ${
              tab === "preview" ? "bg-accent/10 text-accent" : "text-muted-foreground hover:bg-slate-50"
            }`}
          >
            プレビュー
          </button>
        </div>
      </div>

      {/* textarea は常に DOM に残し name を保持する (プレビュー中の submit でも値が欠落しない)。 */}
      <textarea
        ref={textareaRef}
        id={id}
        name={name}
        rows={rows}
        value={current}
        onChange={(event) => setCurrent(event.target.value)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        className={`${tab === "edit" ? "" : "hidden"} ${
          textareaClassName ??
          "min-h-28 w-full resize-y rounded-md border border-line bg-white px-3 py-2 text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
        }`}
      />

      {tab === "preview" ? (
        <div className="min-h-28 rounded-md border border-line bg-white px-3 py-2">
          {current.trim() ? (
            <MarkdownRenderer content={current} />
          ) : (
            <p className="text-sm text-muted-foreground">プレビューする内容がありません。</p>
          )}
        </div>
      ) : null}

      <p className="text-[10px] text-muted-foreground">
        Markdown 対応 (太字 **、斜体 *、見出し #、箇条書き -、番号付き 1.、コード `)
      </p>
    </div>
  );
}
