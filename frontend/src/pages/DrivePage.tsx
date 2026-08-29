import { useEffect, useRef, useState } from "react";
import { VoiceOrb } from "@/components/voice/VoiceOrb";
import { ChatStream } from "@/components/chat/ChatStream";
import { VehicleConsole } from "@/components/hud/VehicleConsole";
import { SeatSwitcher } from "@/components/drive/SeatSwitcher";
import { PresetQuestionsButton } from "@/components/drive/PresetQuestionsButton";
import { ManualPreviewButton } from "@/components/drive/ManualPreviewButton";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";
import { fetchModelStatus } from "@/lib/api";
import { unlockAudioPlayback } from "@/lib/speech";

function appendComposerText(current: string, extra: string): string {
  const cur = current.trim();
  const add = extra.trim();
  if (!add) return current;
  if (!cur) return add;
  if (/[，,、；;。.!？?]$/.test(cur)) return `${cur}${add}`;
  return `${cur}，${add}`;
}

export function DrivePage() {
  const { draft, setDraft, onSubmit, onHoldStart, onHoldEnd, startNewSession, onPauseToggle, canPause, pauseLabel } =
    useCabinRuntime();
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const draftRef = useRef(draft);
  draftRef.current = draft;
  const busy = useCabinStore((s) => s.busy);
  const model = useCabinStore((s) => s.model);
  const setModel = useCabinStore((s) => s.setModel);
  const lastError = useCabinStore((s) => s.lastError);
  const ttsEnabled = useCabinStore((s) => s.ttsEnabled);
  const setTtsEnabled = useCabinStore((s) => s.setTtsEnabled);
  const ttsVolume = useCabinStore((s) => s.ttsVolume);
  const setTtsVolume = useCabinStore((s) => s.setTtsVolume);
  const sessionTitle = useCabinStore((s) => s.sessionTitle);
  const setHistoryOpen = useCabinStore((s) => s.setHistoryOpen);
  const [localHint, setLocalHint] = useState<string | null>(null);

  useEffect(() => {
    if (model !== "local") {
      setLocalHint(null);
      return;
    }
    let cancelled = false;
    void fetchModelStatus()
      .then((s) => {
        if (cancelled) return;
        if (s.local_available) setLocalHint(null);
        else setLocalHint(String(s.local_error || "本地模型未连通"));
      })
      .catch(() => {
        if (!cancelled) setLocalHint("无法检查本地模型");
      });
    return () => {
      cancelled = true;
    };
  }, [model]);

  return (
    <div className="page-drive">
      <section className="drive-left" aria-label="对话区">
        <div className="drive-left-head">
          <div className="drive-session">
            <h1>小特助手</h1>
            <button
              type="button"
              className="drive-history-open"
              onClick={() => setHistoryOpen(true)}
              title="打开会话历史"
            >
              <span>{sessionTitle || "主会话"}</span>
              <svg viewBox="0 0 24 24" aria-hidden>
                <path d="M8 10l4 4 4-4" />
              </svg>
            </button>
          </div>
          <div className="drive-left-actions">
            <button
              type="button"
              className={`btn ghost compact${ttsEnabled ? " on-sound" : ""}`}
              aria-pressed={ttsEnabled}
              onClick={() => {
                const next = !ttsEnabled;
                setTtsEnabled(next);
                if (next) void unlockAudioPlayback();
              }}
            >
              {ttsEnabled ? "声音开" : "声音关"}
            </button>
            {ttsEnabled ? (
              <label className="drive-vol">
                <span className="sr-only">音量</span>
                <input
                  type="range"
                  min={0}
                  max={100}
                  value={Math.round(ttsVolume * 100)}
                  onChange={(e) => setTtsVolume(Number(e.target.value) / 100)}
                  aria-label="播报音量"
                />
              </label>
            ) : null}
            <ManualPreviewButton />
            <select
              className="model-select"
              value={model}
              onChange={(e) => setModel(e.target.value as "remote" | "local")}
              aria-label="模型"
            >
              <option value="remote">云端模型</option>
              <option value="local">本地模型</option>
            </select>
            <button type="button" className="btn ghost compact" onClick={() => setHistoryOpen(true)}>
              历史会话
            </button>
            <button type="button" className="btn ghost compact" onClick={() => void startNewSession()} title="新建对话，当前会话会留在历史里">
              新会话
            </button>
          </div>
        </div>

        <VoiceOrb onHoldStart={onHoldStart} onHoldEnd={onHoldEnd} />

        {localHint ? <div className="inline-error">{localHint}</div> : null}
        {lastError ? <div className="inline-error">{lastError}</div> : null}

        <div className="drive-chat-motion">
          <ChatStream />
        </div>

        <div className="composer-dock">
          <SeatSwitcher />
          <form className="composer" onSubmit={onSubmit}>
            <div className="composer-field">
              <textarea
                ref={inputRef}
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="对小特说点什么… 点「输入示例」可选用一条填入输入框"
                rows={2}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && !e.shiftKey) {
                    e.preventDefault();
                    onSubmit(e);
                  }
                }}
              />
              <div className="composer-toolbar">
                <PresetQuestionsButton
                  compact
                  onPick={(q) => {
                    const next = appendComposerText(draftRef.current, q);
                    draftRef.current = next;
                    setDraft(next);
                    requestAnimationFrame(() => {
                      const el = inputRef.current;
                      if (!el) return;
                      el.setSelectionRange(next.length, next.length);
                    });
                  }}
                />
                <div className="composer-toolbar-actions">
                  {canPause ? (
                    <button
                      type="button"
                      className="btn ghost compact pause-btn"
                      onClick={() => {
                        void unlockAudioPlayback();
                        onPauseToggle();
                      }}
                      title="暂停并撤回本轮，原文回到输入框"
                    >
                      {pauseLabel}
                    </button>
                  ) : null}
                  <button type="submit" className="btn primary compact" disabled={busy || !draft.trim()}>
                    发送
                  </button>
                </div>
              </div>
            </div>
          </form>
        </div>
      </section>

      <div className="drive-right-motion">
        <VehicleConsole />
      </div>
    </div>
  );
}
