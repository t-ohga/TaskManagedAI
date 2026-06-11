"use client";

import { useActionState, useRef, useState, type RefObject } from "react";

import { noop, prepareDiscardOnCommit } from "@/lib/full-reload";
import { useDeferredRouterRefresh } from "@/lib/use-deferred-router-refresh";
import { useDraftDiscardRef } from "@/lib/use-draft-discard";

import {
  archiveProjectAction,
  bulkSoftDeleteAction,
  importTicketsAction,
  restoreBatchAction,
  type ImportActionState,
  type SettingsActionState
} from "../actions";

type DataManagementPanelProps = {
  projectId: string;
  status: string;
  activeTicketCount: number;
};

const INITIAL_STATE: SettingsActionState = { kind: "idle" };
const INITIAL_IMPORT_STATE: ImportActionState = { kind: "idle" };

function StatusMessage({ state }: { state: SettingsActionState }) {
  if (state.kind === "error") {
    return (
      <p role="status" className="rounded-md bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-700 dark:text-rose-300">
        {state.message}
      </p>
    );
  }
  if (state.kind === "ok") {
    return (
      <p role="status" className="rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-700 dark:text-emerald-300">
        {state.message}
      </p>
    );
  }
  return null;
}

function StatusBadge({ status }: { status: string }) {
  const archived = status === "archived";
  return (
    <span
      className={
        archived
          ? "inline-flex items-center rounded-full bg-amber-100 dark:bg-amber-900/40 px-2.5 py-0.5 text-xs font-semibold text-amber-800 dark:text-amber-300"
          : "inline-flex items-center rounded-full bg-emerald-100 dark:bg-emerald-900/40 px-2.5 py-0.5 text-xs font-semibold text-emerald-800 dark:text-emerald-300"
      }
    >
      {archived ? "アーカイブ済み" : "アクティブ"}
    </span>
  );
}

export function DataManagementPanel({
  projectId,
  status,
  activeTicketCount
}: DataManagementPanelProps) {
  // C-5: action 側 revalidatePath 撤去のため表示更新は client full reload。requestRefresh は安定参照 (F-005)。
  const requestRefresh = useDeferredRouterRefresh();
  const archived = status === "archived";

  const [archiveConfirming, setArchiveConfirming] = useState(false);
  const [deleteConfirming, setDeleteConfirming] = useState(false);
  const [importJson, setImportJson] = useState("");
  // C-5: full reload で失われ得る入力 (import JSON / 復元バッチ ID) を draft guard に登録。
  // discard callback は同画面に startTransition 型 form がある場合のみ発火 (将来備え)。
  const [restoreDirty, setRestoreDirty] = useState(false);
  const importDiscardRef = useDraftDiscardRef<HTMLFormElement>(() => setImportJson(""));
  const restoreDiscardRef = useDraftDiscardRef<HTMLFormElement>(() => setRestoreDirty(false));
  // adversarial R2/R4: pre-commit gate の承認済み draft 破棄関数を action ごとに保持する。
  // shared ref は並行 submit で別 action の draft を誤破棄するため per-action ref にする (R4)。
  const archiveCommitRef = useRef<() => void>(noop);
  const deleteCommitRef = useRef<() => void>(noop);
  const restoreCommitRef = useRef<() => void>(noop);
  const importCommitRef = useRef<() => void>(noop);

  // confirm state の reset は action callback 内で行う (effect 内 setState を避ける)。
  // adversarial R3: 副作用は any-ok effect ではなく各 action wrapper で action-scoped に実行する
  // (過去の ok state が別 action の error で再発火し、失敗操作の draft を成功扱いで破棄するのを防ぐ)。
  const finish = (ref: RefObject<() => void>) => {
    ref.current();
    ref.current = noop;
    requestRefresh();
  };
  const [archiveState, archiveAction, archivePending] = useActionState(
    async (prev: SettingsActionState, formData: FormData): Promise<SettingsActionState> => {
      const result = await archiveProjectAction(prev, formData);
      if (result.kind === "ok") {
        setArchiveConfirming(false);
        finish(archiveCommitRef);
      }
      return result;
    },
    INITIAL_STATE
  );
  const [deleteState, deleteAction, deletePending] = useActionState(
    async (prev: SettingsActionState, formData: FormData): Promise<SettingsActionState> => {
      const result = await bulkSoftDeleteAction(prev, formData);
      if (result.kind === "ok") {
        setDeleteConfirming(false);
        finish(deleteCommitRef);
      }
      return result;
    },
    INITIAL_STATE
  );
  const [restoreState, restoreAction, restorePending] = useActionState(
    async (prev: SettingsActionState, formData: FormData): Promise<SettingsActionState> => {
      const result = await restoreBatchAction(prev, formData);
      if (result.kind === "ok") {
        setRestoreDirty(false);
        finish(restoreCommitRef);
      }
      return result;
    },
    INITIAL_STATE
  );
  const [importState, importAction, importPending] = useActionState(
    async (prev: ImportActionState, formData: FormData): Promise<ImportActionState> => {
      const result = await importTicketsAction(prev, formData);
      if (result.kind === "ok") {
        setImportJson("");
        finish(importCommitRef);
      }
      return result;
    },
    INITIAL_IMPORT_STATE
  );
  // adversarial R4: 並行 submit を防ぐため、いずれかの mutation が pending 中は全 form の submit を block。
  const anyPending = archivePending || deletePending || restorePending || importPending;

  // import: プレビュー成功かつ JSON が編集されていない場合のみ「実行」を許可する
  // (プレビュー後に textarea を編集したら再プレビューを要求し stale な確認での import を防ぐ)。
  const importPreviewValidForCurrentJson =
    importState.kind === "preview" &&
    importState.valid &&
    importState.json === importJson;

  return (
    <div className="grid gap-8">
      {/* Q-4: プロジェクトアーカイブ */}
      <section className="grid gap-3" aria-labelledby="data-mgmt-archive">
        <div className="flex items-center gap-3">
          <h3 id="data-mgmt-archive" className="text-sm font-semibold text-ink">
            プロジェクトのアーカイブ
          </h3>
          <StatusBadge status={status} />
        </div>
        <p className="text-sm text-muted-foreground">
          アーカイブは可逆操作です。アーカイブ中は ticket の作成・編集・インポート・一括削除・復元が
          凍結されます (アーカイブ解除で再開)。
        </p>

        <form
          action={archiveAction}
          onSubmit={(event) => {
            const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
            if (!approved) {
              event.preventDefault();
              return;
            }
            archiveCommitRef.current = commit;
          }}
          className="grid gap-3"
          data-testid="archive-form"
        >
          <input type="hidden" name="project_id" value={projectId} />
          {/* compare-and-swap baseline: 現在の status。別操作で変わっていれば 409。 */}
          <input type="hidden" name="expected_status" value={status} />
          <input type="hidden" name="archived" value={archived ? "false" : "true"} />

          {!archiveConfirming ? (
            <div>
              <button
                type="button"
                onClick={() => setArchiveConfirming(true)}
                className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink shadow-sm hover:bg-canvas disabled:opacity-60"
                disabled={archivePending}
              >
                {archived ? "アーカイブを解除する" : "プロジェクトをアーカイブする"}
              </button>
            </div>
          ) : (
            <div className="grid gap-3 rounded-md border border-amber-300 dark:border-amber-700 bg-amber-50 dark:bg-amber-950/40 p-3">
              <p className="text-sm text-amber-900 dark:text-amber-200">
                {archived
                  ? "アーカイブを解除して ticket 操作を再開しますか？"
                  : "プロジェクトをアーカイブしますか？子要素 (ticket) の変更が凍結されます。"}
              </p>
              <div className="flex gap-2">
                <button
                  type="submit"
                  className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
                  disabled={anyPending}
                >
                  {archivePending
                    ? "処理中..."
                    : archived
                      ? "アーカイブ解除を確定"
                      : "アーカイブを確定"}
                </button>
                <button
                  type="button"
                  onClick={() => setArchiveConfirming(false)}
                  className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-canvas"
                  disabled={archivePending}
                >
                  キャンセル
                </button>
              </div>
            </div>
          )}
          <StatusMessage state={archiveState} />
        </form>
      </section>

      {/* Q-3: ticket 一括 soft-delete (二段階確認) */}
      <section
        className="grid gap-3 border-t border-line pt-6"
        aria-labelledby="data-mgmt-bulk-delete"
      >
        <h3 id="data-mgmt-bulk-delete" className="text-sm font-semibold text-ink">
          ticket の一括削除
        </h3>
        <p className="text-sm text-muted-foreground">
          現在のアクティブ ticket{" "}
          <span className="font-mono font-semibold text-ink">{activeTicketCount}</span> 件を
          一括で soft-delete します。削除はバッチ単位で復元できます (hard delete はしません)。
        </p>

        {archived ? (
          <p className="rounded-md bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            プロジェクトがアーカイブされているため一括削除は無効です。アーカイブを解除してください。
          </p>
        ) : (
          <form
            action={deleteAction}
            onSubmit={(event) => {
              const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
              if (!approved) {
                event.preventDefault();
                return;
              }
              deleteCommitRef.current = commit;
            }}
            className="grid gap-3"
            data-testid="bulk-delete-form"
          >
            <input type="hidden" name="project_id" value={projectId} />
            {/* CAS: 表示した件数を宣言。backend current と不一致なら 409。 */}
            <input
              type="hidden"
              name="expected_active_count"
              value={String(activeTicketCount)}
            />
            {!deleteConfirming ? (
              <div>
                <button
                  type="button"
                  onClick={() => setDeleteConfirming(true)}
                  className="rounded-md border border-rose-300 dark:border-rose-700 bg-panel px-4 py-2 text-sm font-medium text-rose-700 dark:text-rose-300 shadow-sm hover:bg-rose-50 dark:hover:bg-rose-950/40 disabled:opacity-60"
                  disabled={deletePending || activeTicketCount === 0}
                >
                  アクティブ ticket を全件削除する
                </button>
                {activeTicketCount === 0 ? (
                  <p className="mt-1 text-xs text-muted-foreground">
                    削除対象のアクティブ ticket はありません。
                  </p>
                ) : null}
              </div>
            ) : (
              <div className="grid gap-3 rounded-md border border-rose-300 dark:border-rose-700 bg-rose-50 dark:bg-rose-950/40 p-3">
                <p className="text-sm text-rose-900 dark:text-rose-200">
                  本当に <span className="font-semibold">{activeTicketCount} 件</span>{" "}
                  すべての ticket を削除しますか？この操作は監査に記録され、復元バッチ ID が発行されます。
                </p>
                <div className="flex gap-2">
                  <button
                    type="submit"
                    className="rounded-md bg-rose-600 px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-rose-700 disabled:opacity-60"
                    disabled={anyPending}
                  >
                    {deletePending ? "削除中..." : `${activeTicketCount} 件の削除を確定`}
                  </button>
                  <button
                    type="button"
                    onClick={() => setDeleteConfirming(false)}
                    className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink hover:bg-canvas"
                    disabled={deletePending}
                  >
                    キャンセル
                  </button>
                </div>
              </div>
            )}
            <StatusMessage state={deleteState} />
          </form>
        )}
      </section>

      {/* Q-3: バッチ復元 */}
      <section
        className="grid gap-3 border-t border-line pt-6"
        aria-labelledby="data-mgmt-restore"
      >
        <h3 id="data-mgmt-restore" className="text-sm font-semibold text-ink">
          削除バッチの復元
        </h3>
        <p className="text-sm text-muted-foreground">
          一括削除時に発行された復元バッチ ID を指定して、そのバッチの ticket を復元します。
        </p>
        {archived ? (
          <p className="rounded-md bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            プロジェクトがアーカイブされているため復元は無効です。アーカイブを解除してください。
          </p>
        ) : (
          <form
            ref={restoreDiscardRef}
            action={restoreAction}
            onChange={() => setRestoreDirty(true)}
            onSubmit={(event) => {
              const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
              if (!approved) {
                event.preventDefault();
                return;
              }
              restoreCommitRef.current = commit;
            }}
            className="grid gap-3"
            data-testid="restore-form"
            data-unsaved-guard=""
            data-dirty={restoreDirty ? "true" : undefined}
          >
            <input type="hidden" name="project_id" value={projectId} />
            <label className="grid gap-2 text-sm">
              <span className="font-medium">復元バッチ ID (UUID)</span>
              <input
                name="deleted_batch_id"
                placeholder="00000000-0000-0000-0000-000000000000"
                className="rounded-md border border-line bg-panel px-3 py-2 font-mono text-sm outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              />
            </label>
            <div>
              <button
                type="submit"
                className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink shadow-sm hover:bg-canvas disabled:opacity-60"
                disabled={anyPending}
              >
                {restorePending ? "復元中..." : "バッチを復元"}
              </button>
            </div>
            <StatusMessage state={restoreState} />
          </form>
        )}
      </section>

      {/* Q-2: ticket 一括インポート (dry-run preview) */}
      <section
        className="grid gap-3 border-t border-line pt-6"
        aria-labelledby="data-mgmt-import"
      >
        <h3 id="data-mgmt-import" className="text-sm font-semibold text-ink">
          ticket の一括インポート
        </h3>
        <p className="text-sm text-muted-foreground">
          ticket の JSON 配列 (1〜100 件) を貼り付けてインポートします。各要素は{" "}
          <code className="font-mono text-xs">{"{ slug, title, description?, status?, priority? }"}</code>
          。まずプレビューで検証し、衝突がなければインポートを実行します (all-or-nothing)。
        </p>

        {archived ? (
          <p className="rounded-md bg-amber-50 dark:bg-amber-950/40 px-3 py-2 text-sm text-amber-800 dark:text-amber-300">
            プロジェクトがアーカイブされているためインポートは無効です。アーカイブを解除してください。
          </p>
        ) : (
          <form
            ref={importDiscardRef}
            action={importAction}
            onSubmit={(event) => {
              const { approved, commit } = prepareDiscardOnCommit(event.currentTarget);
              if (!approved) {
                event.preventDefault();
                return;
              }
              importCommitRef.current = commit;
            }}
            className="grid gap-3"
            data-testid="import-form"
            data-unsaved-guard=""
            data-dirty={importJson.trim() ? "true" : undefined}
          >
            <input type="hidden" name="project_id" value={projectId} />
            <input type="hidden" name="tickets_json" value={importJson} />
            <label className="grid gap-2 text-sm">
              <span className="sr-only">インポートする ticket の JSON</span>
              <textarea
                aria-label="インポートする ticket の JSON"
                rows={8}
                value={importJson}
                onChange={(event) => setImportJson(event.target.value)}
                placeholder='[{ "slug": "example-1", "title": "Example" }]'
                className="min-h-40 resize-y rounded-md border border-line bg-panel px-3 py-2 font-mono text-xs outline-offset-2 focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
              />
            </label>

            <div className="flex flex-wrap gap-2">
              <button
                type="submit"
                name="dry_run"
                value="true"
                className="rounded-md border border-line bg-panel px-4 py-2 text-sm font-medium text-ink shadow-sm hover:bg-canvas disabled:opacity-60"
                disabled={anyPending || importJson.trim().length === 0}
              >
                {importPending ? "検証中..." : "プレビュー (検証のみ)"}
              </button>
              <button
                type="submit"
                name="dry_run"
                value="false"
                className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-white shadow-sm hover:bg-accent/90 disabled:opacity-60"
                disabled={anyPending || !importPreviewValidForCurrentJson}
              >
                {importPending ? "インポート中..." : "インポートを実行"}
              </button>
            </div>

            {importState.kind === "preview" ? (
              <div
                role="status"
                className={
                  importState.valid
                    ? "grid gap-1 rounded-md bg-emerald-50 dark:bg-emerald-950/40 px-3 py-2 text-sm text-emerald-800 dark:text-emerald-300"
                    : "grid gap-1 rounded-md bg-rose-50 dark:bg-rose-950/40 px-3 py-2 text-sm text-rose-700 dark:text-rose-300"
                }
              >
                {importState.json !== importJson ? (
                  <p>
                    JSON が変更されました。再度プレビューを実行してください。
                  </p>
                ) : importState.valid ? (
                  <p>
                    検証成功: {importState.parsedCount} 件をインポートできます。「インポートを実行」
                    を押してください。
                  </p>
                ) : (
                  <>
                    <p className="font-semibold">検証エラー: 衝突を解消してください。</p>
                    {importState.inPayloadDuplicateSlugs.length > 0 ? (
                      <p>
                        入力内の重複 slug:{" "}
                        <span className="font-mono">
                          {importState.inPayloadDuplicateSlugs.join(", ")}
                        </span>
                      </p>
                    ) : null}
                    {importState.existingConflictSlugs.length > 0 ? (
                      <p>
                        既存 ticket と衝突する slug:{" "}
                        <span className="font-mono">
                          {importState.existingConflictSlugs.join(", ")}
                        </span>
                      </p>
                    ) : null}
                  </>
                )}
              </div>
            ) : null}
            {importState.kind === "ok" ? (
              <StatusMessage state={importState} />
            ) : null}
            {importState.kind === "error" ? (
              <StatusMessage state={importState} />
            ) : null}
          </form>
        )}
      </section>
    </div>
  );
}
