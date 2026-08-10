import type { CabinStateSnapshot, ConfirmPayload, TraceStep } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

export async function fetchCabinState(sessionId = "default") {
  const res = await fetch(`/api/state?session_id=${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`state ${res.status}`);
  return res.json() as Promise<{
    session_id: string;
    state: CabinStateSnapshot;
    pending: ConfirmPayload | null;
    slots: Record<string, unknown>;
    agent?: Record<string, unknown>;
  }>;
}

export async function resetCabin(sessionId = "default") {
  const res = await fetch(`/api/reset?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`reset ${res.status}`);
  return res.json();
}

export async function fetchApps() {
  const res = await fetch("/api/apps");
  if (!res.ok) throw new Error(`apps ${res.status}`);
  return res.json() as Promise<{ count: number; apps: { name: string; category: string }[] }>;
}

export type StreamHandlers = {
  onToken?: (text: string) => void;
  onTrace?: (step: TraceStep) => void;
  onIntent?: (data: Record<string, unknown>) => void;
  onConfirm?: (data: ConfirmPayload) => void;
  onContext?: (items: string[]) => void;
  onTurn?: (data: Record<string, unknown>) => void;
  onFinal?: (data: Record<string, unknown>) => void;
  onStatus?: (text: string) => void;
  onError?: (message: string) => void;
};

export async function streamChat(
  query: string,
  opts: {
    sessionId?: string;
    model?: string;
    confirm?: boolean | null;
    signal?: AbortSignal;
  } & StreamHandlers,
) {
  const res = await fetch("/api/chat", {
    method: "POST",
    headers: jsonHeaders,
    signal: opts.signal,
    body: JSON.stringify({
      query,
      session_id: opts.sessionId ?? "default",
      model: opts.model ?? "remote",
      confirm: opts.confirm ?? null,
    }),
  });
  if (!res.ok || !res.body) throw new Error(`chat ${res.status}`);

  const reader = res.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    const lines = buffer.split("\n");
    buffer = lines.pop() ?? "";
    for (const line of lines) {
      if (!line.trim()) continue;
      let payload: { type: string; data: unknown };
      try {
        payload = JSON.parse(line);
      } catch {
        continue;
      }
      switch (payload.type) {
        case "token":
          opts.onToken?.(String(payload.data ?? ""));
          break;
        case "trace":
          opts.onTrace?.(payload.data as TraceStep);
          break;
        case "intent":
          opts.onIntent?.(payload.data as Record<string, unknown>);
          break;
        case "confirm":
          opts.onConfirm?.(payload.data as ConfirmPayload);
          break;
        case "context":
          opts.onContext?.(payload.data as string[]);
          break;
        case "turn":
          opts.onTurn?.(payload.data as Record<string, unknown>);
          break;
        case "final":
          opts.onFinal?.(payload.data as Record<string, unknown>);
          break;
        case "status":
          opts.onStatus?.(String(payload.data ?? ""));
          break;
        case "error":
          opts.onError?.(String(payload.data ?? "error"));
          break;
        default:
          break;
      }
    }
  }
}
