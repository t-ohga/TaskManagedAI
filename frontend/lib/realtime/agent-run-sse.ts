import { z } from "zod";

// ADR-00038 (L-3 SSE realtime) browser SSE client。
// native EventSource は (a) HTTP error status を app に渡さず無制限 auto-reconnect、(b) close/
// 再作成で Last-Event-ID header を再送できない、の 2 制約があるため (R3/R4)、fetch + ReadableStream
// ベースの client で reconnect と resume を app が完全制御する:
//   - resume: 受信した最後の seq_no を保持し (再)接続時に ?last_event_id= で渡す。
//   - reconnect: 指数バックオフ (jitter) + 最大試行、204/404=恒久停止、422=resume reset、
//     stream_end(terminal/scope_revoked)=恒久停止、max_lifetime/server_shutdown/error=再接続。

export const sseEventSchema = z.object({
  event_id: z.string(),
  seq_no: z.number(),
  event_type: z.string(),
  actor_id: z.string(),
  payload_keys: z.array(z.string()),
  payload_redaction_status: z.enum(["keys_only", "blocked_by_secret_scan"]),
  created_at: z.string().nullable(),
});
export type SseEvent = z.infer<typeof sseEventSchema>;

export const sseStatusSchema = z.object({
  status: z.string(),
  blocked_reason: z.string().nullable(),
  terminal: z.boolean(),
  completed_at: z.string().nullable(),
  error_code: z.string().nullable(),
});
export type SseStatus = z.infer<typeof sseStatusSchema>;

const streamEndSchema = z.object({ reason: z.string() });

export type SseStreamState = "connecting" | "open" | "reconnecting" | "closed" | "error";

export type SubscribeOptions = {
  initialLastEventId?: number;
  onEvent?: (event: SseEvent) => void;
  onStatus?: (status: SseStatus) => void;
  onState?: (state: SseStreamState) => void;
};

const MAX_ATTEMPTS = 6;
const BASE_DELAY_MS = 1000;
const MAX_DELAY_MS = 30000;
// 200 stream がこの時間以上継続したら「安定」とみなし retry budget をリセットする。
// 短命な flapping 200 stream (受理直後 close / server_shutdown 連発) では reset せず
// attempts を増やし MAX_ATTEMPTS で停止させる (code-review #2: 無限 reconnect 防止)。
const STABLE_STREAM_MS = 10000;

type FrameAction = "continue" | "stop" | "reconnect";

/**
 * AgentRun の SSE stream を subscribe する。返り値の cleanup 関数で abort する (component unmount)。
 */
export function subscribeAgentRunStream(runId: string, opts: SubscribeOptions): () => void {
  const controller = new AbortController();
  let lastEventId = opts.initialLastEventId ?? 0;
  let attempts = 0;
  let stopped = false;

  const setState = (state: SseStreamState): void => opts.onState?.(state);

  function handleFrame(rawFrame: string): FrameAction {
    let eventName = "message";
    const dataLines: string[] = [];
    for (const line of rawFrame.split("\n")) {
      if (line.startsWith(":")) continue; // comment / heartbeat
      if (line.startsWith("event:")) {
        eventName = line.slice(6).trim();
      } else if (line.startsWith("data:")) {
        dataLines.push(line.slice(5).replace(/^ /, ""));
      }
      // server framing の `id:` 行 (agent_run_event のみ) は無視。resume cursor は DTO の seq_no。
    }
    if (dataLines.length === 0) return "continue";
    let parsed: unknown;
    try {
      parsed = JSON.parse(dataLines.join("\n"));
    } catch {
      return "continue";
    }

    if (eventName === "agent_run_event") {
      const result = sseEventSchema.safeParse(parsed);
      if (result.success) {
        lastEventId = Math.max(lastEventId, result.data.seq_no);
        opts.onEvent?.(result.data);
      }
      return "continue";
    }
    if (eventName === "agent_run_status") {
      const result = sseStatusSchema.safeParse(parsed);
      if (result.success) opts.onStatus?.(result.data);
      return "continue";
    }
    if (eventName === "agent_run_error") {
      return "reconnect"; // retryable error → backoff 再接続
    }
    if (eventName === "stream_end") {
      const result = streamEndSchema.safeParse(parsed);
      const reason = result.success ? result.data.reason : "";
      // terminal / scope_revoked は恒久停止。max_lifetime / server_shutdown は再接続。
      return reason === "terminal" || reason === "scope_revoked" ? "stop" : "reconnect";
    }
    return "continue";
  }

  async function readStream(body: ReadableStream<Uint8Array>): Promise<{ permanentStop: boolean }> {
    const reader = body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    try {
      for (;;) {
        const { done, value } = await reader.read();
        if (done) return { permanentStop: false }; // stream_end 無しに切断 → 再接続
        buffer += decoder.decode(value, { stream: true });
        let separator = buffer.indexOf("\n\n");
        while (separator !== -1) {
          const frame = buffer.slice(0, separator);
          buffer = buffer.slice(separator + 2);
          const action = handleFrame(frame);
          if (action === "stop") return { permanentStop: true };
          if (action === "reconnect") return { permanentStop: false };
          separator = buffer.indexOf("\n\n");
        }
      }
    } catch {
      return { permanentStop: false };
    } finally {
      reader.releaseLock();
    }
  }

  async function backoff(): Promise<boolean> {
    attempts += 1;
    if (attempts > MAX_ATTEMPTS) {
      setState("error");
      return false;
    }
    const base = Math.min(MAX_DELAY_MS, BASE_DELAY_MS * 2 ** (attempts - 1));
    const delay = base * (0.5 + Math.random());
    await sleep(delay, controller.signal);
    return !stopped && !controller.signal.aborted;
  }

  async function run(): Promise<void> {
    while (!stopped && !controller.signal.aborted) {
      setState(attempts === 0 ? "connecting" : "reconnecting");
      let response: Response;
      try {
        response = await fetch(
          `/api/proxy/agent_runs/${runId}/stream?last_event_id=${lastEventId}`,
          { signal: controller.signal, headers: { Accept: "text/event-stream" } }
        );
      } catch {
        if (controller.signal.aborted) return;
        if (!(await backoff())) return;
        continue;
      }

      if (response.status === 204 || response.status === 404) {
        setState("closed"); // flag-off / gone → 恒久停止
        return;
      }
      if (response.status === 400 || response.status === 422) {
        if (lastEventId === 0) {
          setState("error");
          return;
        }
        lastEventId = 0; // resume reset → 即再試行
        continue;
      }
      if (response.status !== 200 || response.body === null) {
        if (!(await backoff())) return; // 503 等 transient
        continue;
      }

      setState("open");
      const streamStart = Date.now();
      const outcome = await readStream(response.body);
      if (stopped || controller.signal.aborted) return;
      if (outcome.permanentStop) {
        setState("closed");
        return;
      }
      // stream が安定継続した場合のみ retry budget をリセット (code-review #2)。
      if (Date.now() - streamStart >= STABLE_STREAM_MS) {
        attempts = 0;
      }
      if (!(await backoff())) return;
    }
  }

  void run().catch(() => setState("error"));

  return () => {
    stopped = true;
    controller.abort();
  };
}

function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(resolve, ms);
    signal.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        resolve();
      },
      { once: true }
    );
  });
}
