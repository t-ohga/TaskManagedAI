import { describe, expect, it } from "vitest";

import { markdownToHtml, sanitizeMarkdownHtml } from "@/components/markdown-renderer";

describe("markdownToHtml (J-4 DOMPurify sanitize)", () => {
  it("正常な markdown を固定の安全タグに変換する", () => {
    expect(markdownToHtml("**bold**")).toContain("<strong>bold</strong>");
    expect(markdownToHtml("*em*")).toContain("<em>em</em>");
    expect(markdownToHtml("# Title")).toContain("<h1>Title</h1>");
    expect(markdownToHtml("`code`")).toMatch(/<code class="[^"]*">code<\/code>/);
  });

  it("入力中の生 HTML は entity-escape されタグ化されない", () => {
    const out = markdownToHtml("<script>alert(1)</script>");
    expect(out).not.toMatch(/<script/i);
    const img = markdownToHtml("<img src=x onerror=alert(1)>");
    expect(img).not.toMatch(/<img/i);
    // 実行可能な属性を持つ実タグが生成されないこと。
    expect(img).not.toMatch(/<\w+[^>]*\son\w+=/i);
  });

  // G-4: 箇条書き / 番号付きリスト対応。
  it("箇条書き (- / *) を <ul><li> に変換する", () => {
    const ul = markdownToHtml("- りんご\n- ばなな");
    expect(ul).toBe("<ul><li>りんご</li><li>ばなな</li></ul>");
    const ulStar = markdownToHtml("* a\n* b");
    expect(ulStar).toBe("<ul><li>a</li><li>b</li></ul>");
  });

  it("番号付きリスト (1. 2.) を <ol><li> に変換する", () => {
    const ol = markdownToHtml("1. first\n2. second\n3. third");
    expect(ol).toBe("<ol><li>first</li><li>second</li><li>third</li></ol>");
  });

  it("リスト項目内の inline 装飾は適用するが生 HTML は escape する", () => {
    const out = markdownToHtml("- **太字** と `code`");
    expect(out).toContain("<li><strong>太字</strong> と <code");
    const xss = markdownToHtml("- <img src=x onerror=alert(1)>");
    // li は生成されるが、項目内の生 HTML は entity-escape され実タグ化されない (escape + sanitize)。
    // "onerror" は無害な literal text として残るが、実行可能な属性を持つ実タグは生成されない。
    expect(xss).toMatch(/<li>/);
    expect(xss).not.toMatch(/<img/i);
    expect(xss).toContain("&lt;img");
    // 実タグに on* 属性が付かないこと (escape 済テキストの "onerror=" は実タグ外)。
    expect(xss).not.toMatch(/<\w+[^>]*\son\w+=/i);
  });

  it("リストと段落が混在する block を分離する", () => {
    const out = markdownToHtml("導入文\n\n- a\n- b\n\n結び");
    expect(out).toBe("<p>導入文</p><ul><li>a</li><li>b</li></ul><p>結び</p>");
  });

  it("リスト記号に見える行が混在する block は段落として扱う (誤 li 生成しない)", () => {
    const out = markdownToHtml("ふつうの文\n- 1 項目だけリスト風");
    // 全行が list 形式でない block は段落 (li を作らない)。
    expect(out).not.toMatch(/<li>/);
    expect(out).toMatch(/<p>/);
  });
});

describe("sanitizeMarkdownHtml (DOMPurify allowlist の defense-in-depth)", () => {
  it("allowlist 外のタグ (script/iframe/a/img) を除去する", () => {
    expect(sanitizeMarkdownHtml("<p>ok</p><script>alert(1)</script>")).not.toMatch(/<script/i);
    expect(sanitizeMarkdownHtml('<iframe src="evil"></iframe>')).not.toMatch(/<iframe/i);
    expect(sanitizeMarkdownHtml('<a href="javascript:alert(1)">x</a>')).not.toMatch(/<a[\s>]/i);
    expect(sanitizeMarkdownHtml('<img src=x onerror=alert(1)>')).not.toMatch(/<img/i);
  });

  it("allowlist タグでも禁止属性 (on* / style) を除去する", () => {
    const out = sanitizeMarkdownHtml('<strong onclick="evil()" style="x">x</strong>');
    expect(out).toMatch(/<strong[^>]*>x<\/strong>/i);
    expect(out).not.toMatch(/onclick/i);
    expect(out).not.toMatch(/style=/i);
  });

  it("class は <code> でのみ保持し、他タグの class は除去する (閉じた allowlist)", () => {
    const code = sanitizeMarkdownHtml('<code class="font-mono">x</code>');
    expect(code).toContain('class="font-mono"');
    expect(code).toContain("<code");

    const para = sanitizeMarkdownHtml('<p class="hidden">x</p>');
    expect(para).toMatch(/<p[^>]*>x<\/p>/i);
    expect(para).not.toMatch(/class=/i);
  });

  it("data-* / aria-* 属性を除去する (DOMPurify 既定の暗黙許可を無効化、R1)", () => {
    const out = sanitizeMarkdownHtml('<p data-x="1" aria-label="x" class="y">z</p>');
    expect(out).toMatch(/<p[^>]*>z<\/p>/i);
    expect(out).not.toMatch(/data-x/i);
    expect(out).not.toMatch(/aria-label/i);
    // class も <p> では除去される。
    expect(out).not.toMatch(/class=/i);
  });
});
