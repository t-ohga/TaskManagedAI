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
 * 直前に commit された変更 (例: ステータス) を旧値で巻き戻せてしまう。本 gate を副次 mutation
 * (コメント / タグ / ステータス / 一括変更 / 中止) の handler 冒頭で呼び、false なら
 * **server action を実行しない** (DB も画面も変化せず、矛盾構造が生まれない)。
 */
export function confirmDiscardUnsavedDrafts(except?: Element | null): boolean {
  if (!hasUnsavedDraft(except)) {
    return true;
  }
  const approved = window.confirm(
    "このページに未保存の入力があります。この操作を行うと画面が更新され、未保存の入力は破棄されます。続行しますか？"
  );
  if (approved) {
    // R9 (Codex adversarial HIGH): 「承認 = 即破棄」。承認した draft をその場で物理的に破棄
    // (dirty クリア + form.reset() で defaultValue = server 値へ) しないと、reload 直前の
    // 再確認 (R7) を拒否した場合に**承認済みの stale draft が生き残り**、編集していた field は
    // R8 の unchanged-field drop をすり抜けて直前 mutation を巻き戻せる。即破棄により:
    // - 再確認の対象は自然に「mutation 中の新規 draft のみ」になる
    // - 拒否で reload しなくても form は server 値に戻っており、保存は all-unchanged = no-op
    discardDrafts(except);
  }
  return approved;
}

function discardDrafts(except?: Element | null): void {
  for (const guard of Array.from(document.querySelectorAll(GUARD_SELECTOR))) {
    if (!(guard instanceof HTMLElement)) {
      continue;
    }
    if (except && (guard === except || guard.contains(except) || except.contains(guard))) {
      continue;
    }
    if (guard.dataset.dirty !== "true") {
      continue;
    }
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
