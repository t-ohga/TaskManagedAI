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

// G-4: line-by-line 変換 (J-4 の regex chain から再構成、adversarial R1: 混在行の list/heading を
// 標準 Markdown 準拠で正しく抽出する)。各行を 見出し (# / ## / ###) / 箇条書き (- / *) / 番号付き
// (1.) / 段落 に分類し、連続する list 行を <ul>/<ol> にまとめ、空行で段落/list を区切る。list 項目 /
// 段落 / 見出しの content は escape 済 + inline 装飾のみで属性 / URL / script を生成しない
// (XSS surface は J-4 と同一)。
function markdownToHtml(md: string): string {
  // 改行を LF に正規化してから処理する (code-reviewer LOW: CRLF / CR だと行末 \r が残り、
  // `$` アンカーの都合で list / heading 行の regex match が失敗して preview が崩れる。backend
  // 保存値や copy-paste の CRLF を吸収する)。
  const escaped = escapeHtml(md.replace(/\r\n?/g, "\n"));
  const lines = escaped.split("\n");
  const out: string[] = [];
  let para: string[] = [];
  let list: { type: "ul" | "ol"; items: string[] } | null = null;

  const flushPara = (): void => {
    if (para.length > 0) {
      out.push(`<p>${inlineFormat(para.join("\n"))}</p>`);
      para = [];
    }
  };
  const flushList = (): void => {
    if (list) {
      out.push(`<${list.type}>${list.items.join("")}</${list.type}>`);
      list = null;
    }
  };

  for (const line of lines) {
    if (line.trim() === "") {
      // 空行は段落 / list の区切り。
      flushPara();
      flushList();
      continue;
    }
    const heading = /^(#{1,3}) (.+)$/.exec(line);
    const ulItem = /^[-*] (.+)$/.exec(line);
    const olItem = /^\d+\. (.+)$/.exec(line);

    if (heading) {
      flushPara();
      flushList();
      const level = heading[1]?.length ?? 1;
      out.push(`<h${level}>${inlineFormat(heading[2] ?? "")}</h${level}>`);
    } else if (ulItem) {
      flushPara();
      if (!list || list.type !== "ul") {
        flushList();
        list = { type: "ul", items: [] };
      }
      list.items.push(`<li>${inlineFormat(ulItem[1] ?? "")}</li>`);
    } else if (olItem) {
      flushPara();
      if (!list || list.type !== "ol") {
        flushList();
        list = { type: "ol", items: [] };
      }
      list.items.push(`<li>${inlineFormat(olItem[1] ?? "")}</li>`);
    } else {
      flushList();
      para.push(line);
    }
  }
  flushPara();
  flushList();

  return sanitizeMarkdownHtml(out.join(""));
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
