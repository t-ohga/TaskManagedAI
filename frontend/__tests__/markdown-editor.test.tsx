import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it } from "vitest";

import { MarkdownEditor } from "@/components/markdown-editor";

// G-4: ツールバー付き Markdown editor。書式挿入 / 編集・プレビュータブ / controlled・uncontrolled。

describe("MarkdownEditor", () => {
  it("ツールバー (太字/斜体/見出し/箇条書き/番号付き/コード) と textarea を描画する", () => {
    render(<MarkdownEditor name="body" ariaLabel="本文" />);
    expect(screen.getByLabelText("本文")).toBeInTheDocument();
    for (const title of ["太字", "斜体", "見出し", "箇条書き", "番号付きリスト", "インラインコード"]) {
      expect(screen.getByRole("button", { name: title })).toBeInTheDocument();
    }
  });

  it("uncontrolled: name + defaultValue を textarea に反映する (FormData 連携)", () => {
    render(<MarkdownEditor name="description" defaultValue="初期値" ariaLabel="説明" />);
    const ta = screen.getByLabelText("説明") as HTMLTextAreaElement;
    expect(ta.name).toBe("description");
    expect(ta.value).toBe("初期値");
  });

  it("太字ボタンは選択範囲を ** で囲む", () => {
    render(<MarkdownEditor ariaLabel="本文" defaultValue="hello" />);
    const ta = screen.getByLabelText("本文") as HTMLTextAreaElement;
    ta.focus();
    ta.setSelectionRange(0, 5); // "hello" を選択
    fireEvent.click(screen.getByRole("button", { name: "太字" }));
    expect(ta.value).toBe("**hello**");
  });

  it("選択なしの太字はプレースホルダ (**太字**) を挿入する", () => {
    render(<MarkdownEditor ariaLabel="本文" defaultValue="" />);
    const ta = screen.getByLabelText("本文") as HTMLTextAreaElement;
    ta.focus();
    ta.setSelectionRange(0, 0);
    fireEvent.click(screen.getByRole("button", { name: "太字" }));
    expect(ta.value).toBe("**太字**");
  });

  it("箇条書きボタンは行頭に '- ' を付与する", () => {
    render(<MarkdownEditor ariaLabel="本文" defaultValue="りんご" />);
    const ta = screen.getByLabelText("本文") as HTMLTextAreaElement;
    ta.focus();
    ta.setSelectionRange(2, 2); // 行内のカーソル
    fireEvent.click(screen.getByRole("button", { name: "箇条書き" }));
    expect(ta.value).toBe("- りんご");
  });

  it("番号付きボタンは行頭に '1. ' を付与する", () => {
    render(<MarkdownEditor ariaLabel="本文" defaultValue="最初" />);
    const ta = screen.getByLabelText("本文") as HTMLTextAreaElement;
    ta.focus();
    ta.setSelectionRange(0, 0);
    fireEvent.click(screen.getByRole("button", { name: "番号付きリスト" }));
    expect(ta.value).toBe("1. 最初");
  });

  it("プレビュータブで MarkdownRenderer の sanitize 済 HTML を表示する", () => {
    render(<MarkdownEditor ariaLabel="本文" defaultValue={"- **太字** 項目"} />);
    fireEvent.click(screen.getByRole("button", { name: "プレビュー" }));
    // li + strong が描画され、編集タブの textarea は hidden になる。
    expect(screen.getByText("太字").tagName.toLowerCase()).toBe("strong");
    const ta = screen.getByLabelText("本文");
    expect(ta).toHaveClass("hidden");
  });

  it("プレビュー中もツールバーは無効化される (書式挿入不可)", () => {
    render(<MarkdownEditor ariaLabel="本文" defaultValue="x" />);
    fireEvent.click(screen.getByRole("button", { name: "プレビュー" }));
    expect(screen.getByRole("button", { name: "太字" })).toBeDisabled();
  });

  it("controlled: onValueChange に挿入結果を通知する (parent が reset 可能)", () => {
    function Harness() {
      const [v, setV] = useState("text");
      return (
        <>
          <MarkdownEditor ariaLabel="本文" value={v} onValueChange={setV} />
          <span data-testid="value">{v}</span>
        </>
      );
    }
    render(<Harness />);
    const ta = screen.getByLabelText("本文") as HTMLTextAreaElement;
    ta.focus();
    ta.setSelectionRange(0, 4);
    fireEvent.click(screen.getByRole("button", { name: "斜体" }));
    expect(screen.getByTestId("value").textContent).toBe("*text*");
  });
});
