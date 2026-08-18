import { motion } from "framer-motion";
import { VoiceOrb } from "@/components/voice/VoiceOrb";
import { ChatStream } from "@/components/chat/ChatStream";
import { VehicleConsole } from "@/components/hud/VehicleConsole";
import { SeatSwitcher } from "@/components/drive/SeatSwitcher";
import { PresetQuestionsButton } from "@/components/drive/PresetQuestionsButton";
import { ManualPreviewButton } from "@/components/drive/ManualPreviewButton";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";
import { unlockAudioPlayback } from "@/lib/speech";

const fadeUp = {
  initial: { opacity: 0, y: 12 },
  animate: { opacity: 1, y: 0 },
};

export function DrivePage() {
  const { draft, setDraft, onSubmit, onHoldStart, onHoldEnd, runQuery, doReset } = useCabinRuntime();
  const busy = useCabinStore((s) => s.busy);
  const model = useCabinStore((s) => s.model);
  const setModel = useCabinStore((s) => s.setModel);
  const lastError = useCabinStore((s) => s.lastError);
  const ttsEnabled = useCabinStore((s) => s.ttsEnabled);
  const setTtsEnabled = useCabinStore((s) => s.setTtsEnabled);
  const ttsVolume = useCabinStore((s) => s.ttsVolume);
  const setTtsVolume = useCabinStore((s) => s.setTtsVolume);

  return (
    <div className="page-drive">
      <section className="drive-left" aria-label="对话区">
        <motion.div
          className="drive-left-head"
          {...fadeUp}
          transition={{ duration: 0.4, ease: [0.16, 1, 0.3, 1] }}
        >
          <div>
            <h1>小特助手</h1>
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
            <button type="button" className="btn ghost compact" onClick={() => void doReset()}>
              重置会话
            </button>
          </div>
        </motion.div>

        <motion.div {...fadeUp} transition={{ delay: 0.06, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}>
          <VoiceOrb onHoldStart={onHoldStart} onHoldEnd={onHoldEnd} />
        </motion.div>

        {lastError ? <div className="inline-error">{lastError}</div> : null}

        <motion.div
          className="drive-chat-motion"
          {...fadeUp}
          transition={{ delay: 0.14, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        >
          <ChatStream />
        </motion.div>

        <motion.div
          className="composer-dock"
          {...fadeUp}
          transition={{ delay: 0.2, duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
        >
          <SeatSwitcher />
          <form className="composer" onSubmit={onSubmit}>
            <div className="composer-field">
              <textarea
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                placeholder="对小特说点什么… 点下方「输入示例」可选用附近美食、导航、空调等"
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
                    void unlockAudioPlayback();
                    void runQuery(q);
                  }}
                  disabled={busy}
                />
                <button type="submit" className="btn primary compact" disabled={busy || !draft.trim()}>
                  发送
                </button>
              </div>
            </div>
          </form>
        </motion.div>
      </section>

      <motion.div
        className="drive-right-motion"
        initial={{ opacity: 0, x: 16 }}
        animate={{ opacity: 1, x: 0 }}
        transition={{ delay: 0.1, duration: 0.5, ease: [0.16, 1, 0.3, 1] }}
      >
        <VehicleConsole />
      </motion.div>
    </div>
  );
}
