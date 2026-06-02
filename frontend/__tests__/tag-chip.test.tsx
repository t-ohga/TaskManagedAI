import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { TagChip } from "@/components/tag-chip";
import { TAG_COLORS } from "@/lib/api/tags";

describe("TagChip", () => {
  it("renders the tag name", () => {
    const { getByText } = render(<TagChip name="優先度: 高" color="red" />);
    expect(getByText("優先度: 高")).toBeInTheDocument();
  });

  it("maps every palette color to a distinct static bg-* class (Tailwind purge-safe)", () => {
    // 9 色すべてが固有の完全な bg class を持つ。動的 class 生成だと purge で消えるため、
    // palette が drift しても undefined class にならないことを保証する (backend TAG_COLORS と整合)。
    const seen = new Set<string>();
    for (const color of TAG_COLORS) {
      const { container, unmount } = render(<TagChip name="x" color={color} />);
      const span = container.querySelector("span");
      expect(span).not.toBeNull();
      const bgClass = [...(span?.classList ?? [])].find((c) => c.startsWith("bg-"));
      expect(bgClass, `color ${color} must map to a bg-* class`).toBeDefined();
      seen.add(bgClass as string);
      unmount();
    }
    expect(seen.size).toBe(TAG_COLORS.length);
  });

  it("sets title for truncated long names", () => {
    const { getByTitle } = render(<TagChip name="とても長いタグ名のサンプル" color="blue" />);
    expect(getByTitle("とても長いタグ名のサンプル")).toBeInTheDocument();
  });
});
