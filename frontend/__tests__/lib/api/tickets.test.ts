import { describe, expect, it } from "vitest";

import {
  DEFAULT_PROJECT_ID,
  TicketListResponseSchema,
  TicketPriorityEnum,
  TicketReadSchema,
  TicketStatusEnum,
} from "@/lib/api/tickets";

describe("tickets schemas (SP-012-9 BL-UIW-003)", () => {
  it("TicketStatusEnum matches backend ticket.py 6 種", () => {
    const expected = [
      "open",
      "in_progress",
      "blocked",
      "review",
      "closed",
      "cancelled",
    ];
    expect(TicketStatusEnum.options).toEqual(expected);
  });

  it("TicketPriorityEnum matches backend 4 種", () => {
    expect(TicketPriorityEnum.options).toEqual(["low", "medium", "high", "critical"]);
  });

  it("TicketReadSchema accepts valid backend response shape", () => {
    const valid = {
      id: "00000000-0000-4000-8000-000000000006",
      tenant_id: 1,
      project_id: DEFAULT_PROJECT_ID,
      repository_id: null,
      slug: "welcome",
      title: "Welcome to TaskManagedAI",
      description: null,
      status: "open",
      priority: null,
      due_date: null,
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true },
      created_at: "2026-05-22T00:00:00+00:00",
      updated_at: "2026-05-22T00:00:00+00:00",
    };
    expect(() => TicketReadSchema.parse(valid)).not.toThrow();
  });

  it("TicketReadSchema requires due_date field (contract drift guard)", () => {
    const missingDueDate = {
      id: "00000000-0000-4000-8000-000000000006",
      tenant_id: 1,
      project_id: DEFAULT_PROJECT_ID,
      repository_id: null,
      slug: "welcome",
      title: "Welcome",
      description: null,
      status: "open",
      priority: null,
      // due_date 欠落 → backend 契約と drift、reject されるべき
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true },
      created_at: "2026-05-22T00:00:00+00:00",
      updated_at: "2026-05-22T00:00:00+00:00",
    };
    expect(() => TicketReadSchema.parse(missingDueDate)).toThrow();
  });

  it("TicketReadSchema accepts due_date as YYYY-MM-DD date string", () => {
    const withDue = {
      id: "00000000-0000-4000-8000-000000000006",
      tenant_id: 1,
      project_id: DEFAULT_PROJECT_ID,
      repository_id: null,
      slug: "welcome",
      title: "Welcome",
      description: null,
      status: "open",
      priority: null,
      due_date: "2026-06-30",
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true },
      created_at: "2026-05-22T00:00:00+00:00",
      updated_at: "2026-05-22T00:00:00+00:00",
    };
    const parsed = TicketReadSchema.parse(withDue);
    expect(parsed.due_date).toBe("2026-06-30");
  });

  it("TicketReadSchema rejects malformed due_date (timestamp / junk / 非実在日) (A-7 R11 F-001)", () => {
    // due_date は date 型 (厳密 YYYY-MM-DD)。serializer drift した値を detail/edit が slice して表示・
    // 誤書き戻ししないため fail-closed で reject (reminders/board と同じ strict-YMD all-surface 整合)。
    const base = {
      id: "00000000-0000-4000-8000-000000000006",
      tenant_id: 1,
      project_id: DEFAULT_PROJECT_ID,
      repository_id: null,
      slug: "welcome",
      title: "Welcome",
      description: null,
      status: "open",
      priority: null,
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: { rls_ready: true },
      created_at: "2026-05-22T00:00:00+00:00",
      updated_at: "2026-05-22T00:00:00+00:00",
    };
    for (const bad of ["2026-06-30T00:00:00Z", "2026-06-30junk", "2026-02-31", "2026-6-3"]) {
      expect(() => TicketReadSchema.parse({ ...base, due_date: bad })).toThrow();
    }
    // 正常な YMD と null は通過する。
    expect(TicketReadSchema.parse({ ...base, due_date: "2026-06-30" }).due_date).toBe("2026-06-30");
    expect(TicketReadSchema.parse({ ...base, due_date: null }).due_date).toBeNull();
  });

  it("TicketReadSchema rejects unknown status enum", () => {
    const invalid = {
      id: "00000000-0000-4000-8000-000000000006",
      tenant_id: 1,
      project_id: DEFAULT_PROJECT_ID,
      repository_id: null,
      slug: "x",
      title: "X",
      description: null,
      status: "INVALID_STATUS",  // not in enum
      priority: null,
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: {},
      created_at: "2026-05-22T00:00:00+00:00",
      updated_at: "2026-05-22T00:00:00+00:00",
    };
    expect(() => TicketReadSchema.parse(invalid)).toThrow();
  });

  it("TicketReadSchema rejects invalid UUID", () => {
    const invalid = {
      id: "not-a-uuid",
      tenant_id: 1,
      project_id: DEFAULT_PROJECT_ID,
      repository_id: null,
      slug: "x",
      title: "X",
      description: null,
      status: "open",
      priority: null,
      assignee_actor_id: null,
      created_by_actor_id: "00000000-0000-4000-8000-000000000001",
      metadata: {},
      created_at: "2026-05-22T00:00:00+00:00",
      updated_at: "2026-05-22T00:00:00+00:00",
    };
    expect(() => TicketReadSchema.parse(invalid)).toThrow();
  });

  it("TicketListResponseSchema parses backend list response", () => {
    const valid = {
      items: [],
      total: 0,
      limit: 50,
      offset: 0,
    };
    expect(() => TicketListResponseSchema.parse(valid)).not.toThrow();
  });

  it("DEFAULT_PROJECT_ID matches seeds/initial.py DEFAULT_PROJECT_ID", () => {
    // seeds/initial.py の DEFAULT_PROJECT_ID と sync 必須
    expect(DEFAULT_PROJECT_ID).toBe("00000000-0000-4000-8000-000000000004");
  });
});
