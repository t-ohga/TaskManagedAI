"use client";

/**
 * C-5 第 2 round: mutation 後の表示同期に使う full reload の seam。
 * - test では本 module を vi.mock する (jsdom の window.location を再定義しない)。
 * - Codex adversarial F-1: 同一ページの **チケット編集フォームに未保存入力**がある状態で
 *   副次 mutation (コメント / タグ / ステータス変更) が成功すると、無条件 reload が入力を
 *   警告なしに破棄する。編集フォームは uncontrolled (value vs defaultValue が dirty の正確な
 *   指標) のため DOM だけで dirty を判定し、dirty 時は確認ダイアログを挟む。
 *   キャンセル時は reload しない (入力保持を優先。周辺表示は次の navigation / 手動更新で収束)。
 */

const EDIT_FORM_SELECTOR = '[data-testid="edit-ticket-form"]';

export function hasUnsavedTicketEdit(): boolean {
  const form = document.querySelector(EDIT_FORM_SELECTOR);
  if (!(form instanceof HTMLFormElement)) {
    return false;
  }
  for (const el of Array.from(form.elements)) {
    if (el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement) {
      if (el instanceof HTMLInputElement && el.type === "hidden") {
        continue;
      }
      if (el.value !== el.defaultValue) {
        return true;
      }
    } else if (el instanceof HTMLSelectElement) {
      const options = Array.from(el.options);
      const defaultIndex = options.findIndex((o) => o.defaultSelected);
      // defaultSelected が無い select はブラウザ既定で先頭が選択される。
      const expected = defaultIndex === -1 ? 0 : defaultIndex;
      if (el.selectedIndex !== expected) {
        return true;
      }
    }
  }
  return false;
}

/**
 * 確実な表示同期 (full reload) を実行する。チケット編集フォームに未保存入力がある場合は
 * 確認してから。キャンセル時は false を返し reload しない。
 */
export function fullReload(
  // test 注入用 seam (jsdom は location.reload を実行できないため)。
  reloadImpl: () => void = () => window.location.reload()
): boolean {
  if (
    hasUnsavedTicketEdit() &&
    !window.confirm(
      "最新の状態に画面を更新します。チケット編集フォームに未保存の変更がありますが、破棄して更新しますか？"
    )
  ) {
    return false;
  }
  reloadImpl();
  return true;
}
