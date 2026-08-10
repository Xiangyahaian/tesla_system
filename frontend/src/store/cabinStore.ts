import { create } from "zustand";
import type {
  CabinStateSnapshot,
  ChatMessage,
  ConfirmPayload,
  TraceStep,
  VoicePhase,
} from "@/lib/types";

export type CabinView = "drive" | "apps" | "agent" | "settings";

type AgentMeta = {
  transcript_chars?: number;
  transcript_messages?: number;
  memory_preview?: string;
  session_dir?: string;
} | null;

type CabinStore = {
  sessionId: string;
  model: "remote" | "local";
  phase: VoicePhase;
  view: CabinView;
  messages: ChatMessage[];
  liveText: string;
  liveSteps: TraceStep[];
  contexts: string[];
  confirm: ConfirmPayload | null;
  vehicle: CabinStateSnapshot | null;
  agentMeta: AgentMeta;
  busy: boolean;
  lastError: string | null;
  ttsEnabled: boolean;
  setPhase: (p: VoicePhase) => void;
  setModel: (m: "remote" | "local") => void;
  setView: (v: CabinView) => void;
  setVehicle: (v: CabinStateSnapshot | null) => void;
  setAgentMeta: (a: AgentMeta) => void;
  setConfirm: (c: ConfirmPayload | null) => void;
  setBusy: (b: boolean) => void;
  setError: (e: string | null) => void;
  setLiveText: (t: string) => void;
  appendLiveText: (t: string) => void;
  addLiveStep: (s: TraceStep) => void;
  resetLive: () => void;
  pushMessage: (m: ChatMessage) => void;
  setContexts: (c: string[]) => void;
  setTtsEnabled: (v: boolean) => void;
  clearChat: () => void;
};

export const useCabinStore = create<CabinStore>((set) => ({
  sessionId: "default",
  model: "remote",
  phase: "idle",
  view: "drive",
  messages: [],
  liveText: "",
  liveSteps: [],
  contexts: [],
  confirm: null,
  vehicle: null,
  agentMeta: null,
  busy: false,
  lastError: null,
  ttsEnabled: true,
  setPhase: (phase) => set({ phase }),
  setModel: (model) => set({ model }),
  setView: (view) => set({ view }),
  setVehicle: (vehicle) => set({ vehicle }),
  setAgentMeta: (agentMeta) => set({ agentMeta }),
  setConfirm: (confirm) => set({ confirm }),
  setBusy: (busy) => set({ busy }),
  setError: (lastError) => set({ lastError }),
  setLiveText: (liveText) => set({ liveText }),
  appendLiveText: (t) => set((s) => ({ liveText: s.liveText + t })),
  addLiveStep: (step) => set((s) => ({ liveSteps: [...s.liveSteps, step] })),
  resetLive: () => set({ liveText: "", liveSteps: [], contexts: [] }),
  pushMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setContexts: (contexts) => set({ contexts }),
  setTtsEnabled: (ttsEnabled) => set({ ttsEnabled }),
  clearChat: () =>
    set({
      messages: [],
      liveText: "",
      liveSteps: [],
      contexts: [],
      confirm: null,
      lastError: null,
      phase: "idle",
    }),
}));
