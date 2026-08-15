import { create } from "zustand";
import type {
  CabinStateSnapshot,
  ChatMessage,
  ConfirmPayload,
  HmiConfirmPayload,
  TraceStep,
  VoicePhase,
} from "@/lib/types";
import type { RetrievedDoc } from "@/lib/answer";
import { DEFAULT_SEAT, type SeatId } from "@/lib/seats";

export type CabinView = "drive" | "apps" | "agent" | "settings";

type AgentMeta = {
  transcript_chars?: number;
  transcript_messages?: number;
  memory_preview?: string;
  session_dir?: string;
} | null;

type CabinStore = {
  sessionId: string;
  sessionTitle: string;
  userNickname: string;
  model: "remote" | "local";
  phase: VoicePhase;
  view: CabinView;
  messages: ChatMessage[];
  liveText: string;
  liveSteps: TraceStep[];
  contexts: RetrievedDoc[];
  confirm: ConfirmPayload | null;
  hmiConfirm: HmiConfirmPayload | null;
  vehicle: CabinStateSnapshot | null;
  agentMeta: AgentMeta;
  busy: boolean;
  lastError: string | null;
  ttsEnabled: boolean;
  ttsVolume: number;
  activeSeat: SeatId;
  setPhase: (p: VoicePhase) => void;
  setModel: (m: "remote" | "local") => void;
  setView: (v: CabinView) => void;
  setVehicle: (v: CabinStateSnapshot | null) => void;
  setAgentMeta: (a: AgentMeta) => void;
  setConfirm: (c: ConfirmPayload | null) => void;
  setHmiConfirm: (c: HmiConfirmPayload | null) => void;
  setBusy: (b: boolean) => void;
  setError: (e: string | null) => void;
  setLiveText: (t: string) => void;
  appendLiveText: (t: string) => void;
  addLiveStep: (s: TraceStep) => void;
  resetLive: () => void;
  pushMessage: (m: ChatMessage) => void;
  setMessages: (m: ChatMessage[]) => void;
  setContexts: (c: RetrievedDoc[]) => void;
  setTtsEnabled: (v: boolean) => void;
  setTtsVolume: (v: number) => void;
  setActiveSeat: (seat: SeatId) => void;
  setSessionId: (id: string, title?: string) => void;
  setSessionTitle: (title: string) => void;
  setUser: (nickname: string, sessionId: string) => void;
  clearUser: () => void;
  clearChat: () => void;
  mapEpoch: number;
  bumpMapEpoch: () => void;
  /** 车辆状态世代：重置/切会话时递增，丢弃过期的 dynamics tick */
  vehicleEpoch: number;
  bumpVehicleEpoch: () => number;
  /** 重置进行中：暂停应用 dynamics tick */
  resetInFlight: boolean;
  setResetInFlight: (v: boolean) => void;
};

const savedNickname =
  typeof localStorage !== "undefined" ? localStorage.getItem("cabin_user_nickname") || "" : "";
const savedSession =
  typeof localStorage !== "undefined"
    ? localStorage.getItem("cabin_session_id") || (savedNickname ? "default" : "")
    : "";

function readBool(key: string, fallback: boolean) {
  if (typeof localStorage === "undefined") return fallback;
  const v = localStorage.getItem(key);
  if (v == null) return fallback;
  return v === "1" || v === "true";
}

function readNum(key: string, fallback: number) {
  if (typeof localStorage === "undefined") return fallback;
  const v = Number(localStorage.getItem(key));
  return Number.isFinite(v) ? v : fallback;
}

export const useCabinStore = create<CabinStore>((set) => ({
  sessionId: savedNickname ? savedSession : "",
  sessionTitle: savedNickname || "未登录",
  userNickname: savedNickname,
  model: "remote",
  phase: "idle",
  view: "drive",
  messages: [],
  liveText: "",
  liveSteps: [],
  contexts: [],
  confirm: null,
  hmiConfirm: null,
  vehicle: null,
  agentMeta: null,
  busy: false,
  lastError: null,
  ttsEnabled: readBool("cabin_tts_enabled", true),
  ttsVolume: Math.min(1, Math.max(0, readNum("cabin_tts_volume", 0.85))),
  activeSeat: DEFAULT_SEAT,
  setPhase: (phase) => set({ phase }),
  setModel: (model) => set({ model }),
  setView: (view) => set({ view }),
  setVehicle: (vehicle) => set({ vehicle }),
  setAgentMeta: (agentMeta) => set({ agentMeta }),
  setConfirm: (confirm) => set({ confirm }),
  setHmiConfirm: (hmiConfirm) => set({ hmiConfirm }),
  setBusy: (busy) => set({ busy }),
  setError: (lastError) => set({ lastError }),
  setLiveText: (liveText) => set({ liveText }),
  appendLiveText: (t) => set((s) => ({ liveText: s.liveText + t })),
  addLiveStep: (step) => set((s) => ({ liveSteps: [...s.liveSteps, step] })),
  resetLive: () => set({ liveText: "", liveSteps: [], contexts: [] }),
  pushMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setMessages: (messages) => set({ messages }),
  setContexts: (contexts) => set({ contexts }),
  setTtsEnabled: (ttsEnabled) => {
    try {
      localStorage.setItem("cabin_tts_enabled", ttsEnabled ? "1" : "0");
    } catch {
      /* ignore */
    }
    set({ ttsEnabled });
  },
  setTtsVolume: (ttsVolume) => {
    const v = Math.min(1, Math.max(0, ttsVolume));
    try {
      localStorage.setItem("cabin_tts_volume", String(v));
    } catch {
      /* ignore */
    }
    set({ ttsVolume: v });
  },
  setActiveSeat: (activeSeat) => set({ activeSeat }),
  setSessionId: (sessionId, title) => {
    try {
      localStorage.setItem("cabin_session_id", sessionId);
    } catch {
      /* ignore */
    }
    set({
      sessionId,
      sessionTitle: title || sessionId,
    });
  },
  setSessionTitle: (sessionTitle) => set({ sessionTitle }),
  setUser: (nickname, sessionId) => {
    try {
      localStorage.setItem("cabin_user_nickname", nickname);
      localStorage.setItem("cabin_session_id", sessionId);
    } catch {
      /* ignore */
    }
    set({
      userNickname: nickname,
      sessionId,
      sessionTitle: nickname,
    });
  },
  clearUser: () => {
    try {
      localStorage.removeItem("cabin_user_nickname");
      localStorage.removeItem("cabin_session_id");
    } catch {
      /* ignore */
    }
    set({
      userNickname: "",
      sessionId: "",
      sessionTitle: "未登录",
      messages: [],
      vehicle: null,
      liveText: "",
      liveSteps: [],
      contexts: [],
      confirm: null,
      hmiConfirm: null,
      agentMeta: null,
      phase: "idle",
    });
  },
  clearChat: () =>
    set({
      messages: [],
      liveText: "",
      liveSteps: [],
      contexts: [],
      confirm: null,
      hmiConfirm: null,
      lastError: null,
      phase: "idle",
    }),
  mapEpoch: 0,
  bumpMapEpoch: () => set((s) => ({ mapEpoch: s.mapEpoch + 1 })),
  vehicleEpoch: 0,
  bumpVehicleEpoch: () => {
    let next = 0;
    set((s) => {
      next = s.vehicleEpoch + 1;
      return { vehicleEpoch: next };
    });
    return next;
  },
  resetInFlight: false,
  setResetInFlight: (resetInFlight) => set({ resetInFlight }),
}));
