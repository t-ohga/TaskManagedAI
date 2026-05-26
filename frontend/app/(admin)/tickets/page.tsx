/**
 * Sprint 9 BL-0103: Ticket 一覧 (P0 UI skeleton)。
 *
 * 本ページは Sprint 9 batch 1 で読み取り専用 skeleton として実装。
 * 実 API integration (listTickets) と Ticket schema は Sprint 9 batch 2 で
 * `frontend/lib/api/tickets.ts` に追加予定。本 skeleton は P0 UI route
 * 構造と layout を確立し、Sprint 9 残 batch の incremental implementation
 * を可能にする。
 *
 * SP-009 §scope: Ticket / Approval / Run / Audit / Settings UI。
 * server-owned-boundary §1: project_id / tenant_id は Server Component
 * で session から resolve、caller-supplied 経路なし。
 */

export const dynamic = "force-dynamic";

export default function TicketsListPage() {
  return (
    <section aria-label="Tickets" className="grid gap-4">
      <header>
        <p className="text-sm font-medium text-accent">Admin</p>
        <h1 className="text-3xl font-semibold tracking-normal">Tickets</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Sprint 9 BL-0103 skeleton — Ticket 一覧 (Acceptance Criteria + Evidence
          + AgentRun status を表示)。
        </p>
      </header>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">Sprint 9 batch 1 進捗</h2>
        <ul className="mt-2 list-disc pl-5 text-sm text-muted-foreground">
          <li>BL-0103 Ticket 一覧 skeleton (本ページ)</li>
          <li>BL-0104 Ticket 詳細: Sprint 9 batch 2 で実装</li>
          <li>BL-0105 Approval Inbox: 既存実装 (Sprint 3 完成)</li>
          <li>BL-0106 Agent Runs timeline: Sprint 9 batch 3 で実装</li>
          <li>BL-0107 Audit Log: Sprint 9 batch 4 で実装</li>
          <li>BL-0108 Project Settings: Sprint 9 batch 5 で実装</li>
        </ul>
      </article>

      <article className="rounded-md border border-base p-4">
        <h2 className="text-lg font-medium">P0 UI 設計 (SP-009 §scope)</h2>
        <p className="mt-2 text-sm text-muted-foreground">
          - Server Component default (Next.js 16 App Router)
          <br />- secret_ref / installation_token / capability token を DOM に出さない
          <br />- AgentRun 16 状態 + blocked_reason 3 種を status と分離表示
          <br />- payload_data_class と allowed_data_class を別 dimension で表示
          <br />- audit log は raw secret なし (reason_code / hash / pattern hit 種別 のみ)
        </p>
      </article>
    </section>
  );
}
