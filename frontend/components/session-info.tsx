type SessionInfoProps = {
  // 実 DevSession (cookie) から解決した値。取得できない場合は null。
  actorId: string | null;
  // R-1 セッションタイムアウト表示: dev session cookie の有効期限 (ISO 文字列)。
  expiresAt: string | null;
  // R-1: 有効期限までの残り時間ラベル (例「あと約 3 時間 12 分」)。impure な現在時刻計算は
  // data loader 側で行い、本 component は pure に保つ (render body で Date.now() を呼ばない)。
  remainingLabel: string | null;
  // R-2 (ADR-00043): 最終ログイン日時 (iat 由来、ISO 文字列)。iat 無 cookie は null。
  lastLoginAt: string | null;
};

export function SessionInfo({
  actorId,
  expiresAt,
  remainingLabel,
  lastLoginAt,
}: SessionInfoProps) {
  const expiry = expiresAt ? new Date(expiresAt) : null;
  const lastLogin = lastLoginAt ? new Date(lastLoginAt) : null;

  return (
    <article className="rounded-lg border border-line bg-panel p-5 shadow-sm">
      <h2 className="text-base font-semibold">セッション情報</h2>
      <dl className="mt-4 grid gap-3 text-sm">
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">アクター ID</dt>
          <dd className="font-mono text-xs">
            {actorId ? `${actorId.slice(0, 12)}...` : "—"}
          </dd>
        </div>
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">認証方式</dt>
          <dd>Dev Login (P0)</dd>
        </div>
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">ネットワーク</dt>
          <dd>Tailscale 閉域</dd>
        </div>
        {/* R-2 最終ログイン日時 (ADR-00043、iat 由来) */}
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">最終ログイン日時</dt>
          <dd>{lastLogin ? lastLogin.toLocaleString("ja-JP") : "—"}</dd>
        </div>
        {/* R-1 セッションタイムアウト表示 */}
        <div className="flex justify-between border-t border-line pt-3">
          <dt className="text-muted-foreground">セッション有効期限</dt>
          <dd className="text-right">
            {expiry ? (
              <>
                <span className="block">{expiry.toLocaleString("ja-JP")}</span>
                {remainingLabel ? (
                  <span className="block text-xs text-muted-foreground">
                    ({remainingLabel})
                  </span>
                ) : null}
              </>
            ) : (
              "—"
            )}
          </dd>
        </div>
      </dl>
    </article>
  );
}
