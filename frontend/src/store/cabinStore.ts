import { create } from "zustand";
import type {
  CabinStateSnapshot,
  ChatMessage,
  ConfirmPayload,
  TraceStep,
  VoicePhase,
} from "@/lib/types";

type CabinStore = {
  sessionId: string;
  model: "remote" | "local";
  phase: VoicePhase;
  messages: ChatMessage[];
  liveText: string;
  liveSteps: TraceStep[];
  contexts: string[];
  confirm: ConfirmPayload | null;
  vehicle: CabinStateSnapshot | null;
  busy: boolean;
  lastError: string | null;
  setPhase: (p: VoicePhase) => void;
  setModel: (m: "remote" | "local") => void;
  setVehicle: (v: CabinStateSnapshot | null) => void;
  setConfirm: (c: ConfirmPayload | null) => void;
  setBusy: (b: boolean) => void;
  setError: (e: string | null) => void;
  setLiveText: (t: string) => void;
  appendLiveText: (t: string) => void;
  addLiveStep: (s: TraceStep) => void;
  resetLive: () => void;
  pushMessage: (m: ChatMessage) => void;
  setContexts: (c: string[]) => void;
  clearChat: () => void;
};

export const useCabinStore = create<CabinStore>((set) => ({
  sessionId: "default",
  model: "remote",
  phase: "idle",
  messages: [],
  liveText: "",
  liveSteps: [],
  contexts: [],
  confirm: null,
  vehicle: null,
  busy: false,
  lastError: null,
  setPhase: (phase) => set({ phase }),
  setModel: (model) => set({ model }),
  setVehicle: (vehicle) => set({ vehicle }),
  setConfirm: (confirm) => set({ confirm }),
  setBusy: (busy) => set({ busy }),
  setError: (lastError) => set({ lastError }),
  setLiveText: (liveText) => set({ liveText }),
  appendLiveText: (t) => set((s) => ({ liveText: s.liveText + t })),
  addLiveStep: (step) => set((s) => ({ liveSteps: [...s.liveSteps, step] })),
  resetLive: () => set({ liveText: "", liveSteps: [], contexts: [] }),
  pushMessage: (m) => set((s) => ({ messages: [...s.messages, m] })),
  setContexts: (contexts) => set({ contexts }),
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
