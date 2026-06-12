import type { SecretRefListItem, SecretRefStatus } from "@/lib/api/session";

/**
 * R-3 (ADR-00036): secret_refs read-only インベントリ table。
 *
 * backend が公開する metadata (scope / name / version / status / rotated / timestamps) のみ表示する。
 * secret_uri / allowed_consumers / allowed_operations / owner_actor_id / raw secret は backend response
 * に含まれず、UI でも一切表示しない。登録 / rotation / revoke は ops/CLI 経路 (UI は read-only)。
 */

const STATUS_STYLE: Record<SecretRefStatus, { label: string; className: string }> = {
  active: { label: "active", className: "bg-emerald-50 dark:bg-emerald-950/40 text-emerald-700 dark:text-emerald-300 ring-emerald-600/20" },
  deprecated: { label: "deprecated", className: "bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-400 ring-slate-500/20" },
  revoked: { label: "revoked", className: "bg-rose-50 dark:bg-rose-950/40 text-rose-700 dark:text-rose-300 ring-rose-600/20" },
  pending: { label: "pending", className: "bg-amber-50 dark:bg-amber-950/40 text-amber-700 dark:text-amber-300 ring-amber-600/20" }
};

function StatusBadge({ status }: { status: SecretRefStatus }) {
  const style = STATUS_STYLE[status];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${style.className}`}
    >
      {style.label}
    </span>
  );
}

function formatDate(value: string | null): string {
  if (!value) return "—";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toISOString().slice(0, 10);
}

export function SecretRefsInventory({ secretRefs }: { secretRefs: SecretRefListItem[] }) {
  if (secretRefs.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        登録済シークレットはありません。プロバイダー API キーや GitHub App
        キーは SOPS + age と SecretBroker 経由で登録されます (UI からの登録・変更はできません)。
      </p>
    );
  }

  return (
    <div
      className="overflow-x-auto focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      // 横スクロールする table を keyboard でスクロール可能にする (axe scrollable-region-focusable)。
      // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex
      tabIndex={0}
    >
      <table className="w-full text-left text-sm">
        <caption className="sr-only">登録済シークレットのインベントリ (読み取り専用)</caption>
        <thead>
          <tr className="border-b border-line text-xs uppercase tracking-normal text-muted-foreground">
            <th scope="col" className="px-3 py-2 font-semibold">スコープ</th>
            <th scope="col" className="px-3 py-2 font-semibold">名前</th>
            <th scope="col" className="px-3 py-2 font-semibold">バージョン</th>
            <th scope="col" className="px-3 py-2 font-semibold">状態</th>
            <th scope="col" className="px-3 py-2 font-semibold">ローテーション</th>
            <th scope="col" className="px-3 py-2 font-semibold">更新日</th>
          </tr>
        </thead>
        <tbody>
          {secretRefs.map((secret) => (
            <tr key={secret.id} className="border-b border-line/60">
              <td className="px-3 py-2 text-ink">{secret.scope}</td>
              <td className="px-3 py-2 font-mono text-xs text-ink">{secret.name}</td>
              <td className="px-3 py-2 font-mono text-xs text-ink">{secret.version}</td>
              <td className="px-3 py-2">
                <StatusBadge status={secret.status} />
              </td>
              <td className="px-3 py-2 text-muted-foreground">
                {secret.rotated ? "rotation 済 (旧版あり)" : "—"}
              </td>
              <td className="px-3 py-2 text-muted-foreground">{formatDate(secret.updated_at)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
