import { AnimatePresence, motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";

export function ConfirmGate({
  onConfirm,
  onCancel,
}: {
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const confirm = useCabinStore((s) => s.confirm);
  return (
    <AnimatePresence>
      {confirm ? (
        <motion.div
          className="confirm-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
        >
          <motion.div
            className="confirm-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            initial={{ opacity: 0, y: 16 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: 10 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            <div className="confirm-kicker">安全确认 · {confirm.risk}</div>
            <h3 id="confirm-title">需要你确认后才会执行</h3>
            <p className="confirm-msg">{confirm.message}</p>
            <p className="confirm-summary">{confirm.summary}</p>
            <div className="confirm-actions">
              <button type="button" className="btn ghost" onClick={onCancel}>
                取消
              </button>
              <button type="button" className="btn primary" onClick={onConfirm}>
                确认执行
              </button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
