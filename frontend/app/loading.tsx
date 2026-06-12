export default function Loading() {
  // loading fallback は layout の <main> の内側にネストして描画されるため、ここで <main> を
  // 使うと main landmark が二重になる (admin layout の main + 本 fallback の main → a11y 違反 +
  // Playwright の locator('main') strict-mode 違反)。landmark を持たない <div> にする
  // (読み込み中の見た目は不変、status role は内側の live region が担保)。
  return (
    <div className="grid min-h-dvh place-items-center px-4 py-10">
      <div
        aria-live="polite"
        className="rounded-lg border border-line bg-panel px-5 py-4 text-sm font-medium text-muted-foreground shadow-sm"
        role="status"
      >
        読み込み中です...
      </div>
    </div>
  );
}
