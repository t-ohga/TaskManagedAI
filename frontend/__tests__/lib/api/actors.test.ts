import { describe, expect, it } from "vitest";

import {
  AssignableActorsSchema,
  buildAssigneeNameMap,
  assigneeLabel,
  assigneeSelectOptions,
  type AssignableActor
} from "@/lib/api/actors";

// A-6 (ADR-00046): 担当者割当の zod 契約 + 表示/選択 helper の pure logic。

const ID_A = "00000000-0000-4000-8000-0000000000a1";
const ID_B = "00000000-0000-4000-8000-0000000000b2";
const ID_GHOST = "00000000-0000-4000-8000-0000000000ff";

describe("AssignableActorsSchema", () => {
  it("id + display_name + truncated を持つ正常 response を parse する", () => {
    const parsed = AssignableActorsSchema.parse({
      actors: [
        { id: ID_A, display_name: "Owner" },
        { id: ID_B, display_name: null }
      ],
      truncated: false
    });
    expect(parsed.actors).toHaveLength(2);
    expect(parsed.actors[1]?.display_name).toBeNull();
    expect(parsed.truncated).toBe(false);
  });

  it("不正な UUID を reject する (fail-closed)", () => {
    expect(() =>
      AssignableActorsSchema.parse({
        actors: [{ id: "not-a-uuid", display_name: "x" }],
        truncated: false
      })
    ).toThrow();
  });

  it("truncated の boolean 欠落を reject する", () => {
    expect(() =>
      AssignableActorsSchema.parse({ actors: [] })
    ).toThrow();
  });
});

describe("buildAssigneeNameMap", () => {
  it("id -> display_name の map を構築する (null も保持)", () => {
    const actors: AssignableActor[] = [
      { id: ID_A, display_name: "Owner" },
      { id: ID_B, display_name: null }
    ];
    const map = buildAssigneeNameMap(actors);
    expect(map.get(ID_A)).toBe("Owner");
    expect(map.has(ID_B)).toBe(true);
    expect(map.get(ID_B)).toBeNull();
  });
});

describe("assigneeLabel", () => {
  const map = buildAssigneeNameMap([
    { id: ID_A, display_name: "Owner" },
    { id: ID_B, display_name: null }
  ]);

  it("null は『未割当』", () => {
    expect(assigneeLabel(map, null)).toBe("未割当");
  });

  it("map にあり display_name あり -> display_name", () => {
    expect(assigneeLabel(map, ID_A)).toBe("Owner");
  });

  it("map にあり display_name null -> 『担当者 (名称未設定)』", () => {
    expect(assigneeLabel(map, ID_B)).toBe("担当者 (名称未設定)");
  });

  it("map-miss (legacy 非 human / fetch 失敗) -> 『担当者 (不明)』。UUID を晒さない", () => {
    expect(assigneeLabel(map, ID_GHOST)).toBe("担当者 (不明)");
    expect(assigneeLabel(new Map(), ID_A)).toBe("担当者 (不明)");
  });
});

describe("assigneeSelectOptions", () => {
  const actors: AssignableActor[] = [
    { id: ID_A, display_name: "Owner" },
    { id: ID_B, display_name: null }
  ];

  it("actors を {value,label} に写像し、display_name null は fallback label", () => {
    const opts = assigneeSelectOptions(actors, null);
    expect(opts).toEqual([
      { value: ID_A, label: "Owner" },
      { value: ID_B, label: "担当者 (名称未設定)" }
    ]);
  });

  it("現 assignee が一覧に無いとき option に保持する (R1 F-009、現在値を失わない)", () => {
    const opts = assigneeSelectOptions(actors, ID_GHOST);
    expect(opts.map((o) => o.value)).toContain(ID_GHOST);
    expect(opts.find((o) => o.value === ID_GHOST)?.label).toBe("担当者 (一覧外)");
  });

  it("現 assignee が一覧に有るとき重複させない", () => {
    const opts = assigneeSelectOptions(actors, ID_A);
    expect(opts.filter((o) => o.value === ID_A)).toHaveLength(1);
  });

  it("現 assignee null のとき余分な option を足さない", () => {
    const opts = assigneeSelectOptions(actors, null);
    expect(opts).toHaveLength(2);
  });
});
