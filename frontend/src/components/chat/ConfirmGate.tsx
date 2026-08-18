import { AnimatePresence, motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";
import { resolveHmiConfirm } from "@/hooks/useVehicleControl";

/**
 * 仅中控手动点按的危险动作弹确认。
 * Agent / 语音侧确认走对话（说「确认」「取消」），不弹网页式对话框。
 */
export function ConfirmGate() {
  const hmiConfirm = useCabinStore((s) => s.hmiConfirm);
  const open = !!hmiConfirm;
  const message = hmiConfirm?.message || "";
  const summary = hmiConfirm?.summary;

  return (
    <AnimatePresence>
      {open ? (
        <motion.div
          className="confirm-overlay"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          onClick={() => resolveHmiConfirm(false)}
        >
          <motion.div
            className="confirm-card"
            role="dialog"
            aria-modal="true"
            aria-labelledby="confirm-title"
            initial={{ opacity: 0, y: 24, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 12, scale: 0.98 }}
            transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
            onClick={(e) => e.stopPropagation()}
          >
            <div className="confirm-kicker">中控确认</div>
            <h3 id="confirm-title">确认后再执行</h3>
            <p className="confirm-msg">{message}</p>
            {summary ? <p className="confirm-summary">{summary}</p> : null}
            <div className="confirm-actions">
              <button type="button" className="btn ghost" onClick={() => resolveHmiConfirm(false)}>
                取消
              </button>
              <button type="button" className="btn primary" onClick={() => resolveHmiConfirm(true)}>
                确认
              </button>
            </div>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>
  );
}
