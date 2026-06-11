"use client";

import { confirmDiscardUnsavedDrafts } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";
import { useRef, useState, useTransition } from "react";

import {
  attachTagAction,
  createTagAndAttachAction,
  deleteTagAction,
  detachTagAction,
  renameTagAction,
  type TagActionState
} from "@/app/(admin)/tickets/[id]/tag-actions";
import { TagChip } from "@/components/tag-chip";
import { TAG_COLORS, type TagColor, type TagRead } from "@/lib/domain/tag";

/**
 * ADR-00044 (A-5): ticket 詳細でのタグ操作 UI。
 *
 * - 付与中タグの表示 + 除去 (detach)
 * - project の未付与タグを付与 (attach)
 * - 新規タグ作成 + 付与 (create + attach)
 * - 既存タグの編集 (rename / recolor) と削除 (delete) — project label の管理
 *
 * mutation は Server Action 経由 (project_id は server-owned)。楽観更新は持たず、成功後
 * router.refresh() で canonical state を再取得する (タグは件数が少なく refresh コストが低い)。
 */

type Props = {
  ticketId: string;
  currentTags: TagRead[];
  allTags: TagRead[];
};

const IDLE: TagActionState = { kind: "idle" };

const COLOR_SWATCH: Record<TagColor, string> = {
  slate: "bg-slate-400",
  red: "bg-red-400",
  orange: "bg-orange-400",
  amber: "bg-amber-400",
  green: "bg-green-400",
  teal: "bg-teal-400",
  blue: "bg-blue-400",
  purple: "bg-purple-400",
  pink: "bg-pink-400"
};

function ColorPicker({
  value,
  onChange,
  disabled
}: {
  value: TagColor;
  onChange: (color: TagColor) => void;
  disabled: boolean;
}) {
  return (
    <div className="flex flex-wrap gap-1" role="radiogroup" aria-label="タグの色">
      {TAG_COLORS.map((color) => (
        <button
          key={color}
          type="button"
          role="radio"
          aria-checked={value === color}
          aria-label={color}
          disabled={disabled}
          onClick={() => onChange(color)}
          className={`h-5 w-5 rounded-full ${COLOR_SWATCH[color]} transition ${
            value === color ? "ring-2 ring-offset-1 ring-accent" : "opacity-60 hover:opacity-100"
          } ${disabled ? "cursor-not-allowed" : "cursor-pointer"}`}
        />
      ))}
    </div>
  );
}

export function TicketTagManager({ ticketId, currentTags, allTags }: Props) {
  const requestRefresh = useDeferredRouterRefresh();
  const [isPending, startTransition] = useTransition();
  // R6 (Codex adversarial HIGH): guard は create / rename を**個別領域**にする。root 全体を
  // except すると attach/detach が同 panel 内の別 draft (新規タグ名 / rename 中) を gate なしで
  // 破棄できるため、except は「その draft を実際に consume する操作」だけに渡す。
  const createGuardRef = useRef<HTMLDivElement | null>(null);
  const renameGuardRef = useRef<HTMLDivElement | null>(null);
  const [error, setError] = useState<string | null>(null);

  const [creating, setCreating] = useState(false);
  const [newName, setNewName] = useState("");
  const [newColor, setNewColor] = useState<TagColor>("slate");

  const [editingId, setEditingId] = useState<string | null>(null);
  const [editName, setEditName] = useState("");
  const [editColor, setEditColor] = useState<TagColor>("slate");

  // R10 (Codex adversarial HIGH): create / rename の data-dirty は newName / editingId state 由来。
  // discardDrafts() の DOM 操作だけでは次 render で draft が復活するため、discard event で
  // state を正本ごと破棄する (mirrorRef で既存の except 用 object ref を維持)。
  const createDiscardRef = useDraftDiscardRef<HTMLDivElement>(() => {
    setNewName("");
    setNewColor("slate");
  }, createGuardRef);
  const renameDiscardRef = useDraftDiscardRef<HTMLDivElement>(() => {
    setEditingId(null);
    setEditName("");
  }, renameGuardRef);

  const currentIds = new Set(currentTags.map((t) => t.id));
  const available = allTags.filter((t) => !currentIds.has(t.id));

  function run(
    action: (s: TagActionState, fd: FormData) => Promise<TagActionState>,
    fd: FormData,
    onOk?: () => void,
    // R6: その操作が consume する draft 領域のみ except (attach/detach は null = 全 draft 対象)。
    except: Element | null = null
  ) {
    // R2 (Codex adversarial HIGH): 未保存編集の破棄確認は mutation **前**。キャンセルなら
    // server action を実行しない (post-commit 確認だと stale form 保存で commit を巻き戻せる)。
    if (!confirmDiscardUnsavedDrafts(except)) return;
    setError(null);
    startTransition(async () => {
      const result = await action(IDLE, fd);
      if (result.kind === "error") {
        setError(result.message);
      } else {
        onOk?.();
      // C-5 workaround: transition 内の router.refresh() は isPending を固める (lib/use-deferred-router-refresh.ts 参照)。
        requestRefresh();
      }
    });
  }

  function buildForm(entries: Record<string, string>): FormData {
    const fd = new FormData();
    for (const [key, value] of Object.entries(entries)) fd.set(key, value);
    return fd;
  }

  function handleAttach(tagId: string) {
    run(attachTagAction, buildForm({ ticket_id: ticketId, tag_id: tagId }));
  }

  function handleDetach(tagId: string) {
    run(detachTagAction, buildForm({ ticket_id: ticketId, tag_id: tagId }));
  }

  function handleCreate() {
    if (newName.trim().length === 0) {
      setError("タグ名を入力してください。");
      return;
    }
    run(
      createTagAndAttachAction,
      buildForm({ ticket_id: ticketId, name: newName.trim(), color: newColor }),
      () => {
        setNewName("");
        setNewColor("slate");
        setCreating(false);
      },
      // R6: 作成操作は新規タグ draft を consume する — create 領域のみ except。
      createGuardRef.current
    );
  }

  function startEdit(tag: TagRead) {
    setEditingId(tag.id);
    setEditName(tag.name);
    setEditColor(tag.color);
    setError(null);
  }

  function handleRename() {
    if (editingId === null || editName.trim().length === 0) {
      setError("タグ名を入力してください。");
      return;
    }
    run(
      renameTagAction,
      buildForm({
        ticket_id: ticketId,
        tag_id: editingId,
        name: editName.trim(),
        color: editColor
      }),
      () => setEditingId(null),
      // R6: rename 確定は rename draft を consume する — rename 領域のみ except。
      renameGuardRef.current
    );
  }

  function handleDelete(tagId: string) {
    // R6: 削除は rename 編集 UI 内から行う操作 (編集中タグの削除) — rename 領域のみ except。
    run(
      deleteTagAction,
      buildForm({ ticket_id: ticketId, tag_id: tagId }),
      () => setEditingId(null),
      renameGuardRef.current
    );
  }

  return (
    <div className="grid gap-4">
      {/* 付与中のタグ */}
      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">付与中</p>
        <div className="flex flex-wrap items-center gap-2">
          {currentTags.length === 0 ? (
            <p className="text-sm text-muted-foreground">タグはまだありません</p>
          ) : (
            currentTags.map((tag) => (
              <span key={tag.id} className="inline-flex items-center gap-0.5">
                <TagChip name={tag.name} color={tag.color} />
                <button
                  type="button"
                  disabled={isPending}
                  onClick={() => handleDetach(tag.id)}
                  aria-label={`タグ「${tag.name}」をこのチケットから外す`}
                  className="rounded-full px-1 text-xs text-muted-foreground hover:text-red-600 dark:hover:text-red-400 disabled:opacity-40"
                >
                  ×
                </button>
              </span>
            ))
          )}
        </div>
      </div>

      {/* 未付与のタグを付与 */}
      {available.length > 0 ? (
        <div>
          <p className="mb-2 text-xs font-medium text-muted-foreground">追加</p>
          <div className="flex flex-wrap items-center gap-2">
            {available.map((tag) => (
              <button
                key={tag.id}
                type="button"
                disabled={isPending}
                onClick={() => handleAttach(tag.id)}
                aria-label={`タグ「${tag.name}」をこのチケットに付与する`}
                className="rounded-full transition hover:opacity-100 disabled:opacity-40"
              >
                <TagChip name={`+ ${tag.name}`} color={tag.color} className="opacity-70" />
              </button>
            ))}
          </div>
        </div>
      ) : null}

      {/* 新規作成 */}
      <div>
        {creating ? (
          <div
            ref={createDiscardRef}
            className="grid gap-2 rounded-md border border-line p-3"
            // R6: 新規タグ draft の guard 領域 (作成操作のみ except)。
            data-unsaved-guard=""
            data-dirty={newName.trim() ? "true" : undefined}
          >
            <input
              type="text"
              value={newName}
              maxLength={50}
              placeholder="タグ名 (1〜50 文字)"
              disabled={isPending}
              onChange={(e) => setNewName(e.target.value)}
              className="rounded border border-line px-2 py-1 text-sm"
              aria-label="新しいタグ名"
            />
            <ColorPicker value={newColor} onChange={setNewColor} disabled={isPending} />
            <div className="flex items-center gap-2">
              <span className="text-xs text-muted-foreground">プレビュー:</span>
              <TagChip name={newName.trim() || "タグ名"} color={newColor} />
            </div>
            <div className="flex gap-2">
              <button
                type="button"
                disabled={isPending}
                onClick={handleCreate}
                className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
              >
                作成して付与
              </button>
              <button
                type="button"
                disabled={isPending}
                onClick={() => {
                  setCreating(false);
                  setNewName("");
                  setError(null);
                }}
                className="rounded-md border border-line px-3 py-1 text-xs"
              >
                キャンセル
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            disabled={isPending}
            onClick={() => setCreating(true)}
            className="rounded-md border border-dashed border-line px-3 py-1 text-xs text-muted-foreground hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-40"
          >
            + 新しいタグを作成
          </button>
        )}
      </div>

      {/* 既存タグの編集 / 削除 (project label 管理) */}
      {allTags.length > 0 ? (
        <details className="rounded-md border border-line">
          <summary className="cursor-pointer px-3 py-2 text-xs font-medium text-muted-foreground">
            タグを管理 (名前・色の変更 / 削除)
          </summary>
          <div className="grid gap-2 border-t border-line p-3">
            {allTags.map((tag) =>
              editingId === tag.id ? (
                <div
                  key={tag.id}
                  ref={renameDiscardRef}
                  className="grid gap-2 rounded border border-line p-2"
                  // R6: rename draft の guard 領域 (rename 確定 / 編集中タグの削除のみ except)。
                  data-unsaved-guard=""
                  data-dirty="true"
                >
                  <input
                    type="text"
                    value={editName}
                    maxLength={50}
                    disabled={isPending}
                    onChange={(e) => setEditName(e.target.value)}
                    className="rounded border border-line px-2 py-1 text-sm"
                    aria-label={`タグ「${tag.name}」の新しい名前`}
                  />
                  <ColorPicker value={editColor} onChange={setEditColor} disabled={isPending} />
                  <div className="flex flex-wrap gap-2">
                    <button
                      type="button"
                      disabled={isPending}
                      onClick={handleRename}
                      className="rounded-md bg-accent px-3 py-1 text-xs font-medium text-white disabled:opacity-40"
                    >
                      保存
                    </button>
                    <button
                      type="button"
                      disabled={isPending}
                      onClick={() => setEditingId(null)}
                      className="rounded-md border border-line px-3 py-1 text-xs"
                    >
                      キャンセル
                    </button>
                    <button
                      type="button"
                      disabled={isPending}
                      onClick={() => handleDelete(tag.id)}
                      className="ml-auto rounded-md border border-red-200 dark:border-red-800 px-3 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/40 disabled:opacity-40"
                    >
                      削除
                    </button>
                  </div>
                </div>
              ) : (
                <div key={tag.id} className="flex items-center gap-2">
                  <TagChip name={tag.name} color={tag.color} />
                  <button
                    type="button"
                    disabled={isPending}
                    onClick={() => startEdit(tag)}
                    className="ml-auto rounded border border-line px-2 py-0.5 text-xs text-muted-foreground hover:bg-slate-50 dark:hover:bg-slate-800 disabled:opacity-40"
                  >
                    編集
                  </button>
                </div>
              )
            )}
            <p className="text-xs text-muted-foreground">
              使用中 (アクティブなチケットに付与) のタグは削除できません。先に各チケットから外してください。
            </p>
          </div>
        </details>
      ) : null}

      <div aria-live="polite">
        {error ? <p className="text-xs text-red-600 dark:text-red-400">{error}</p> : null}
        {isPending ? <p className="text-xs text-muted-foreground">更新中...</p> : null}
      </div>
    </div>
  );
}
