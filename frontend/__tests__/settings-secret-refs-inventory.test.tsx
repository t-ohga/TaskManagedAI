import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SecretRefsInventory } from "../app/(admin)/settings/_components/secret-refs-inventory";
import type { SecretRefListItem } from "@/lib/api/session";

const ITEMS: SecretRefListItem[] = [
  {
    id: "00000000-0000-4000-8000-0000000bb010",
    scope: "provider",
    name: "provider-openai",
    version: "v2",
    status: "active",
    rotated: true,
    created_at: "2026-05-01T00:00:00Z",
    updated_at: "2026-05-20T00:00:00Z",
    deprecated_at: null,
    revoked_at: null
  },
  {
    id: "00000000-0000-4000-8000-0000000bb012",
    scope: "repo",
    name: "github-app-key",
    version: "v1",
    status: "revoked",
    rotated: false,
    created_at: "2026-04-01T00:00:00Z",
    updated_at: "2026-04-15T00:00:00Z",
    deprecated_at: "2026-04-15T00:00:00Z",
    revoked_at: "2026-04-15T00:00:00Z"
  }
];

describe("SecretRefsInventory (R-3 / ADR-00036)", () => {
  it("renders registered secrets with scope/name/version and status badges", () => {
    render(<SecretRefsInventory secretRefs={ITEMS} />);

    // scope / name / version が表示される
    expect(screen.getByText("provider-openai")).toBeVisible();
    expect(screen.getByText("github-app-key")).toBeVisible();
    expect(screen.getByText("v2")).toBeVisible();

    // status バッジ
    expect(screen.getByText("active")).toBeVisible();
    expect(screen.getByText("revoked")).toBeVisible();

    // rotated 表示
    expect(screen.getByText("rotation 済 (旧版あり)")).toBeVisible();

    // table として描画される
    expect(screen.getByRole("table")).toBeInTheDocument();
  });

  it("shows an empty-state message when there are no secrets", () => {
    render(<SecretRefsInventory secretRefs={[]} />);

    expect(
      screen.getByText(/登録済シークレットはありません/u)
    ).toBeVisible();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });

  it("never renders raw secret, secret_uri, or authz topology in the DOM", () => {
    const { container } = render(<SecretRefsInventory secretRefs={ITEMS} />);
    const html = container.innerHTML;

    // secret_uri / raw secret / topology は表示しない
    expect(html).not.toContain("secret://");
    expect(html).not.toMatch(/sk-[A-Za-z0-9_-]{8,}/u);
    expect(html.toLowerCase()).not.toContain("allowed_consumers");
    expect(html.toLowerCase()).not.toContain("allowed_operations");
    expect(html).not.toContain("provider.call");
    expect(html).not.toContain("repo.push");
    expect(html.toLowerCase()).not.toContain("owner_actor_id");
  });
});
