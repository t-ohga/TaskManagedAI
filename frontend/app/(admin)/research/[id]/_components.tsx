import "server-only";

import type {
  Claim,
  EvidenceItem,
  EvidenceSource,
  ResearchTaskDetail
} from "@/lib/api/research";
import { formatEvidenceRelation, formatResearchStatus } from "@/lib/i18n/research-labels";

function formatDate(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toISOString();
}

function formatRate(value: number | null): string {
  if (value === null) {
    return "n/a";
  }
  return `${Math.round(value * 1000) / 10}%`;
}

// F-PR26-R1-001 P2 adopt: reject non-HTTP(S) schemes. javascript: / data: /
// file: / etc. URLs are accepted by `new URL()` but rendering them as
// `<a href>` would XSS or expose unsafe navigation targets. The
// evidence_sources.canonical_url column is data-backed and not yet
// constrained to http(s) at write time, so the read-side allowlist is
// authoritative.
const SAFE_URL_PROTOCOLS = new Set(["http:", "https:"]);

function safeEvidenceSourceUrl(value: string): string | null {
  try {
    const url = new URL(value);
    if (!SAFE_URL_PROTOCOLS.has(url.protocol)) {
      return null;
    }
    url.username = "";
    url.password = "";
    url.search = "";
    url.hash = "";
    return url.toString();
  } catch {
    return null;
  }
}

function relationSummary(items: readonly EvidenceItem[]): string {
  if (items.length === 0) {
    return "evidence relation なし";
  }

  const counts = new Map<EvidenceItem["relation"], number>();
  for (const item of items) {
    counts.set(item.relation, (counts.get(item.relation) ?? 0) + 1);
  }

  return Array.from(counts.entries())
    .map(([relation, count]) => `${formatEvidenceRelation(relation)}:${count}`)
    .join(" / ");
}

function provenanceRelationCount(claim: Claim): number {
  const prov = claim.provenance_json;
  return (
    prov.wasGeneratedBy.length +
    prov.used.length +
    prov.wasAttributedTo.length +
    prov.wasInformedBy.length +
    prov.wasDerivedFrom.length
  );
}

function ProvenanceSummary({ claim }: { readonly claim: Claim }) {
  const prov = claim.provenance_json;

  return (
    <dl className="mt-3 grid gap-2 text-xs text-muted-foreground sm:grid-cols-4">
      <div className="rounded-md border border-line bg-slate-50 p-2">
        <dt className="font-semibold text-ink">activities</dt>
        <dd>{prov.activities.length}</dd>
      </div>
      <div className="rounded-md border border-line bg-slate-50 p-2">
        <dt className="font-semibold text-ink">entities</dt>
        <dd>{prov.entities.length}</dd>
      </div>
      <div className="rounded-md border border-line bg-slate-50 p-2">
        <dt className="font-semibold text-ink">agents</dt>
        <dd>{prov.agents.length}</dd>
      </div>
      <div className="rounded-md border border-line bg-slate-50 p-2">
        <dt className="font-semibold text-ink">relations</dt>
        <dd>{provenanceRelationCount(claim)}</dd>
      </div>
    </dl>
  );
}

export function ResearchTaskCard({ task }: { readonly task: ResearchTaskDetail }) {
  return (
    <dl className="grid gap-3 md:grid-cols-2">
      <div className="rounded-md border border-line bg-white p-3">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">タイトル</dt>
        <dd className="mt-2 text-sm font-medium text-ink">{task.title}</dd>
      </div>
      <div className="rounded-md border border-line bg-white p-3">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">状態 (status)</dt>
        <dd className="mt-2">
          <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-ink">
            {formatResearchStatus(task.status)}
          </code>
        </dd>
      </div>
      <div className="rounded-md border border-line bg-white p-3">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">project_id</dt>
        <dd className="mt-2 break-all font-mono text-xs text-ink">{task.project_id}</dd>
      </div>
      <div className="rounded-md border border-line bg-white p-3">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
          作成日時 (created_at)
        </dt>
        <dd className="mt-2 text-sm text-muted-foreground">
          <time dateTime={task.created_at}>{formatDate(task.created_at)}</time>
        </dd>
      </div>
    </dl>
  );
}

export function ResearchMetricSummary({ task }: { readonly task: ResearchTaskDetail }) {
  const metric = task.research_evidence_attachment;

  return (
    <dl className="grid gap-3 md:grid-cols-4">
      <div className="rounded-md border border-line bg-white p-3 md:col-span-2">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
          evidence_set_hash
        </dt>
        <dd className="mt-2 break-all font-mono text-xs text-ink">
          {task.evidence_set_hash}
        </dd>
      </div>
      <div className="rounded-md border border-line bg-white p-3">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
          attachment_rate
        </dt>
        <dd className="mt-2 text-2xl font-semibold text-ink">
          {formatRate(metric.attachment_rate)}
        </dd>
      </div>
      <div className="rounded-md border border-line bg-white p-3">
        <dt className="text-xs font-semibold uppercase tracking-normal text-muted-foreground">
          numerator / denominator
        </dt>
        <dd className="mt-2 font-mono text-sm text-ink">
          {metric.numerator} / {metric.denominator}
        </dd>
      </div>
    </dl>
  );
}

export function ClaimList({
  claims,
  evidenceItemsByClaimId
}: {
  readonly claims: readonly Claim[];
  readonly evidenceItemsByClaimId: ReadonlyMap<string, readonly EvidenceItem[]>;
}) {
  if (claims.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line bg-white p-4 text-sm text-muted-foreground">
        このリサーチ task に紐づく claim はありません。
      </div>
    );
  }

  return (
    <ol className="grid gap-3">
      {claims.map((claim) => {
        const evidenceItems = evidenceItemsByClaimId.get(claim.id) ?? [];

        return (
          <li key={claim.id} className="rounded-md border border-line bg-white p-3">
            <div className="flex flex-col gap-2 md:flex-row md:items-start md:justify-between">
              <div>
                <p className="text-sm font-medium text-ink">{claim.claim_text}</p>
                <p className="mt-1 font-mono text-xs text-muted-foreground">{claim.id}</p>
              </div>
              <div className="grid gap-1 text-xs text-muted-foreground md:text-right">
                <span>relation: {relationSummary(evidenceItems)}</span>
                <time dateTime={claim.created_at}>created_at: {formatDate(claim.created_at)}</time>
              </div>
            </div>
            <ProvenanceSummary claim={claim} />
          </li>
        );
      })}
    </ol>
  );
}

export function EvidenceSourceLink({
  source
}: {
  readonly source: EvidenceSource | undefined;
}) {
  if (!source) {
    return <span className="text-xs text-muted-foreground">source 未解決 (source unavailable)</span>;
  }

  const href = safeEvidenceSourceUrl(source.canonical_url);

  if (!href) {
    return <span className="text-xs text-muted-foreground">source 非表示 (redacted source)</span>;
  }

  return (
    <a
      className="break-all text-xs font-semibold text-accent outline-offset-2 hover:underline focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent"
      href={href}
      rel="noreferrer"
      target="_blank"
    >
      {href}
    </a>
  );
}

export function EvidenceItemList({
  items,
  sourcesById
}: {
  readonly items: readonly EvidenceItem[];
  readonly sourcesById: ReadonlyMap<string, EvidenceSource>;
}) {
  if (items.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-line bg-white p-4 text-sm text-muted-foreground">
        このリサーチ task に紐づく evidence item はありません。
      </div>
    );
  }

  return (
    <div className="overflow-x-auto rounded-md border border-line">
      <table className="min-w-full border-separate border-spacing-0 text-left text-sm">
        <caption className="sr-only">
          locator、relation、relevance score、source link を含む evidence item 一覧。
        </caption>
        <thead className="bg-slate-50 text-xs uppercase tracking-normal text-muted-foreground">
          <tr>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              locator
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              relation
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              関連度 (relevance)
            </th>
            <th scope="col" className="border-b border-line px-3 py-2 font-semibold">
              source
            </th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => (
            <tr key={item.id} className="align-top">
              <th scope="row" className="border-b border-line px-3 py-2">
                <code className="break-all font-mono text-xs text-ink">{item.locator}</code>
              </th>
              <td className="border-b border-line px-3 py-2">
                <code className="rounded bg-slate-100 px-1.5 py-0.5 font-mono text-xs text-ink">
                  {formatEvidenceRelation(item.relation)}
                </code>
              </td>
              <td className="border-b border-line px-3 py-2 text-muted-foreground">
                {item.relevance_score === null ? "n/a" : item.relevance_score}
              </td>
              <td className="border-b border-line px-3 py-2">
                <EvidenceSourceLink source={sourcesById.get(item.source_id)} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
