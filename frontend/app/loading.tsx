export default function Loading() {
  return (
    <main className="grid min-h-dvh place-items-center px-4 py-10">
      <div
        aria-live="polite"
        className="rounded-lg border border-line bg-panel px-5 py-4 text-sm font-medium text-muted-foreground shadow-sm"
        role="status"
      >
        読み込み中です...
      </div>
    </main>
  );
}
