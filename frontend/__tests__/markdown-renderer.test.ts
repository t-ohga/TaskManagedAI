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

  it("allowlist タグと許可属性 (class) は保持する", () => {
    const out = sanitizeMarkdownHtml('<code class="font-mono">x</code>');
    expect(out).toContain('class="font-mono"');
    expect(out).toContain("<code");
  });
});
