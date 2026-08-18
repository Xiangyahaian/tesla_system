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
import { fetchCabinState, fetchSessionMessages, resetCabin, streamChat } from "@/lib/api";
import { extractAnswer, extractSpeakText, normalizeContexts } from "@/lib/answer";
import { recognizeBlob, speakText, startMicRecording, stopSpeaking, unlockAudioPlayback, type MicRecorder } from "@/lib/speech";
import { useCabinStore } from "@/store/cabinStore";
import type { CabinStateSnapshot, ChatMessage, TraceStep } from "@/lib/types";
import { isSeatId } from "@/lib/seats";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

/** 首句完整句读才抢跑，避免只播半截就停。 */
function pickFirstSentence(answer: string): string {
  const flat = (answer || "").replace(/\s+/g, " ").trim();
  if (!flat) return "";
  const m = flat.match(/^[\s\S]{4,100}?[。！？!?]/);
  return m ? m[0].trim() : "";
}

function transcriptToChat(messages: { role: string; content: string; ts?: number }[]): ChatMessage[] {
  const out: ChatMessage[] = [];
  for (const m of messages) {
    if (m.role !== "user" && m.role !== "assistant") continue;
    const content = (m.content || "").trim();
    if (!content) continue;
    // 过滤内部 trace 风格的过程行（以 > 开头的 harness 日志）
    if (m.role === "assistant" && content.startsWith("> **[")) {
      const parts = content.split(/\n\n---\n\n/);
      const human = parts.length > 1 ? parts[parts.length - 1].trim() : "";
      if (!human || human.startsWith(">")) continue;
      out.push({ id: uid(), role: "assistant", content: human });
      continue;
    }
    out.push({ id: uid(), role: m.role, content });
  }
  return out;
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
  switchSession: (sessionId: string, title?: string) => Promise<void>;
  reloadMessages: () => Promise<void>;
};

const Ctx = createContext<CabinRuntime | null>(null);

export function CabinRuntimeProvider({ children }: { children: ReactNode }) {
  const [draft, setDraft] = useState("");
  const recognizingRef = useRef(false);
  const micRef = useRef<MicRecorder | null>(null);
  const holdActiveRef = useRef(false);

  const sessionId = useCabinStore((s) => s.sessionId);
  const model = useCabinStore((s) => s.model);
  const busy = useCabinStore((s) => s.busy);
  const ttsEnabled = useCabinStore((s) => s.ttsEnabled);
  const ttsVolume = useCabinStore((s) => s.ttsVolume);
  const activeSeat = useCabinStore((s) => s.activeSeat);
  const setActiveSeat = useCabinStore((s) => s.setActiveSeat);
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
  const setMessages = useCabinStore((s) => s.setMessages);
  const setContexts = useCabinStore((s) => s.setContexts);
  const clearChat = useCabinStore((s) => s.clearChat);
  const setSessionId = useCabinStore((s) => s.setSessionId);

  const reloadMessages = useCallback(async () => {
    if (!sessionId) return;
    try {
      const data = await fetchSessionMessages(sessionId, 300);
      setMessages(transcriptToChat(data.messages || []));
      if (data.title) useCabinStore.getState().setSessionTitle(data.title);
    } catch {
      /* 首次无历史时忽略 */
    }
  }, [sessionId, setMessages]);

  const refreshState = useCallback(async () => {
    if (!sessionId) return;
    const epoch = useCabinStore.getState().vehicleEpoch;
    try {
      const data = await fetchCabinState(sessionId);
      const now = useCabinStore.getState();
      // 重置过程中的旧轮询结果不要盖住刚写入的南门快照
      if (now.resetInFlight || now.vehicleEpoch !== epoch) return;
      setVehicle(data.state);
      setAgentMeta(data.agent ?? null);
      if (data.pending) {
        // 后端仍有 pending，但前端不弹窗；用户用输入/语音说确认或取消
        setConfirm(null);
      } else {
        setConfirm(null);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "状态同步失败");
    }
  }, [sessionId, setAgentMeta, setConfirm, setError, setVehicle]);

  useEffect(() => {
    void refreshState();
    void reloadMessages();
    const t = window.setInterval(() => void refreshState(), 3500);
    return () => window.clearInterval(t);
  }, [refreshState, reloadMessages]);

  const runQuery = useCallback(
    async (query: string, confirm: boolean | null = null) => {
      const q = query.trim();
      if (!q || busy || !sessionId) return;

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
      let collectedContexts = normalizeContexts([]);
      let earlyTtsStarted = false;
      let spokenPrefix = "";
      let ttsPromise: Promise<void> | null = null;

      const enqueueSpeak = (text: string, interrupt: boolean) => {
        const clean = (text || "").replace(/\s+/g, " ").trim();
        if (!clean || !ttsEnabled) return;
        setPhase("speaking");
        const run = () =>
          speakText(clean, ttsVolume, { interrupt }).catch((e) => {
            setError(e instanceof Error ? e.message : "语音播报失败");
          });
        ttsPromise = ttsPromise ? ttsPromise.then(run, run) : run();
      };

      try {
        await streamChat(q, {
          sessionId,
          model,
          confirm,
          activeSeat,
          onStatus: () => setPhase("thinking"),
          onToken: (t) => {
            appendLiveText(t);
            finalAnswer += t;
            if (t && !t.trimStart().startsWith(">")) setPhase("acting");
            // 只抢跑 Agent 指定的【听】内容（或无标记时的可播结论）
            if (ttsEnabled && !earlyTtsStarted) {
              const speakable = extractSpeakText(finalAnswer);
              const first = pickFirstSentence(speakable);
              // 有【听】标记时，等相对完整再播；无标记则等首句句读
              const hasListenTag = /【听】|\[\[说\]\]/.test(finalAnswer);
              const ready = hasListenTag
                ? speakable.length >= 6 && (/[。！？!?]/.test(speakable) || /【看】/.test(finalAnswer))
                : !!first;
              if (ready && (first || speakable)) {
                earlyTtsStarted = true;
                spokenPrefix = first || speakable.slice(0, 100);
                enqueueSpeak(spokenPrefix, true);
              }
            }
          },
          onTrace: (step) => {
            collectedSteps.push(step);
            addLiveStep(step);
            if (step.type === "tool" || step.type === "loop") setPhase("acting");
          },
          onConfirm: () => {
            // Agent 确认只走对话（文本/语音回「确认」「取消」），不弹窗
            setConfirm(null);
            setPhase("idle");
          },
          onActiveSeat: (data) => {
            if (isSeatId(data?.active_seat)) setActiveSeat(data.active_seat);
          },
          onContext: (items) => {
            collectedContexts = normalizeContexts(items);
            setContexts(collectedContexts);
          },
          onFinal: async (data) => {
            const seatFromState = (data as { state?: { active_seat?: string } })?.state?.active_seat;
            const seat = (data as { active_seat?: string }).active_seat || seatFromState;
            if (isSeatId(seat)) setActiveSeat(seat);
            const fromFinal = normalizeContexts(
              (data as { contexts?: unknown }).contexts ?? collectedContexts,
            );
            const answer = extractAnswer(finalAnswer) || "好的，我这边处理好了。";
            const speakFull = extractSpeakText(finalAnswer) || answer;
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
              contexts: fromFinal,
            });
            resetLive();

            if (!earlyTtsStarted) {
              enqueueSpeak(speakFull, true);
            } else if (speakFull && spokenPrefix) {
              let rest = "";
              if (speakFull.startsWith(spokenPrefix)) {
                rest = speakFull.slice(spokenPrefix.length).trim();
              } else {
                const idx = speakFull.indexOf(spokenPrefix);
                rest = idx >= 0 ? speakFull.slice(idx + spokenPrefix.length).trim() : "";
              }
              if (rest.length >= 2) enqueueSpeak(rest, false);
            }
            void refreshState();
            if (ttsPromise) {
              setPhase("speaking");
              void ttsPromise.finally(() => setPhase("idle"));
            } else {
              setPhase("idle");
            }
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
      activeSeat,
      addLiveStep,
      appendLiveText,
      busy,
      model,
      pushMessage,
      refreshState,
      resetLive,
      sessionId,
      setActiveSeat,
      setBusy,
      setConfirm,
      setContexts,
      setError,
      setPhase,
      ttsEnabled,
      ttsVolume,
    ],
  );

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void unlockAudioPlayback();
    const q = draft;
    setDraft("");
    void runQuery(q);
  };

  const onHoldStart = () => {
    if (busy || recognizingRef.current) return;
    holdActiveRef.current = true;
    stopSpeaking();
    setError(null);
    setPhase("listening");
    setDraft("正在聆听…");
    void (async () => {
      try {
        await unlockAudioPlayback();
        const mic = await startMicRecording();
        if (!holdActiveRef.current) {
          mic.abort();
          return;
        }
        micRef.current = mic;
        recognizingRef.current = true;
      } catch (e) {
        holdActiveRef.current = false;
        recognizingRef.current = false;
        setDraft("");
        setError(e instanceof Error ? e.message : "无法启动麦克风");
        setPhase("idle");
      }
    })();
  };

  const onHoldEnd = () => {
    holdActiveRef.current = false;
    const mic = micRef.current;
    micRef.current = null;
    if (!mic) {
      // 松手太快，录音还没起来
      setDraft("");
      setPhase("idle");
      return;
    }
    void (async () => {
      recognizingRef.current = false;
      setPhase("thinking");
      setDraft("正在识别…");
      try {
        const blob = await mic.stop();
        if (!blob.size) {
          setDraft("");
          setPhase("idle");
          setError("没听清，请再试一次");
          return;
        }
        const text = await recognizeBlob(blob);
        if (!text) {
          setDraft("");
          setPhase("idle");
          setError("没听清，请再说一次");
          return;
        }
        setDraft("");
        await runQuery(text);
      } catch (e) {
        setDraft("");
        setPhase("idle");
        setError(e instanceof Error ? e.message : "语音识别失败");
      }
    })();
  };

  const doReset = useCallback(async () => {
    stopSpeaking();
    const store = useCabinStore.getState();
    store.setResetInFlight(true);
    store.bumpVehicleEpoch();
    try {
      const res = await resetCabin(sessionId);
      clearChat();
      if (res?.state) setVehicle(res.state as CabinStateSnapshot);
      store.bumpVehicleEpoch();
      store.bumpMapEpoch();
    } finally {
      useCabinStore.getState().setResetInFlight(false);
    }
    // 放行后再拉一次，确认与后端一致（此时 tick 已恢复）
    await refreshState();
  }, [clearChat, refreshState, sessionId, setVehicle]);

  const switchSession = useCallback(
    async (nextId: string, title?: string) => {
      stopSpeaking();
      useCabinStore.getState().bumpVehicleEpoch();
      setSessionId(nextId, title);
      clearChat();
      resetLive();
      setError(null);
      setPhase("idle");
      try {
        const data = await fetchSessionMessages(nextId, 300);
        setMessages(transcriptToChat(data.messages || []));
        useCabinStore.getState().setSessionTitle(data.title || title || nextId);
        const state = await fetchCabinState(nextId);
        setVehicle(state.state);
        useCabinStore.getState().bumpMapEpoch();
        setAgentMeta(state.agent ?? null);
        if (state.pending) {
          setConfirm(null);
        } else {
          setConfirm(null);
        }
      } catch (e) {
        setError(e instanceof Error ? e.message : "切换会话失败");
      }
    },
    [
      clearChat,
      resetLive,
      setAgentMeta,
      setConfirm,
      setError,
      setMessages,
      setPhase,
      setSessionId,
      setVehicle,
    ],
  );

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
      switchSession,
      reloadMessages,
    }),
    [draft, doReset, onHoldEnd, onHoldStart, onSubmit, refreshState, reloadMessages, runQuery, switchSession],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useCabinRuntime() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error("useCabinRuntime must be used within CabinRuntimeProvider");
  return ctx;
}
