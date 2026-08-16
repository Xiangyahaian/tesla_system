import { motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";
import type { VoicePhase } from "@/lib/types";

const LABELS: Record<VoicePhase, string> = {
  idle: "按住说话",
  listening: "正在聆听…",
  thinking: "正在理解…",
  acting: "正在执行…",
  speaking: "正在播报…",
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
    <div className={`voice-orb-wrap${active ? " is-live" : ""}`}>
      <div className="voice-orb-stage">
        {[0, 1, 2].map((i) => (
          <motion.span
            key={i}
            className="voice-orb-pulse"
            aria-hidden
            animate={
              active
                ? { scale: [1, 1.55 + i * 0.12], opacity: [0.35, 0] }
                : { scale: 1, opacity: 0 }
            }
            transition={
              active
                ? { duration: 1.8 + i * 0.25, repeat: Infinity, delay: i * 0.35, ease: "easeOut" }
                : { duration: 0.3 }
            }
          />
        ))}
        <motion.button
          type="button"
          className={`voice-orb ${phase}`}
          disabled={busy && phase === "thinking"}
          style={{ touchAction: "none", userSelect: "none", WebkitUserSelect: "none" }}
          onContextMenu={(e) => e.preventDefault()}
          onPointerDown={(e) => {
            e.preventDefault();
            e.currentTarget.setPointerCapture(e.pointerId);
            onHoldStart();
          }}
          onPointerUp={onHoldEnd}
          onPointerCancel={onHoldEnd}
          onLostPointerCapture={onHoldEnd}
          whileHover={{ scale: 1.03 }}
          whileTap={{ scale: 0.96 }}
          animate={active ? { scale: [1, 1.04, 1] } : { scale: 1 }}
          transition={{ duration: 1.6, repeat: active ? Infinity : 0, ease: "easeInOut" }}
          aria-label="按住说话"
        >
          <motion.span
            className="voice-orb-ring"
            animate={active ? { opacity: [0.35, 0.95, 0.35], rotate: 360 } : { opacity: 0.45, rotate: 0 }}
            transition={
              active
                ? { opacity: { duration: 1.4, repeat: Infinity }, rotate: { duration: 8, repeat: Infinity, ease: "linear" } }
                : { duration: 0.3 }
            }
          />
          <span className="voice-orb-core" />
          <span className="voice-orb-shine" aria-hidden />
        </motion.button>
      </div>
      <div className="voice-orb-meta">
        <div className="voice-orb-label">{LABELS[phase]}</div>
      </div>
    </div>
  );
}
