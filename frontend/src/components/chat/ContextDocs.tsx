import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { contextSourceLabel, type RetrievedDoc } from "@/lib/answer";

export function ContextDocs({
  docs,
  embedded = false,
}: {
  docs: RetrievedDoc[];
  /** 嵌在详情折叠区内时，不再重复外层标题 */
  embedded?: boolean;
}) {
  const [openId, setOpenId] = useState<number | null>(null);
  if (!docs.length) return null;
  const src = contextSourceLabel(docs);

  return (
    <div className={`context-docs${embedded ? " embedded" : ""}`}>
      {!embedded ? <div className="context-docs-title">检索到的{src.section}</div> : null}
      <div className="context-docs-list">
        {docs.map((d) => {
          const open = openId === d.index;
          const meta =
            d.kind === "amap_poi"
              ? "地点"
              : d.page != null && d.page !== ""
                ? `第 ${d.page} 页`
                : src.meta;
          return (
            <div key={d.index} className={`context-doc${open ? " open" : ""}`}>
              <button
                type="button"
                className="context-doc-head"
                onClick={() => setOpenId(open ? null : d.index)}
                aria-expanded={open}
              >
                <span className="context-doc-idx">【{d.index}】</span>
                <span className="context-doc-main">
                  <span className="context-doc-name">{d.title}</span>
                  <span className="context-doc-preview">{d.preview || d.content.slice(0, 100)}</span>
                </span>
                <span className="context-doc-meta">
                  {meta}
                  <i className={open ? "up" : ""} />
                </span>
              </button>
              <AnimatePresence initial={false}>
                {open ? (
                  <motion.div
                    className="context-doc-body"
                    initial={{ height: 0, opacity: 0 }}
                    animate={{ height: "auto", opacity: 1 }}
                    exit={{ height: 0, opacity: 0 }}
                    transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
                  >
                    <pre>{d.content}</pre>
                  </motion.div>
                ) : null}
              </AnimatePresence>
            </div>
          );
        })}
      </div>
    </div>
  );
}
