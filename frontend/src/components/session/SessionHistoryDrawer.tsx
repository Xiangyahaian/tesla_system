import { useEffect } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";
import { SessionManagerPanel } from "@/components/session/SessionManagerPanel";

export function SessionHistoryDrawer() {
  const open = useCabinStore((s) => s.historyOpen);
  const setHistoryOpen = useCabinStore((s) => s.setHistoryOpen);
  const sessionTitle = useCabinStore((s) => s.sessionTitle);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setHistoryOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, setHistoryOpen]);

  return (
    <AnimatePresence>
      {open ? (
        <div className="session-sheet-root" role="presentation">
          <motion.button
            type="button"
            className="session-sheet-backdrop"
            aria-label="关闭会话历史"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22 }}
            onClick={() => setHistoryOpen(false)}
          />
          <motion.aside
            className="session-sheet"
            role="dialog"
            aria-modal="true"
            aria-labelledby="session-sheet-title"
            initial={{ x: -28, opacity: 0 }}
            animate={{ x: 0, opacity: 1 }}
            exit={{ x: -20, opacity: 0 }}
            transition={{ duration: 0.32, ease: [0.16, 1, 0.3, 1] }}
          >
            <header className="session-sheet-head">
              <div>
                <h2 id="session-sheet-title">历史记录</h2>
                <p>{sessionTitle || "当前会话"}</p>
              </div>
              <button type="button" className="session-sheet-close" onClick={() => setHistoryOpen(false)} aria-label="关闭">
                <svg viewBox="0 0 24 24" aria-hidden>
                  <path d="M6 6l12 12M18 6L6 18" />
                </svg>
              </button>
            </header>
            <SessionManagerPanel variant="drawer" onConsumed={() => setHistoryOpen(false)} />
          </motion.aside>
        </div>
      ) : null}
    </AnimatePresence>
  );
}
