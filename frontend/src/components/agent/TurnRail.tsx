import { AnimatePresence, motion } from "framer-motion";
import type { TraceStep } from "@/lib/types";

export function TurnRail({ steps }: { steps: TraceStep[] }) {
  if (!steps.length) return null;
  return (
    <ol className="turn-rail" aria-label="本轮 Agent 轨迹">
      <AnimatePresence initial={false}>
        {steps.map((s) => (
          <motion.li
            key={s.id}
            className={`turn-step status-${s.status || "ok"}`}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <span className="turn-type">{s.type}</span>
            <span className="turn-title">{s.title}</span>
          </motion.li>
        ))}
      </AnimatePresence>
    </ol>
  );
}
