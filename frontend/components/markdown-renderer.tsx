import DOMPurify from "isomorphic-dompurify";

type MarkdownRendererProps = {
  content: string;
};

// J-4 (UI 監査 fix): 脆弱な denylist sanitize を DOMPurify (allowlist) に置換。
// markdownToHtml は入力を先に entity-escape し固定タグ集合のみ生成するが、将来の
// コンバータ拡張時の XSS を防ぐ defense-in-depth として、生成 HTML を allowlist で
// 最終 sanitize する (rendering.md §8: Markdown rendering は sanitize する)。
//
// DOMPurify は既定で data-* / aria-* 属性を暗黙許可するため (Codex J-4 R1)、明示的に
// 無効化して「閉じた allowlist」にする。class は本コンバータが付与する <code> のみに
// 限定する (markdown-renderer が DOMPurify の唯一の利用者であることを前提とした hook)。
// G-4: 箇条書き / 番号付きリスト (ul/ol/li) を追加。これらは属性 / URL を持たないため、J-4 の
// 「閉じた allowlist」の XSS surface を広げない (link <a href> は別 follow-up で href sanitize を
// 検討するまで意図的に除外)。
const ALLOWED_TAGS = ["h1", "h2", "h3", "strong", "em", "code", "p", "ul", "ol", "li"];
const ALLOWED_ATTR = ["class"];
const CLASS_ALLOWED_TAG = "code";

DOMPurify.addHook("uponSanitizeAttribute", (node, data) => {
  if (data.attrName === "class" && node.nodeName.toLowerCase() !== CLASS_ALLOWED_TAG) {
    data.keepAttr = false;
  }
});

export function sanitizeMarkdownHtml(html: string): string {
  return DOMPurify.sanitize(html, {
    ALLOWED_TAGS,
    ALLOWED_ATTR,
    ALLOW_DATA_ATTR: false,
    ALLOW_ARIA_ATTR: false
  });
}

// 入力を先に entity-escape する (生 HTML をタグ化させない、J-4 の前提)。
function escapeHtml(text: string): string {
  return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
}

// escape 済テキストに inline 装飾 (太字 / 斜体 / インラインコード) を適用する。
function inlineFormat(escaped: string): string {
  return escaped
    .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
    .replace(/\*(.+?)\*/g, "<em>$1</em>")
    .replace(
      /`(.+?)`/g,
      '<code class="rounded bg-gray-100 px-1 py-0.5 text-xs font-mono">$1</code>'
    );
}

// G-4: block 単位の変換 (J-4 の regex chain から block-based に再構成)。空行 (\n{2,}) で block を
// 分割し、各 block を 見出し / 箇条書き / 番号付き / 段落 に分類する。リスト項目内の content も
// escape 済 + inline 装飾のみで、属性 / URL を生成しない (XSS surface は J-4 と同一)。
function markdownToHtml(md: string): string {
  const escaped = escapeHtml(md);
  const blocks = escaped.split(/\n{2,}/);
  const htmlBlocks: string[] = [];

  for (const block of blocks) {
    const lines = block.split("\n").filter((line) => line.trim() !== "");
    if (lines.length === 0) continue;

    // 見出し (単一行 block の # / ## / ###)。
    if (lines.length === 1) {
      const heading = /^(#{1,3}) (.+)$/.exec(lines[0] ?? "");
      if (heading) {
        const level = heading[1]?.length ?? 1;
        htmlBlocks.push(`<h${level}>${inlineFormat(heading[2] ?? "")}</h${level}>`);
        continue;
      }
    }

    // 箇条書き (全行が `- ` / `* `)。
    if (lines.every((line) => /^[-*] (.+)$/.test(line))) {
      const items = lines
        .map((line) => `<li>${inlineFormat(line.replace(/^[-*] /, ""))}</li>`)
        .join("");
      htmlBlocks.push(`<ul>${items}</ul>`);
      continue;
    }

    // 番号付き (全行が `1. ` 形式)。
    if (lines.every((line) => /^\d+\. (.+)$/.test(line))) {
      const items = lines
        .map((line) => `<li>${inlineFormat(line.replace(/^\d+\. /, ""))}</li>`)
        .join("");
      htmlBlocks.push(`<ol>${items}</ol>`);
      continue;
    }

    // 段落 (複数行は \n 結合 = HTML 上は空白)。
    htmlBlocks.push(`<p>${inlineFormat(lines.join("\n"))}</p>`);
  }

  return sanitizeMarkdownHtml(htmlBlocks.join(""));
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
