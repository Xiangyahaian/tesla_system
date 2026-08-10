import { motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";
import type { VoicePhase } from "@/lib/types";

const LABELS: Record<VoicePhase, string> = {
  idle: "待命",
  listening: "聆听中",
  thinking: "理解中",
  acting: "执行中",
  speaking: "播报中",
};

export function VoiceOrb({
  onHoldStart,
  onHoldEnd,
}: {
  onHoldStart: () => void;
  onHoldEnd: () => void;
}) {
  const phase = useCabinStore((s) => s.phase);
  const busy = useCabinStore((s) => s.busy);
  const active = phase !== "idle";

  return (
    <div className="voice-orb-wrap">
      <motion.button
        type="button"
        className={`voice-orb ${phase}`}
        disabled={busy && phase === "thinking"}
        onPointerDown={(e) => {
          e.currentTarget.setPointerCapture(e.pointerId);
          onHoldStart();
        }}
        onPointerUp={onHoldEnd}
        onPointerCancel={onHoldEnd}
        whileTap={{ scale: 0.97 }}
        animate={{
          scale: active ? [1, 1.03, 1] : 1,
        }}
        transition={{ duration: 2.4, repeat: active ? Infinity : 0, ease: "easeInOut" }}
        aria-label="按住说话"
      >
        <span className="voice-orb-ring" />
        <span className="voice-orb-core" />
      </motion.button>
      <div className="voice-orb-meta">
        <div className="voice-orb-label">{LABELS[phase]}</div>
        <div className="voice-orb-hint">按住说话 · 松开发送</div>
      </div>
    </div>
  );
}
