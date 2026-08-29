import { FormEvent, useEffect, useState } from "react";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";

/** Floating composer available on Apps/Agent/Settings without leaving context */
export function GlobalComposer() {
  const { runQuery, onPauseToggle, canPause, pauseLabel } = useCabinRuntime();
  const busy = useCabinStore((s) => s.busy);
  const phase = useCabinStore((s) => s.phase);
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
      }
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const submit = (e: FormEvent) => {
    e.preventDefault();
    const q = text.trim();
    if (!q || busy) return;
    setText("");
    setOpen(false);
    void runQuery(q);
  };

  if (!open) {
    return (
      <button
        type="button"
        className="global-composer-fab"
        onClick={() => setOpen(true)}
        title="Ctrl/Cmd+K"
      >
        提问
        <span className="fab-kbd">⌘K</span>
      </button>
    );
  }

  return (
    <div className="global-composer-overlay" role="dialog" aria-label="全局指令">
      <form className="global-composer" onSubmit={submit}>
        <div className="global-composer-head">
          <span>对小特说</span>
          <span className="global-composer-phase">{phase}</span>
        </div>
        <input
          autoFocus
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="输入一句指令…"
        />
        <div className="global-composer-actions">
          <button type="button" className="btn ghost compact" onClick={() => setOpen(false)}>
            取消
          </button>
          {canPause ? (
            <button type="button" className="btn ghost compact pause-btn" onClick={() => onPauseToggle()}>
              {pauseLabel}
            </button>
          ) : null}
          <button type="submit" className="btn primary compact" disabled={busy || !text.trim()}>
            发送
          </button>
        </div>
      </form>
    </div>
  );
}
