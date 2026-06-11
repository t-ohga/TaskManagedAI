"use client";

/**
 * C-5 第 2 round: mutation 後の表示同期に使う full reload の seam と、
 * 未保存 draft の pre-commit 破棄確認 gate。
 * test では本 module を vi.mock する (jsdom の window.location を再定義しない)。
 */

/**
 * R3/R4 (Codex adversarial): 未保存 draft の検知は **汎用 convention** で行う —
 * reload で失われ得る入力を持つ領域 (チケット編集フォーム / コメント / タグ管理 /
 * 新規チケット作成) は `data-unsaved-guard` 属性を持ち、draft がある間
 * `data-dirty="true"` を立てる。
 * - DOM の value/defaultValue 比較は controlled field (MarkdownEditor) をすり抜けるため不採用。
 * - toolbar 由来の変更は MarkdownEditor が bubbling input event を dispatch して通知する。
 * - `except` には「mutation を起こした領域自身」を渡す (自分の draft を consume する操作で
 *   自分に confirm を出さない。例: コメント送信はコメント form を、タグ操作はタグ管理領域を除外)。
 */
const GUARD_SELECTOR = "[data-unsaved-guard]";

/**
 * R10 (Codex adversarial HIGH): discardDrafts() の DOM 操作 (dirty 削除 + form.reset()) は
 * React state を正本とする draft (コメント body / タグ名 / MarkdownEditor 内部 state) を
 * 破棄できない — controlled value は次 render で復活し、state 由来の data-dirty も再付与される。
 * そのため discard 時に guard 要素へ本 event を dispatch し、各 component が listener
 * (lib/use-draft-discard.ts) で **自身の React state を破棄**する。
 */
export const DRAFT_DISCARD_EVENT = "unsaved-draft:discard";

export function hasUnsavedDraft(except?: Element | null): boolean {
  for (const guard of Array.from(document.querySelectorAll(GUARD_SELECTOR))) {
    if (!(guard instanceof HTMLElement)) {
      continue;
    }
    if (except && (guard === except || guard.contains(except) || except.contains(guard))) {
      continue;
    }
    if (guard.dataset.dirty === "true") {
      return true;
    }
  }
  return false;
}

/**
 * R2 (Codex adversarial HIGH): 未保存 draft の破棄確認は **mutation 実行前 (pre-commit)** に行う。
 * post-commit の確認だと、キャンセルで stale な編集フォームが残り、それを後から保存すると
 * 直前に commit された変更 (例: ステータス) を旧値で巻き戻せてしまう。
 *
 * 本関数は **確認のみ** (破棄しない)。reload 直前の再確認 (R7、useDeferredRouterRefresh) 用。
 * 副次 mutation の handler 冒頭で破棄を伴う gate が必要な経路は `prepareDiscardOnCommit` を使う。
 */
export function confirmDiscardUnsavedDrafts(except?: Element | null): boolean {
  if (!hasUnsavedDraft(except)) {
    return true;
  }
  return window.confirm(
    "このページに未保存の入力があります。この操作を行うと画面が更新され、未保存の入力は破棄されます。続行しますか？"
  );
}

/**
 * R11 (Codex adversarial HIGH): pre-commit gate。破棄を **mutation 成功時まで遅延**する。
 *
 * R9/R10 は承認直後 (= server action の前) に React state まで物理破棄していたが、その後 mutation が
 * 失敗 (権限 / project 境界 / network / validation) すると DB は変わらないのに無関係な draft が
 * 不可逆に失われていた。本関数は:
 * - 確認時点の dirty guard を **参照で捕捉** (`pending`)。confirm 承認まで何も破棄しない。
 * - 返り値 `commit()` を **mutation 成功時にのみ呼ぶ**と、捕捉済み guard だけを破棄する。
 *   失敗時は `commit()` を呼ばなければ draft は無傷。
 * - 捕捉は呼び出し時点の dirty guard に固定されるため、mutation 中に新規作成された draft N は
 *   `pending` に含まれず、reload 直前の `confirmDiscardUnsavedDrafts` 再確認 (R7) で別途扱われる
 *   (= 二重 confirm を生まずに新規 draft を保護)。
 *
 * 破棄の rollback 防御 (R8 の touched-field-only PATCH) は維持される — 成功時に commit() で
 * 捕捉 draft を server 値へ戻すため、reload を拒否しても stale form で巻き戻せない。
 */
export function prepareDiscardOnCommit(except?: Element | null): {
  approved: boolean;
  commit: () => void;
} {
  const pending = collectDirtyGuards(except);
  if (pending.length === 0) {
    return { approved: true, commit: noop };
  }
  const approved = window.confirm(
    "このページに未保存の入力があります。この操作を行うと画面が更新され、未保存の入力は破棄されます。続行しますか？"
  );
  if (!approved) {
    return { approved: false, commit: noop };
  }
  return { approved: true, commit: () => discardGuards(pending) };
}

/** 破棄なし (dirty 無し or 確認拒否時) の commit プレースホルダ。 */
export function noop(): void {
  /* no-op */
}

function collectDirtyGuards(except?: Element | null): HTMLElement[] {
  const result: HTMLElement[] = [];
  for (const guard of Array.from(document.querySelectorAll(GUARD_SELECTOR))) {
    if (!(guard instanceof HTMLElement)) {
      continue;
    }
    if (except && (guard === except || guard.contains(except) || except.contains(guard))) {
      continue;
    }
    if (guard.dataset.dirty === "true") {
      result.push(guard);
    }
  }
  return result;
}

function discardGuards(guards: HTMLElement[]): void {
  for (const guard of guards) {
    delete guard.dataset.dirty;
    if (guard instanceof HTMLFormElement) {
      guard.reset();
    } else {
      // form 以外の guard 領域 (タグ管理等) は内包する form を reset する。
      for (const form of Array.from(guard.querySelectorAll("form"))) {
        form.reset();
      }
    }
    // R10: React state 由来の draft は DOM 操作では消えない — component 側 listener に
    // state 破棄を委譲する (上記 DRAFT_DISCARD_EVENT のコメント参照)。
    guard.dispatchEvent(new CustomEvent(DRAFT_DISCARD_EVENT));
  }
}

/**
 * 確実な表示同期 (full reload) を実行する。未保存 draft の確認は呼び出し側が
 * confirmDiscardUnsavedDrafts() で **mutation 前に**済ませている前提 (R2)。
 */
export function fullReload(
  // test 注入用 seam (jsdom は location.reload を実行できないため)。
  reloadImpl: () => void = () => window.location.reload()
): void {
  reloadImpl();
}
