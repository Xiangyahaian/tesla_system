import type { CabinStateSnapshot, ConfirmPayload, TraceStep } from "./types";

const jsonHeaders = { "Content-Type": "application/json" };

function actorSessionId(): string {
  try {
    return localStorage.getItem("cabin_auth_session_id") || localStorage.getItem("cabin_session_id") || "";
  } catch {
    return "";
  }
}

export function cabinActorHeaders(init?: HeadersInit): Headers {
  const h = new Headers(init);
  const sid = actorSessionId();
  if (sid) h.set("X-Cabin-Session", sid);
  return h;
}

async function readApiError(res: Response, fallback: string) {
  try {
    const data = (await res.clone().json()) as { error?: string; detail?: string };
    if (data?.error) return String(data.error);
    if (data?.detail) return String(data.detail);
  } catch {
    /* ignore */
  }
  return `${fallback} ${res.status}`;
}

export async function fetchCabinState(sessionId = "default") {
  const res = await fetch(`/api/state?session_id=${encodeURIComponent(sessionId)}`, {
    headers: cabinActorHeaders(),
  });
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
      user_dir?: string;
    };
  }>;
}

export async function resetCabin(sessionId = "default") {
  const res = await fetch(`/api/reset?session_id=${encodeURIComponent(sessionId)}`, {
    method: "POST",
    headers: cabinActorHeaders(),
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
    headers: cabinActorHeaders(jsonHeaders),
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

export async function tickDynamics(sessionId = "default", dt = 0.25, signal?: AbortSignal) {
  const res = await fetch(
    `/api/dynamics/tick?session_id=${encodeURIComponent(sessionId)}&dt=${dt}`,
    { method: "POST", signal, headers: cabinActorHeaders() },
  );
  if (!res.ok) throw new Error(`tick ${res.status}`);
  return res.json() as Promise<{
    ok: boolean;
    state: CabinStateSnapshot;
    data?: Record<string, unknown>;
  }>;
}

export type WeatherPayload = {
  ok?: boolean;
  error?: string;
  summary?: string;
  place?: string;
  weather?: string;
  temperature?: string;
  wind?: string;
  humidity?: string;
  reporttime?: string;
  cached?: boolean;
  ttl_sec?: number;
};

export async function fetchWeather(sessionId = "default", force = false) {
  const qs = new URLSearchParams({
    session_id: sessionId,
    ...(force ? { force: "1" } : {}),
  });
  const res = await fetch(`/api/weather?${qs}`, { headers: cabinActorHeaders() });
  if (!res.ok) throw new Error(await readApiError(res, "weather"));
  return res.json() as Promise<WeatherPayload>;
}

export type PlaceSearchHit = {
  name: string;
  address?: string;
  location?: string;
  type?: string;
  source?: string;
};

export async function searchPlaces(query: string, sessionId = "default", limit = 8) {
  const qs = new URLSearchParams({
    q: query,
    session_id: sessionId,
    limit: String(limit),
  });
  const res = await fetch(`/api/maps/search?${qs}`, { headers: cabinActorHeaders() });
  if (!res.ok) throw new Error(await readApiError(res, "maps search"));
  return res.json() as Promise<{
    ok?: boolean;
    query?: string;
    error?: string;
    pois?: PlaceSearchHit[];
    count?: number;
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
  const res = await fetch("/api/model-status", { signal: AbortSignal.timeout(8000) });
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
  owner_id?: string;
  owner_nickname?: string;
  is_home?: boolean;
  user_dir?: string;
  path?: string;
};

export async function loginUser(nickname: string) {
  const res = await fetch("/api/users/login", {
    method: "POST",
    headers: jsonHeaders,
    body: JSON.stringify({ nickname }),
  });
  const raw = await res.text();
  let parsed: unknown;
  try {
    parsed = raw ? JSON.parse(raw) : {};
  } catch {
    throw new Error(res.ok ? "登录接口返回了网页而不是 JSON" : `登录失败（${res.status}）`);
  }
  const data = parsed as {
    ok?: boolean;
    error?: string;
    nickname?: string;
    session_id?: string;
    title?: string;
    role?: "admin" | "user";
    is_admin?: boolean;
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
    role: "admin" | "user";
    is_admin: boolean;
    users?: UserSummary[];
  };
}

export async function fetchUsers() {
  const res = await fetch("/api/users", { headers: cabinActorHeaders() });
  if (!res.ok) throw new Error(await readApiError(res, "users"));
  return res.json() as Promise<{ ok: boolean; users: UserSummary[] }>;
}

export async function deleteUser(userId: string) {
  const res = await fetch(`/api/users/${encodeURIComponent(userId)}`, {
    method: "DELETE",
    headers: cabinActorHeaders(),
  });
  const data = (await res.json()) as { ok?: boolean; error?: string; users?: UserSummary[] };
  if (!res.ok || !data.ok) throw new Error(data.error || `delete user ${res.status}`);
  return data as { ok: true; nickname?: string; users: UserSummary[] };
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
  session_count?: number;
  is_admin?: boolean;
};

export async function fetchSessions() {
  const res = await fetch("/api/sessions", { headers: cabinActorHeaders() });
  if (!res.ok) throw new Error(await readApiError(res, "sessions"));
  return res.json() as Promise<{ ok: boolean; sessions: SessionSummary[]; is_admin?: boolean; role?: string }>;
}

export async function createSession(title?: string) {
  const res = await fetch("/api/sessions", {
    method: "POST",
    headers: cabinActorHeaders(jsonHeaders),
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(await readApiError(res, "create session"));
  return res.json() as Promise<{
    ok: boolean;
    session_id: string;
    title: string;
    sessions: SessionSummary[];
    state?: CabinStateSnapshot;
  }>;
}

export async function renameSession(sessionId: string, title: string) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "PATCH",
    headers: cabinActorHeaders(jsonHeaders),
    body: JSON.stringify({ title }),
  });
  if (!res.ok) throw new Error(await readApiError(res, "rename session"));
  return res.json() as Promise<{ ok: boolean; session_id: string; title: string; sessions: SessionSummary[] }>;
}

export async function deleteSession(sessionId: string) {
  const res = await fetch(`/api/sessions/${encodeURIComponent(sessionId)}`, {
    method: "DELETE",
    headers: cabinActorHeaders(),
  });
  const data = (await res.json()) as { ok?: boolean; error?: string; sessions?: SessionSummary[] };
  if (!res.ok || !data.ok) throw new Error(data.error || `delete session ${res.status}`);
  return data as { ok: true; session_id: string; sessions: SessionSummary[] };
}

export async function purgeAllSessions() {
  const res = await fetch("/api/sessions/purge", {
    method: "POST",
    headers: cabinActorHeaders(),
  });
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
    { headers: cabinActorHeaders() },
  );
  if (!res.ok) throw new Error(await readApiError(res, "session messages"));
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
    { headers: cabinActorHeaders() },
  );
  if (!res.ok) throw new Error(await readApiError(res, "history"));
  return res.json() as Promise<{
    session_id: string;
    total_returned: number;
    turns: AgentTurnSummary[];
  }>;
}

export async function fetchAgentTurn(turnId: string, sessionId = "default") {
  const res = await fetch(
    `/api/agent/turns/${encodeURIComponent(turnId)}?session_id=${encodeURIComponent(sessionId)}`,
    { headers: cabinActorHeaders() },
  );
  if (!res.ok) throw new Error(await readApiError(res, "turn"));
  return res.json() as Promise<Record<string, unknown>>;
}

export type AgentContextPayload = {
  session_id: string;
  sources: string[];
  total_chars: number;
  system?: string;
  user_context?: string;
  recent_dialog: string;
  user_context_preview: string;
  sections?: { id: string; title: string; chars: number; text: string }[];
};

export async function fetchAgentContext(sessionId = "default") {
  const res = await fetch(`/api/agent/context?session_id=${encodeURIComponent(sessionId)}`, {
    headers: cabinActorHeaders(),
  });
  if (!res.ok) throw new Error(await readApiError(res, "context"));
  return res.json() as Promise<AgentContextPayload>;
}

export async function compactAgent(sessionId = "default", model = "remote") {
  const res = await fetch(
    `/api/agent/compact?session_id=${encodeURIComponent(sessionId)}&model=${encodeURIComponent(model)}`,
    { method: "POST", headers: cabinActorHeaders() },
  );
  if (!res.ok) throw new Error(await readApiError(res, "compact"));
  return res.json();
}

export type AgentLlmPrompt = {
  system?: string;
  user?: string;
  output?: string;
  prompt_chars?: number;
  completion_chars?: number;
  system_chars?: number;
  user_chars?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  token_source?: string;
  model?: string;
  mode?: string;
  elapsed_ms?: number;
};

export type AgentTurnMetrics = {
  llm_used?: boolean;
  llm_calls?: number;
  prompt_chars?: number;
  completion_chars?: number;
  prompt_tokens?: number;
  completion_tokens?: number;
  total_tokens?: number;
  llm_elapsed_ms?: number;
  token_source?: string;
  prompts?: AgentLlmPrompt[];
  context_chars?: number;
  tools?: string[];
  loop_iters?: number;
};

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
  metrics?: AgentTurnMetrics;
  duration_ms?: number;
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
    headers: cabinActorHeaders(jsonHeaders),
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
