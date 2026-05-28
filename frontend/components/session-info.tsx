type SessionInfoProps = {
  actorId: string;
};

export function SessionInfo({ actorId }: SessionInfoProps) {
  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <h2 className="text-base font-semibold">セッション情報</h2>
      <dl className="mt-4 grid gap-3 text-sm">
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">アクター ID</dt>
          <dd className="font-mono text-xs">{actorId.slice(0, 12)}...</dd>
        </div>
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">認証方式</dt>
          <dd>Dev Login (P0)</dd>
        </div>
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">ネットワーク</dt>
          <dd>Tailscale 閉域</dd>
        </div>
      </dl>
    </article>
  );
}
