import { Breadcrumb } from "@/components/breadcrumb";
import { loadDomainTrustList } from "@/lib/api/research-advanced";

import { AdminPageShell, Panel } from "../_components/sprint9-admin-ui";
import { DomainTrustManager } from "./_components";

export const dynamic = "force-dynamic";

export default async function DomainTrustPage() {
  const result = await loadDomainTrustList();

  return (
    <AdminPageShell
      description={
        <>
          リサーチ証拠の出典ドメインに対する <code>trust_tier</code> (低 / 中 / 高) を tenant 単位で
          登録します。リサーチ詳細では各証拠のドメインに照合した信頼度バッジが表示されます
          (SP-032 / ADR-00052)。登録・編集・削除はオーナーのみ可能です。
        </>
      }
      eyebrow="管理 / ドメイン信頼度"
      regionLabel="ドメイン信頼度レジストリ"
      title="ドメイン信頼度レジストリ"
    >
      <Breadcrumb
        items={[
          { label: "ダッシュボード", href: "/dashboard" },
          { label: "ドメイン信頼度" }
        ]}
      />

      <Panel
        description="ドメインはホスト名単位 (exact match) で登録します。scheme / path / port は含めず、ホスト名のみを入力してください。"
        title="ドメイン信頼度の管理"
        titleId="domain-trust-manage"
      >
        {result.ok ? (
          <DomainTrustManager entries={result.data.items} />
        ) : (
          <p role="alert" className="rounded-md border border-rose-200 dark:border-rose-800 bg-rose-50 dark:bg-rose-950/40 p-3 text-sm text-danger">
            ドメイン信頼度レジストリの読込に失敗しました。時間をおいて再度お試しください。
          </p>
        )}
      </Panel>
    </AdminPageShell>
  );
}
