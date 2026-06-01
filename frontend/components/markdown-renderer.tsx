import DOMPurify from "isomorphic-dompurify";

type MarkdownRendererProps = {
  content: string;
};

// J-4 (UI 監査 fix): 脆弱な denylist sanitize を DOMPurify (allowlist) に置換。
// markdownToHtml は入力を先に entity-escape し固定タグ集合のみ生成するが、将来の
// コンバータ拡張時の XSS を防ぐ defense-in-depth として、生成 HTML を allowlist で
// 最終 sanitize する (rendering.md §8: Markdown rendering は sanitize する)。
const ALLOWED_TAGS = ["h1", "h2", "h3", "strong", "em", "code", "p"];
const ALLOWED_ATTR = ["class"];

export function sanitizeMarkdownHtml(html: string): string {
  return DOMPurify.sanitize(html, { ALLOWED_TAGS, ALLOWED_ATTR });
}

function markdownToHtml(md: string): string {
  let html = md
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  html = html.replace(/^### (.+)$/gm, "<h3>$1</h3>");
  html = html.replace(/^## (.+)$/gm, "<h2>$1</h2>");
  html = html.replace(/^# (.+)$/gm, "<h1>$1</h1>");
  html = html.replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/\*(.+?)\*/g, "<em>$1</em>");
  html = html.replace(/`(.+?)`/g, '<code class="rounded bg-gray-100 px-1 py-0.5 text-xs font-mono">$1</code>');
  html = html.replace(/\n\n/g, "</p><p>");
  html = `<p>${html}</p>`;
  html = html.replace(/<p><h([123])>/g, "<h$1>").replace(/<\/h([123])><\/p>/g, "</h$1>");

  return sanitizeMarkdownHtml(html);
}

export function MarkdownRenderer({ content }: MarkdownRendererProps) {
  const html = markdownToHtml(content);
  return (
    <div
      className="prose prose-sm max-w-none text-sm leading-relaxed"
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}

export { markdownToHtml };
