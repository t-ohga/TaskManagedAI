import { describe, expect, it } from "vitest";

import {
  getRoleVisual,
  listRoleVisuals,
  STANDARD_ROLE_IDS
} from "@/lib/domain/role-icon";

describe("role-icon catalog", () => {
  it("matches the SP-013 standard role taxonomy exactly", () => {
    expect(STANDARD_ROLE_IDS).toEqual([
      "orchestrator",
      "implementer",
      "reviewer",
      "tester",
      "security_agent",
      "researcher",
      "observer",
      "curator",
      "dispatcher",
      "repair_specialist"
    ]);
    expect(listRoleVisuals().map((role) => role.rawId)).toEqual(STANDARD_ROLE_IDS);
  });

  it("preserves raw ids while adding Japanese labels and static icons", () => {
    for (const roleId of STANDARD_ROLE_IDS) {
      const visual = getRoleVisual(roleId);
      expect(visual.rawId).toBe(roleId);
      expect(visual.label.length).toBeGreaterThan(0);
      expect(visual.icon.length).toBeGreaterThan(0);
      expect(visual.standard).toBe(true);
    }
  });

  it("does not hide unknown role ids", () => {
    expect(getRoleVisual("custom_agent")).toMatchObject({
      id: "unknown",
      rawId: "custom_agent",
      label: "未分類",
      standard: false
    });
    expect(getRoleVisual(null).rawId).toBe("unassigned");
  });
});
