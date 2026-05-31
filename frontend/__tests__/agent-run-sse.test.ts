import { afterEach, describe, expect, it, vi } from "vitest";

import {
  subscribeAgentRunStream,
  type SseEvent,
  type SseStatus,
  type SseStreamState,
} from "@/lib/realtime/agent-run-sse";

// ADR-00038 (L-3 realtime) fetch-based SSE client の core 挙動 test。
// 204 恒久停止 (storm 防止) / agent_run_event parse + stream_end(terminal) 停止 / status parse /
// stream_end(terminal) で再接続しないこと。backoff 待ちを避けるため terminal/204 経路のみ検証。

function sseResponse(frames: string[]): Response {
  const stream = new ReadableStream<Uint8Array>({
    start(controller) {
      const encoder = new TextEncoder();
      for (const frame of frames) {
        controller.enqueue(encoder.encode(frame));
      }
      controller.close();
    },
  });
  return new Response(stream, { status: 200 });
}

function frame(event: string, data: unknown, id?: number): string {
  const idLine = id === undefined ? "" : `id: ${id}\n`;
  return `${idLine}event: ${event}\ndata: ${JSON.stringify(data)}\n\n`;
}

async function until(condition: () => boolean, timeout = 1500): Promise<void> {
  const start = Date.now();
  while (!condition() && Date.now() - start < timeout) {
    await new Promise((resolve) => setTimeout(resolve, 5));
  }
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("subscribeAgentRunStream", () => {
  it("204 (flag-off) で再接続せず closed になる", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(null, { status: 204 }));
    vi.stubGlobal("fetch", fetchMock);
    const states: SseStreamState[] = [];

    const cleanup = subscribeAgentRunStream("run-1", { onState: (s) => states.push(s) });
    await until(() => states.includes("closed"));
    cleanup();

    expect(states).toContain("closed");
    expect(fetchMock).toHaveBeenCalledTimes(1); // 204 → 再接続しない
  });

  it("agent_run_event を parse し stream_end(terminal) で停止 (再接続なし)", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        frame(
          "agent_run_event",
          {
            event_id: "e1",
            seq_no: 5,
            event_type: "run_completed",
            actor_id: "a1",
            payload_keys: ["result"],
            payload_redaction_status: "keys_only",
            created_at: null,
          },
          5
        ),
        frame("stream_end", { reason: "terminal" }),
      ])
    );
    vi.stubGlobal("fetch", fetchMock);
    const events: SseEvent[] = [];
    const states: SseStreamState[] = [];

    const cleanup = subscribeAgentRunStream("run-1", {
      onEvent: (e) => events.push(e),
      onState: (s) => states.push(s),
    });
    await until(() => states.includes("closed"));
    cleanup();

    expect(events).toHaveLength(1);
    expect(events[0]?.event_type).toBe("run_completed");
    expect(events[0]?.seq_no).toBe(5);
    expect(events[0]?.payload_keys).toEqual(["result"]);
    expect(states).toContain("open");
    expect(states).toContain("closed");
    expect(fetchMock).toHaveBeenCalledTimes(1); // terminal → 再接続なし
  });

  it("agent_run_status を parse する", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      sseResponse([
        frame("agent_run_status", {
          status: "running",
          blocked_reason: null,
          terminal: false,
          completed_at: null,
          error_code: null,
        }),
        frame("agent_run_status", {
          status: "blocked",
          blocked_reason: "policy_blocked",
          terminal: false,
          completed_at: null,
          error_code: null,
        }),
        frame("stream_end", { reason: "terminal" }),
      ])
    );
    vi.stubGlobal("fetch", fetchMock);
    const statuses: SseStatus[] = [];
    const states: SseStreamState[] = [];

    const cleanup = subscribeAgentRunStream("run-1", {
      onStatus: (s) => statuses.push(s),
      onState: (s) => states.push(s),
    });
    await until(() => states.includes("closed"));
    cleanup();

    expect(statuses.map((s) => s.status)).toEqual(["running", "blocked"]);
    expect(statuses[1]?.blocked_reason).toBe("policy_blocked");
  });

  it("初回接続は ?last_event_id= を付けて proxy を叩く", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValue(sseResponse([frame("stream_end", { reason: "terminal" })]));
    vi.stubGlobal("fetch", fetchMock);
    const states: SseStreamState[] = [];

    const cleanup = subscribeAgentRunStream("run-xyz", {
      initialLastEventId: 7,
      onState: (s) => states.push(s),
    });
    await until(() => states.includes("closed"));
    cleanup();

    const url = String(fetchMock.mock.calls[0]?.[0]);
    expect(url).toBe("/api/proxy/agent_runs/run-xyz/stream?last_event_id=7");
  });
});
