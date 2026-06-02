import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RemindersPanel } from "../components/reminders-panel";

import type { ReminderItem, ReminderSummary } from "../lib/api/reminders";

function item(overrides: Partial<ReminderItem>): ReminderItem {
  return {
    ticket_id: "00000000-0000-4000-8000-000000000001",
    project_id: "00000000-0000-4000-8000-0000000000a1",
    slug: "task",
    title: "サンプル",
    status: "open",
    priority: null,
    due_date: "2026-06-01",
    days_until: -1,
    ...overrides
  };
}

const baseSummary: ReminderSummary = {
  reference_date: "2026-06-02",
  threshold_days: 7,
  overdue: { count: 0, truncated: false, items: [] },
  due_today: { count: 0, truncated: false, items: [] },
  upcoming: { count: 0, truncated: false, items: [] }
};

describe("RemindersPanel (ADR-00045)", () => {
  it("全 bucket 0 件のとき空状態を表示する", () => {
    render(<RemindersPanel reminders={baseSummary} />);
    expect(
      screen.getByText("期限が近い・超過したチケットはありません。")
    ).toBeInTheDocument();
  });

  it("基準日と window を表示する", () => {
    render(<RemindersPanel reminders={baseSummary} />);
    expect(screen.getByText("2026-06-02 基準 / 7日以内")).toBeInTheDocument();
  });

  it("bucket 別に count + item リンクを表示する", () => {
    const summary: ReminderSummary = {
      ...baseSummary,
      overdue: {
        count: 2,
        truncated: false,
        items: [
          item({ ticket_id: "t-1", title: "超過チケットA", days_until: -3 }),
          item({ ticket_id: "t-2", title: "超過チケットB", days_until: -1 })
        ]
      },
      due_today: {
        count: 1,
        truncated: false,
        items: [item({ ticket_id: "t-3", title: "本日チケット", days_until: 0 })]
      }
    };
    render(<RemindersPanel reminders={summary} />);

    expect(screen.getByRole("heading", { name: "期限超過" })).toBeInTheDocument();
    // overdue=2 / due_today=1 は一意な count badge。
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.getByText("1")).toBeInTheDocument();

    const linkA = screen.getByRole("link", { name: "超過チケットA" });
    expect(linkA).toHaveAttribute("href", "/tickets/t-1");
    expect(screen.getByText("3日超過")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "超過チケットB" })).toBeInTheDocument();

    expect(screen.getByRole("link", { name: "本日チケット" })).toBeInTheDocument();
    expect(screen.getByText("本日")).toBeInTheDocument();
  });

  it("upcoming は『あとN日』を表示する", () => {
    const summary: ReminderSummary = {
      ...baseSummary,
      upcoming: {
        count: 1,
        truncated: false,
        items: [item({ ticket_id: "t-9", title: "近日チケット", due_date: "2026-06-05", days_until: 3 })]
      }
    };
    render(<RemindersPanel reminders={summary} />);
    expect(screen.getByText("あと3日")).toBeInTheDocument();
  });

  it("bucket が truncated のとき『他に N 件』を表示する (silent truncation 回避、F-001)", () => {
    const summary: ReminderSummary = {
      ...baseSummary,
      overdue: {
        count: 53,
        truncated: true,
        items: [item({ ticket_id: "t-1", title: "先頭超過" })]
      }
    };
    render(<RemindersPanel reminders={summary} />);
    // count 53 - items 1 = 52 件が hidden。
    expect(screen.getByText("他に 52 件")).toBeInTheDocument();
  });

  it("count 0 の bucket は描画しない (空 bucket の見出しを出さない)", () => {
    const summary: ReminderSummary = {
      ...baseSummary,
      overdue: {
        count: 1,
        truncated: false,
        items: [item({ ticket_id: "t-1", title: "唯一超過" })]
      }
    };
    render(<RemindersPanel reminders={summary} />);
    expect(screen.getByRole("heading", { name: "期限超過" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "本日期限" })).not.toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "まもなく期限" })).not.toBeInTheDocument();
  });
});
