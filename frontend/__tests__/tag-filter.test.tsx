import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TagFilter } from "@/components/tag-filter";
import type { TagRead } from "@/lib/domain/tag";

const push = vi.fn();
let searchString = "";
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(searchString)
}));

const TAG_A: TagRead = { id: "00000000-0000-4000-8000-00000000a001", name: "bug", color: "red" };
const TAG_B: TagRead = { id: "00000000-0000-4000-8000-00000000b002", name: "docs", color: "blue" };

beforeEach(() => {
  push.mockClear();
  searchString = "";
});

describe("TagFilter", () => {
  it("renders nothing when there are no tags", () => {
    const { container } = render(<TagFilter tags={[]} />);
    expect(container.firstChild).toBeNull();
  });

  it("sets ?tag=<id> when a tag is selected", () => {
    render(<TagFilter tags={[TAG_A, TAG_B]} />);
    fireEvent.click(screen.getByLabelText("タグ「docs」で絞り込み"));
    expect(push).toHaveBeenCalledWith(`?tag=${TAG_B.id}`);
  });

  it("clears ?tag when the active tag is clicked again", () => {
    searchString = `tag=${TAG_A.id}`;
    render(<TagFilter tags={[TAG_A]} />);
    fireEvent.click(screen.getByLabelText("タグ「bug」で絞り込み"));
    expect(push).toHaveBeenCalledWith("?");
  });

  it("shows a clear control only when a tag is active", () => {
    searchString = `tag=${TAG_A.id}`;
    render(<TagFilter tags={[TAG_A]} />);
    fireEvent.click(screen.getByText("クリア"));
    expect(push).toHaveBeenCalledWith("?");
  });
});
