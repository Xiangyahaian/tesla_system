import {
  createContext,
  FormEvent,
  ReactNode,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { fetchCabinState, resetCabin, streamChat } from "@/lib/api";
import { getSpeechRecognition, speakText, stopSpeaking } from "@/lib/speech";
import { useCabinStore } from "@/store/cabinStore";
import type { ChatMessage, TraceStep } from "@/lib/types";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

type CabinRuntime = {
  draft: string;
  setDraft: (v: string) => void;
  runQuery: (query: string, confirm?: boolean | null) => Promise<void>;
  onSubmit: (e: FormEvent) => void;
  onHoldStart: () => void;
  onHoldEnd: () => void;
  refreshState: () => Promise<void>;
  doReset: () => Promise<void>;
};

const Ctx = createContext<CabinRuntime | null>(null);

export function CabinRuntimeProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState("");
  const recognizingRef = useRef(false);
  const transcriptRef = useRef("");

  const sessionId = useCabinStore((s) => s.sessionId);
  const model = useCabinStore((s) => s.model);
  const busy = useCabinStore((s) => s.busy);
  const ttsEnabled = useCabinStore((s) => s.ttsEnabled);
  const setPhase = useCabinStore((s) => s.setPhase);
  const setBusy = useCabinStore((s) => s.setBusy);
  const setError = useCabinStore((s) => s.setError);
  const setVehicle = useCabinStore((s) => s.setVehicle);
  const setConfirm = useCabinStore((s) => s.setConfirm);
  const setAgentMeta = useCabinStore((s) => s.setAgentMeta);
  const resetLive = useCabinStore((s) => s.resetLive);
  const appendLiveText = useCabinStore((s) => s.appendLiveText);
  const addLiveStep = useCabinStore((s) => s.addLiveStep);
  const pushMessage = useCabinStore((s) => s.pushMessage);
  const setContexts = useCabinStore((s) => s.setContexts);
  const clearChat = useCabinStore((s) => s.clearChat);

  const refreshState = useCallback(async () => {
    try {
      const data = await fetchCabinState(sessionId);
      setVehicle(data.state);
      setAgentMeta(data.agent ?? null);
      if (data.pending) {
        const p = data.pending as {
          message?: string;
          summary?: string;
          risk?: string | { value?: string };
        };
        setConfirm({
          message: p.message || "该操作涉及车辆安全，请确认后执行。",
          summary: p.summary || "",
          risk: typeof p.risk === "string" ? p.risk : p.risk?.value || "high",
        });
      } else {
        setConfirm(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "状态同步失败");
    }
  }, [sessionId, setAgentMeta, setConfirm, setError, setVehicle]);

  useEffect(() => {
    void refreshState();
    const t = window.setInterval(() => void refreshState(), 3500);
    return () => window.clearInterval(t);
  }, [refreshState]);

  const runQuery = useCallback(
    async (query: string, confirm: boolean | null = null) => {
      const q = query.trim();
      if (!q || busy) return;

      stopSpeaking();
      setBusy(true);
      setError(null);
      if (confirm == null) setConfirm(null);
      resetLive();
      setPhase(confirm == null ? "thinking" : "acting");

      if (confirm == null) {
        const userMsg: ChatMessage = { id: uid(), role: "user", content: q };
        pushMessage(userMsg);
      }

      let finalAnswer = "";
      const collectedSteps: TraceStep[] = [];

      try {
        await streamChat(q, {
          sessionId,
          model,
          confirm,
          onStatus: () => setPhase("thinking"),
          onToken: (t) => {
            appendLiveText(t);
            finalAnswer += t;
            if (t && !t.startsWith(">")) setPhase("acting");
          },
          onTrace: (step) => {
            collectedSteps.push(step);
            addLiveStep(step);
            if (step.type === "tool" || step.type === "loop") setPhase("acting");
          },
          onConfirm: (data) => {
            setConfirm(data);
            setPhase("idle");
          },
          onContext: (items) => setContexts(items),
          onFinal: async (data) => {
            const answer = finalAnswer.trim() || "已完成。";
            pushMessage({
              id: uid(),
              role: "assistant",
              content: answer,
              turnId: String((data as { turn_id?: string }).turn_id || ""),
              steps: collectedSteps,
              citePages: (data as { cite_pages?: (string | number)[] }).cite_pages,
              relatedImages: (
                data as { related_images?: { image_path: string; title?: string }[] }
              ).related_images,
            });
            resetLive();
            await refreshState();

            const spoken = answer
              .split(/\n+/)
              .filter((line) => line.trim() && !line.trim().startsWith(">"))
              .slice(-3)
              .join(" ");
            if (spoken && confirm == null && ttsEnabled) {
              setPhase("speaking");
              await speakText(spoken);
            }
            setPhase("idle");
          },
          onError: (msg) => setError(msg),
        });
      } catch (e) {
        setError(e instanceof Error ? e.message : "请求失败");
        setPhase("idle");
      } finally {
        setBusy(false);
      }
    },
    [
      addLiveStep,
      appendLiveText,
      busy,
      model,
      pushMessage,
      refreshState,
      resetLive,
      sessionId,
      setBusy,
      setConfirm,
      setContexts,
      setError,
      setPhase,
      ttsEnabled,
    ],
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    const q = draft;
    setDraft("");
    void runQuery(q);
  };

  const onHoldStart = () => {
    if (busy) return;
    const rec = getSpeechRecognition();
    if (!rec) {
      setError("当前浏览器不支持语音识别，请用 Chrome 并允许麦克风");
      return;
    }
    stopSpeaking();
    transcriptRef.current = "";
    recognizingRef.current = true;
    setPhase("listening");
    rec.lang = "zh-CN";
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (ev) => {
      let text = "";
      for (let i = 0; i < ev.results.length; i++) {
        text += ev.results[i][0].transcript;
      }
      transcriptRef.current = text;
      setDraft(text);
    };
    rec.onerror = () => {
      recognizingRef.current = false;
      setPhase("idle");
    };
    rec.onend = () => {
      recognizingRef.current = false;
    };
    try {
      rec.start();
      (window as unknown as { __cabinRec?: typeof rec }).__cabinRec = rec;
    } catch {
      setError("无法启动麦克风");
      setPhase("idle");
    }
  };

  const onHoldEnd = () => {
    const rec = (window as unknown as { __cabinRec?: ReturnType<typeof getSpeechRecognition> })
      .__cabinRec;
    try {
      rec?.stop();
    } catch {
      /* ignore */
    }
    const text = transcriptRef.current.trim() || draft.trim();
    setPhase("idle");
    if (text) {
      setDraft("");
      void runQuery(text);
    }
  };

  const doReset = useCallback(async () => {
    await resetCabin(sessionId);
    clearChat();
    await refreshState();
  }, [clearChat, refreshState, sessionId]);

  const value = useMemo(
    () => ({
      draft,
      setDraft,
      runQuery,
      onSubmit,
      onHoldStart,
      onHoldEnd,
      refreshState,
      doReset,
    }),
    [draft, doReset, onHoldEnd, onHoldStart, onSubmit, refreshState, runQuery],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCabinRuntime() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCabinRuntime must be used within CabinRuntimeProvider");
  return ctx;
}
