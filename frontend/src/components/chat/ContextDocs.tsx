import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { contextSourceLabel, type RetrievedDoc, type RetrievedImage } from "@/lib/answer";

export function ManualImageRow({
  images,
  compact = false,
}: {
  images: RetrievedImage[];
  compact?: boolean;
}) {
  if (!images.length) return null;
  return (
    <div className={`image-row${compact ? " compact" : ""}`}>
      {images.map((img) => (
        <figure key={img.image_path} className="image-card">
          <img
            src={`/api/image?path=${encodeURIComponent(img.image_path)}`}
            alt={img.title || "手册图"}
            loading="lazy"
          />
          {img.title ? <figcaption>{img.title}</figcaption> : null}
        </figure>
      ))}
    </div>
  );
}

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
          const imgN = d.images?.length ?? 0;
          const metaBits = [
            d.kind === "amap_poi"
              ? "地点"
              : d.kind === "web"
                ? "网页"
                : d.page != null && d.page !== ""
                  ? `第 ${d.page} 页`
                  : src.meta,
            imgN ? `${imgN} 张图` : "",
          ].filter(Boolean);
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
                  {metaBits.join(" · ")}
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
                    {d.url ? (
                      <p className="context-doc-link">
                        <a href={d.url} target="_blank" rel="noreferrer">
                          打开原文
                        </a>
                      </p>
                    ) : null}
                    {d.images?.length ? <ManualImageRow images={d.images} compact /> : null}
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
