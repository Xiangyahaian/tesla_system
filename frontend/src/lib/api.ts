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
    agent?: {
      transcript_chars?: number;
      transcript_messages?: number;
      memory_preview?: string;
      session_dir?: string;
    };
  }>;
}

export async function resetCabin(sessionId = "default") {
  const res = await fetch(`/api/reset?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
  });
  if (!res.ok) throw new Error(`reset ${res.status}`);
  return res.json() as Promise<{
    success: boolean;
    message: string;
    state: CabinStateSnapshot;
  }>;
}

export async function executeControl(
  tool: string,
  arguments_: Record<string, unknown> = {},
  sessionId = "default",
) {
  const res = await fetch("/api/control", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({
      tool,
      arguments: arguments_,
      session_id: sessionId,
    }),
  });
  if (!res.ok) throw new Error(`control ${res.status}`);
  return res.json() as Promise<{
    ok: boolean;
    message: string;
    data?: Record<string, unknown>;
    tool: string;
    state: CabinStateSnapshot;
    error?: string;
  }>;
}

export async function tickDynamics(sessionId = "default", dt = 0.25) {
  const res = await fetch(
    `/api/dynamics/tick?session_id=${encodeURIComponent(sessionId)}&dt=${dt}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`tick ${res.status}`);
  return res.json() as Promise<{
    ok: boolean;
    state: CabinStateSnapshot;
    data?: Record<string, unknown>;
  }>;
}

export async function fetchApps() {
  const res = await fetch("/api/apps");
  if (!res.ok) throw new Error(`apps ${res.status}`);
  return res.json() as Promise<{
    count: number;
    apps: { name: string; category: string; aliases?: string[] }[];
    categories: string[];
    note?: string;
  }>;
}

export async function fetchTools() {
  const res = await fetch("/api/tools");
  if (!res.ok) throw new Error(`tools ${res.status}`);
  return res.json() as Promise<{
    tools: {
      name: string;
      description: string;
      risk: string;
      domain: string;
      schema?: Record<string, unknown>;
    }[];
  }>;
}

export async function fetchAmapConfig() {
  const res = await fetch("/api/maps/config");
  if (!res.ok) throw new Error(`maps config ${res.status}`);
  return res.json() as Promise<{
    ok: boolean;
    provider: string;
    configured: boolean;
    js_key: string;
    security_code: string;
    origin: { name: string; lng: number; lat: number; location: string; address?: string };
  }>;
}

export async function fetchModelStatus() {
  const res = await fetch("/api/model-status");
  if (!res.ok) throw new Error(`model-status ${res.status}`);
  return res.json() as Promise<Record<string, unknown>>;
}

export type SessionSummary = {
  session_id: string;
  title: string;
  created_at?: number;
  updated_at?: number;
  last_active?: number;
  status?: string;
  message_count?: number;
  turn_count?: number;
  transcript_chars?: number;
  preview?: string;
  has_vehicle?: boolean;
  has_transcript?: boolean;
};

export async function loginUser(nickname: string) {
  const res = await fetch("/api/users/login", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ nickname }),
  });
  const data = (await res.json()) as {
    ok?: boolean;
    error?: string;
    nickname?: string;
    session_id?: string;
    title?: string;
    users?: UserSummary[];
  };
  if (!res.ok || !data.ok || !data.session_id) {
    throw new Error(data.error || `login ${res.status}`);
  }
  return data as {
    ok: true;
    nickname: string;
    session_id: string;
    title: string;
    users: UserSummary[];
  };
}

export async function fetchUsers() {
  const res = await fetch("/api/users");
  if (!res.ok) throw new Error(`users ${res.status}`);
  return res.json() as Promise<{ ok: boolean; users: UserSummary[] }>;
}

export type UserSummary = {
  id?: string;
  session_id: string;
  nickname: string;
  title?: string;
  created_at?: number | null;
  last_login_at?: number | null;
  login_count?: number;
  updated_at?: number | string | null;
};

export async function fetchSessions() {
  const res = await fetch("/api/sessions");
  if (!res.ok) throw new Error(`sessions ${res.status}`);
  return res.json() as Promise<{ ok: boolean; sessions: SessionSummary[] }>;
}

export async function createSession(title?: string) {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`create session ${res.status}`);
  return res.json() as Promise<{
    ok: boolean;
    session_id: string;
    title: string;
    sessions: SessionSummary[];
  }>;
}

export async function renameSession(sessionId: string, title: string) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    headers: jsonHeaders,
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(`rename session ${res.status}`);
  return res.json() as Promise<{ ok: boolean; session_id: string; title: string; sessions: SessionSummary[] }>;
}

export async function deleteSession(sessionId: string) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, { method: "DELETE" });
  const data = (await res.json()) as { ok?: boolean; error?: string; sessions?: SessionSummary[] };
  if (!res.ok || !data.ok) throw new Error(data.error || `delete session ${res.status}`);
  return data as { ok: true; session_id: string; sessions: SessionSummary[] };
}

export async function purgeAllSessions() {
  const res = await fetch("/api/sessions/purge", { method: "POST" });
  const data = (await res.json()) as {
    ok?: boolean;
    error?: string;
    count?: number;
    deleted?: string[];
    sessions?: SessionSummary[];
  };
  if (!res.ok || !data.ok) throw new Error(data.error || `purge sessions ${res.status}`);
  return data as {
    ok: true;
    count: number;
    deleted: string[];
    sessions: SessionSummary[];
  };
}

export async function fetchSessionMessages(sessionId = "default", limit = 200) {
  const res = await fetch(
    `/api/sessions/${encodeURIComponent(sessionId)}/messages?limit=${limit}`,
  );
  if (!res.ok) throw new Error(`session messages ${res.status}`);
  return res.json() as Promise<{
    ok: boolean;
    session_id: string;
    title: string;
    total: number;
    messages: { role: string; content: string; ts?: number; meta?: Record<string, unknown> }[];
  }>;
}

export async function transcribeAudio(file: Blob | File) {
  const form = new FormData();
  form.append("audio", file, file instanceof File ? file.name : "voice.webm");
  const res = await fetch("/api/asr", { method: "POST", body: form });
  const data = (await res.json()) as { ok?: boolean; text?: string; error?: string; model?: string };
  if (!res.ok || !data.ok) throw new Error(data.error || `asr ${res.status}`);
  return data as { ok: true; text: string; model?: string };
}

export async function synthesizeSpeech(text: string, voice?: string, emotion?: string) {
  const res = await fetch("/api/tts", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ text, voice, emotion }),
  });
  const data = (await res.json()) as {
    ok?: boolean;
    audio_base64?: string;
    mime?: string;
    error?: string;
    model?: string;
    voice?: string;
    emotion?: string;
  };
  if (!res.ok || !data.ok || !data.audio_base64) {
    throw new Error(data.error || `tts ${res.status}`);
  }
  return data as {
    ok: true;
    audio_base64: string;
    mime: string;
    model?: string;
    voice?: string;
    emotion?: string;
  };
}

export async function fetchAgentHistory(sessionId = "default", limit = 40) {
  const res = await fetch(
    `/api/agent/history?session_id=${encodeURIComponent(sessionId)}&limit=${limit}`,
  );
  if (!res.ok) throw new Error(`history ${res.status}`);
  return res.json() as Promise<{
    session_id: string;
    total_returned: number;
    turns: AgentTurnSummary[];
  }>;
}

export async function fetchAgentTurn(turnId: string, sessionId = "default") {
  const res = await fetch(
    `/api/agent/turns/${encodeURIComponent(turnId)}?session_id=${encodeURIComponent(sessionId)}`,
  );
  if (!res.ok) throw new Error(`turn ${res.status}`);
  return res.json() as Promise<Record<string, unknown>>;
}

export async function fetchAgentContext(sessionId = "default") {
  const res = await fetch(`/api/agent/context?session_id=${encodeURIComponent(sessionId)}`);
  if (!res.ok) throw new Error(`context ${res.status}`);
  return res.json() as Promise<{
    session_id: string;
    sources: string[];
    total_chars: number;
    recent_dialog: string;
    user_context_preview: string;
  }>;
}

export async function compactAgent(sessionId = "default", model = "remote") {
  const res = await fetch(
    `/api/agent/compact?session_id=${encodeURIComponent(sessionId)}&model=${encodeURIComponent(model)}`,
    { method: "POST" },
  );
  if (!res.ok) throw new Error(`compact ${res.status}`);
  return res.json();
}

export type AgentTurnSummary = {
  turn_id?: string;
  id?: string;
  started_at?: number;
  ended_at?: number;
  query?: string;
  user_query?: string;
  answer_preview?: string;
  intent?: string;
  status?: string;
  steps?: TraceStep[];
  step_count?: number;
  tool_names?: string[];
};

export type StreamHandlers = {
  onToken?: (text: string) => void;
  onTrace?: (step: TraceStep) => void;
  onIntent?: (data: Record<string, unknown>) => void;
  onConfirm?: (data: ConfirmPayload) => void;
  onContext?: (items: unknown) => void;
  onTurn?: (data: Record<string, unknown>) => void;
  onFinal?: (data: Record<string, unknown>) => void;
  onStatus?: (text: string) => void;
  onError?: (message: string) => void;
  onActiveSeat?: (data: { active_seat?: string; active_seat_cn?: string; source?: string }) => void;
  onMemory?: (data: Record<string, unknown>) => void;
};

export async function streamChat(
  query: string,
  opts: {
    sessionId?: string;
    model?: string;
    confirm?: boolean | null;
    activeSeat?: string;
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
      active_seat: opts.activeSeat ?? "front_left",
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
          opts.onContext?.(payload.data);
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
        case "active_seat":
          opts.onActiveSeat?.(payload.data as { active_seat?: string; active_seat_cn?: string; source?: string });
          break;
        case "memory":
          opts.onMemory?.(payload.data as Record<string, unknown>);
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
