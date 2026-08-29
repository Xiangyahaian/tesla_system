import { useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import {
  PRESET_CATEGORY_LABEL,
  PRESET_QUESTIONS,
  type PresetCategory,
  type PresetQuestion,
} from "@/lib/presets";

const TABS: Array<{ id: PresetCategory | "all"; label: string }> = [
  { id: "all", label: "全部" },
  { id: "knowledge", label: "手册" },
  { id: "tool", label: "控车" },
  { id: "chat", label: "闲聊" },
];

export function PresetQuestionsButton({
  onPick,
  disabled,
  compact,
}: {
  onPick: (q: string) => void;
  disabled?: boolean;
  /** 嵌在输入区工具栏时的紧凑样式 */
  compact?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<PresetCategory | "all">("all");

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  const grouped = useMemo(() => {
    const source =
      tab === "all" ? PRESET_QUESTIONS : PRESET_QUESTIONS.filter((q) => q.category === tab);
    if (tab !== "all") {
      return [{ category: tab as PresetCategory, items: source }];
    }
    const order: PresetCategory[] = ["knowledge", "tool", "chat"];
    return order.map((c) => ({
      category: c,
      items: PRESET_QUESTIONS.filter((q) => q.category === c),
    }));
  }, [tab]);

  const pick = (q: PresetQuestion) => {
    onPick(q.text);
    setOpen(false);
  };

  return (
    <>
      <button
        type="button"
        className={compact ? "composer-preset-btn" : "action-link"}
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        输入示例
      </button>

      <AnimatePresence>
        {open ? (
          <motion.div
            className="preset-overlay"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.22 }}
            onClick={() => setOpen(false)}
          >
            <motion.aside
              className="preset-sheet"
              role="dialog"
              aria-modal="true"
              aria-label="输入示例"
              initial={{ x: -28, opacity: 0 }}
              animate={{ x: 0, opacity: 1 }}
              exit={{ x: -16, opacity: 0 }}
              transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
              onClick={(e) => e.stopPropagation()}
            >
              <header className="preset-sheet-head">
                <div>
                  <p className="preset-eyebrow">点选填入输入框，侧栏自动收起</p>
                  <h3>输入示例</h3>
                </div>
                <button type="button" className="preset-close" onClick={() => setOpen(false)} aria-label="关闭">
                  <span />
                  <span />
                </button>
              </header>

              <div className="preset-seg" role="tablist">
                {TABS.map((t) => (
                  <button
                    key={t.id}
                    type="button"
                    role="tab"
                    aria-selected={tab === t.id}
                    className={tab === t.id ? "active" : ""}
                    onClick={() => setTab(t.id)}
                  >
                    {t.label}
                  </button>
                ))}
              </div>

              <div className="preset-body">
                {grouped.map((group) => (
                  <section key={group.category} className="preset-group">
                    {tab === "all" ? (
                      <div className="preset-group-title">{PRESET_CATEGORY_LABEL[group.category]}</div>
                    ) : null}
                    <ul className="preset-lines">
                      {group.items.map((q, i) => (
                        <li key={`${q.category}-${q.text}`}>
                          <button
                            type="button"
                            className="preset-line"
                            disabled={disabled}
                            onClick={() => pick(q)}
                          >
                            <span className="preset-idx">{String(i + 1).padStart(2, "0")}</span>
                            <span className="preset-q">{q.text}</span>
                            <span className="preset-go" aria-hidden>
                              选用
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  </section>
                ))}
              </div>
            </motion.aside>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </>
  );
}
