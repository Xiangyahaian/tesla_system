import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { fetchCabinState, resetCabin, streamChat } from "@/lib/api";
import { getSpeechRecognition, speakText, stopSpeaking } from "@/lib/speech";
import { useCabinStore } from "@/store/cabinStore";
import type { ChatMessage, TraceStep } from "@/lib/types";
import { ChatStream } from "@/components/chat/ChatStream";
import { ConfirmGate } from "@/components/chat/ConfirmGate";
import { VehicleHud } from "@/components/hud/VehicleHud";
import { VoiceOrb } from "@/components/voice/VoiceOrb";

function uid() {
  return Math.random().toString(36).slice(2, 10);
}

export function CabinShell() {
  const [draft, setDraft] = useState("");
  const recognizingRef = useRef(false);
  const transcriptRef = useRef("");

  const sessionId = useCabinStore((s) => s.sessionId);
  const model = useCabinStore((s) => s.model);
  const busy = useCabinStore((s) => s.busy);
  const setModel = useCabinStore((s) => s.setModel);
  const setPhase = useCabinStore((s) => s.setPhase);
  const setBusy = useCabinStore((s) => s.setBusy);
  const setError = useCabinStore((s) => s.setError);
  const setVehicle = useCabinStore((s) => s.setVehicle);
  const setConfirm = useCabinStore((s) => s.setConfirm);
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
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "状态同步失败");
    }
  }, [sessionId, setConfirm, setError, setVehicle]);

  useEffect(() => {
    void refreshState();
    const t = window.setInterval(() => void refreshState(), 4000);
    return () => window.clearInterval(t);
  }, [refreshState]);

  const runQuery = useCallback(
    async (query: string, confirm: boolean | null = null) => {
      const q = query.trim();
      if (!q || busy) return;

      stopSpeaking();
      setBusy(true);
      setError(null);
      setConfirm(null);
      resetLive();
      setPhase(confirm == null ? "thinking" : "acting");

      const userMsg: ChatMessage = { id: uid(), role: "user", content: q };
      if (confirm == null) pushMessage(userMsg);

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
              relatedImages: (data as { related_images?: { image_path: string; title?: string }[] })
                .related_images,
            });
            resetLive();
            await refreshState();

            // Speak only the last non-log paragraph for demo polish
            const spoken = answer
              .split(/\n+/)
              .filter((line) => line.trim() && !line.trim().startsWith(">"))
              .slice(-3)
              .join(" ");
            if (spoken && confirm == null) {
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
        if (!useCabinStore.getState().confirm) {
          // keep phase if speaking handled above
        }
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
    const rec = (window as unknown as { __cabinRec?: ReturnType<typeof getSpeechRecognition> }).__cabinRec;
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

  return (
    <div className="cabin-shell">
      <header className="cabin-top">
        <div className="brand-block">
          <div className="brand-mark">CABIN</div>
          <div className="brand-sub">Intelligent Cockpit · Demo</div>
        </div>
        <div className="top-actions">
          <select
            className="model-select"
            value={model}
            onChange={(e) => setModel(e.target.value as "remote" | "local")}
            aria-label="模型"
          >
            <option value="remote">Qwen Flash</option>
            <option value="local">Local</option>
          </select>
          <a className="link-quiet" href="/agent" target="_blank" rel="noreferrer">
            轨迹
          </a>
          <a className="link-quiet" href="/legacy" target="_blank" rel="noreferrer">
            旧版
          </a>
          <button
            type="button"
            className="btn ghost compact"
            onClick={async () => {
              await resetCabin(sessionId);
              clearChat();
              await refreshState();
            }}
          >
            重置
          </button>
        </div>
      </header>

      <div className="cabin-main">
        <section className="cabin-center">
          <VoiceOrb onHoldStart={onHoldStart} onHoldEnd={onHoldEnd} />
          <ChatStream />
          <form className="composer" onSubmit={onSubmit}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="输入指令，或按住上方声纹说话…"
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSubmit(e);
                }
              }}
            />
            <button type="submit" className="btn primary" disabled={busy || !draft.trim()}>
              发送
            </button>
          </form>
        </section>
        <VehicleHud />
      </div>

      <ConfirmGate
        onConfirm={() => void runQuery("确认", true)}
        onCancel={() => {
          setConfirm(null);
          void runQuery("取消", false);
        }}
      />
    </div>
  );
}
