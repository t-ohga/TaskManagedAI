// C-5 R2-R6 (Codex adversarial HIGH 回帰 test): 編集フォームの表示正本の優先順位。
// 保存成功 snapshot (PATCH response = DB truth) と server props (refresh 由来) の新旧を
// updated_at version で決める。古い成功 snapshot が「より新しい props」(外部更新) を
// 恒久遮断して次の submit で DB を巻き戻す経路を封鎖する。
// R6: helper は action state ではなく「保持済み snapshot (null 可)」を取る。component は
// last-ok snapshot を action state と独立に保持するため、ok→error 遷移でも snapshot は
// 失われない (本 test は snapshot が渡され続ける前提での優先順位を固定する)。
import { describe, expect, it } from "vitest";

import {
  resolveServerTicket,
  timestampOrderKey,
  type EditableTicket
} from "../app/(admin)/tickets/[id]/_components/edit-ticket-form";
import type { UpdatedTicketSnapshot } from "../app/(admin)/tickets/[id]/actions";

const TICKET_ID = "00000000-0000-4000-8000-00000000e001";

function ticketAt(updatedAt: string, status = "open"): EditableTicket {
  return {
    id: TICKET_ID,
    title: "props title",
    description: null,
    due_date: null,
    status,
    priority: null,
    assignee_actor_id: null,
    updated_at: updatedAt
  };
}

function snapshotAt(updatedAt: string, status = "in_progress"): UpdatedTicketSnapshot {
  return {
    id: TICKET_ID,
    title: "snapshot title",
    description: "from snapshot",
    due_date: null,
    status,
    priority: "high",
    assignee_actor_id: null,
    updated_at: updatedAt
  };
}

describe("resolveServerTicket (C-5 R2-R6)", () => {
  it("snapshot が無い (保存前 / idle / error 初回) は props を正本にする", () => {
    const props = ticketAt("2026-06-10T00:00:00Z");
    expect(resolveServerTicket(null, props)).toBe(props);
  });

  it("成功直後 (snapshot が props より新しい) は snapshot を正本にする — stale window ゼロ化", () => {
    const props = ticketAt("2026-06-10T00:00:00Z", "open");
    const snapshot = snapshotAt("2026-06-10T00:00:05Z", "in_progress");
    const resolved = resolveServerTicket(snapshot, props);
    expect(resolved.status).toBe("in_progress");
    expect(resolved.updated_at).toBe("2026-06-10T00:00:05Z");
  });

  it("refresh が snapshot と同一更新の props を運んだら snapshot を維持する (同値、remount 不要)", () => {
    const props = ticketAt("2026-06-10T00:00:05Z", "in_progress");
    const snapshot = snapshotAt("2026-06-10T00:00:05Z", "in_progress");
    expect(resolveServerTicket(snapshot, props).status).toBe("in_progress");
  });

  it("外部更新でより新しい props が来たら snapshot を捨てて props に戻る (巻き戻し封鎖)", () => {
    // 例: 保存後に同画面の TicketStatusChanger が blocked へ変更 → refresh で props が更新。
    const newerProps = ticketAt("2026-06-10T00:01:00Z", "blocked");
    const staleSnapshot = snapshotAt("2026-06-10T00:00:05Z", "in_progress");
    const resolved = resolveServerTicket(staleSnapshot, newerProps);
    expect(resolved).toBe(newerProps);
    expect(resolved.status).toBe("blocked");
  });

  it("ok→error 遷移後も保持された snapshot は stale props より優先される (R6 再入口封鎖)", () => {
    // component は last-ok snapshot を action state と独立に保持する。次 submit が error に
    // なっても snapshot は渡され続け、refresh 前の stale props (旧 status) で remount しない。
    const stalePropsBeforeRefresh = ticketAt("2026-06-10T00:00:00Z", "open");
    const retainedSnapshot = snapshotAt("2026-06-10T00:00:05Z", "in_progress");
    const resolved = resolveServerTicket(retainedSnapshot, stalePropsBeforeRefresh);
    expect(resolved.status).toBe("in_progress");
  });

  it("別 ticket の props には snapshot を適用しない (R3 id mismatch guard)", () => {
    const otherProps = {
      ...ticketAt("2026-06-09T00:00:00Z", "open"),
      id: "00000000-0000-4000-8000-00000000e002"
    };
    const staleSnapshot = snapshotAt("2026-06-10T00:00:05Z", "in_progress");
    expect(resolveServerTicket(staleSnapshot, otherProps)).toBe(otherProps);
  });

  it("offset 混在 timestamp でも時系列で判定する (R4: epoch 比較、文字列順に依存しない)", () => {
    // snapshot "2026-06-10T00:30:00+09:00" = 2026-06-09T15:30Z。
    // props    "2026-06-09T16:00:00Z" の方が時系列では新しいが、文字列比較では snapshot が勝って
    // しまう形。epoch 比較なら props (新しい外部更新) が正本になる。
    const newerPropsUtc = ticketAt("2026-06-09T16:00:00Z", "blocked");
    const olderSnapshotJst = snapshotAt("2026-06-10T00:30:00+09:00", "in_progress");
    expect(resolveServerTicket(olderSnapshotJst, newerPropsUtc)).toBe(newerPropsUtc);

    // 逆向き: snapshot (JST 表記) の方が時系列で新しいなら snapshot が勝つ。
    const olderPropsUtc = ticketAt("2026-06-09T15:00:00Z", "open");
    const newerSnapshotJst = snapshotAt("2026-06-10T00:30:00+09:00", "in_progress");
    expect(resolveServerTicket(newerSnapshotJst, olderPropsUtc).status).toBe("in_progress");
  });

  it("同一 millisecond 内の microsecond 差も時系列で判定する (R5: backend は µs 精度)", () => {
    // PostgreSQL timestamptz は microsecond 精度。Date.parse (ms) では同値になる pair で、
    // props (.123999) が snapshot (.123000) より新しい → props 勝ち。
    const newerPropsMicro = ticketAt("2026-06-10T00:00:00.123999+00:00", "blocked");
    const olderSnapshotMicro = snapshotAt("2026-06-10T00:00:00.123000+00:00", "in_progress");
    expect(resolveServerTicket(olderSnapshotMicro, newerPropsMicro)).toBe(newerPropsMicro);

    // 逆向き: snapshot (.123999) の方が新しいなら snapshot 勝ち。
    const olderPropsMicro = ticketAt("2026-06-10T00:00:00.123000+00:00", "open");
    const newerSnapshotMicro = snapshotAt("2026-06-10T00:00:00.123999+00:00", "in_progress");
    expect(resolveServerTicket(newerSnapshotMicro, olderPropsMicro).status).toBe("in_progress");
  });

  it("snapshot の updated_at が parse 不能なら props に倒れる (R4 fail-closed)", () => {
    const props = ticketAt("2026-06-10T00:00:00Z", "open");
    const broken = snapshotAt("not-a-timestamp", "in_progress");
    expect(resolveServerTicket(broken, props)).toBe(props);
  });

  // note (R3): props.updated_at が null/欠落で「順序不明」になる経路は、loadTicket の strict
  // validate (必須 + parseable timestamp、fail-closed throw) + EditableTicket.updated_at: string
  // により**型レベルで存在しない**。null props が外部更新を運ぶ runtime ケースは構造的に不能。
});

describe("timestampOrderKey (C-5 R4/R5)", () => {
  it("offset を正規化し、µs fraction を順序に反映する", () => {
    expect(timestampOrderKey("2026-06-10T00:30:00+09:00")).toBe(
      timestampOrderKey("2026-06-09T15:30:00Z")
    );
    expect(
      timestampOrderKey("2026-06-10T00:00:00.123999Z") >
        timestampOrderKey("2026-06-10T00:00:00.123000Z")
    ).toBe(true);
    expect(Number.isNaN(timestampOrderKey("junk"))).toBe(true);
  });
});
