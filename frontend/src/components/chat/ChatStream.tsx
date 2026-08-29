import { useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";
import { TurnRail } from "@/components/agent/TurnRail";
import { AnswerBody } from "@/components/chat/AnswerBody";
import { ContextDocs, ManualImageRow } from "@/components/chat/ContextDocs";
import { contextSourceLabel, extractAnswer } from "@/lib/answer";
import { toShowcaseSteps } from "@/lib/trace";
import type { ChatMessage, TraceStep } from "@/lib/types";
import type { RetrievedDoc } from "@/lib/answer";

function ReplyDetails({
  docs,
  citePages,
  images,
  steps,
}: {
  docs?: RetrievedDoc[];
  citePages?: Array<string | number>;
  images?: ChatMessage["relatedImages"];
  steps?: TraceStep[];
}) {
  const [open, setOpen] = useState(false);
  const [tab, setTab] = useState<"docs" | "trace">("docs");
  const showcase = toShowcaseSteps(steps || []);
  const docCount = docs?.length ?? 0;
  const imageCount = images?.length ?? 0;
  const hasTrace = showcase.length > 0;
  const hasCite = (citePages?.length ?? 0) > 0;
  const hasDocs = docCount > 0 || imageCount > 0 || hasCite;
  const src = contextSourceLabel(docs);
  if (!hasDocs && !hasTrace) return null;

  const bits: string[] = [];
  if (docCount) bits.push(`${docCount} ${src.short}`);
  if (imageCount) bits.push(`${imageCount} 张图`);
  if (hasTrace) bits.push(`${showcase.length} 步`);

  const defaultTab = hasDocs ? "docs" : "trace";
  const activeTab = hasDocs && hasTrace ? tab : defaultTab;

  return (
    <div className="reply-details">
      <button
        type="button"
        className={`reply-details-toggle${open ? " open" : ""}`}
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="reply-details-toggle-label">
          {open ? "收起依据与过程" : "查看依据与过程"}
        </span>
        {bits.length ? <span className="reply-details-toggle-bits">{bits.join(" · ")}</span> : null}
        <span className="reply-details-chevron" aria-hidden />
      </button>
      <AnimatePresence initial={false}>
        {open ? (
          <motion.div
            className="reply-details-panel"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: 0.16 }}
          >
            {hasDocs && hasTrace ? (
              <div className="reply-details-tabs" role="tablist">
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "docs"}
                  className={activeTab === "docs" ? "on" : ""}
                  onClick={() => setTab("docs")}
                >
                  {src.tab}
                </button>
                <button
                  type="button"
                  role="tab"
                  aria-selected={activeTab === "trace"}
                  className={activeTab === "trace" ? "on" : ""}
                  onClick={() => setTab("trace")}
                >
                  执行过程
                </button>
              </div>
            ) : null}

            {activeTab === "docs" && hasDocs ? (
              <div className="reply-details-pane">
                {docCount > 0 ? (
                  <section className="reply-details-section" aria-label={src.section}>
                    {!hasTrace ? <h4>{src.section}</h4> : null}
                    <ContextDocs docs={docs!} embedded />
                    {hasCite ? <div className="cite">参考页码：{citePages!.join("、")}</div> : null}
                  </section>
                ) : hasCite ? (
                  <div className="cite">参考页码：{citePages!.join("、")}</div>
                ) : null}
                {imageCount > 0 ? (
                  <section className="reply-details-section" aria-label="相关插图">
                    <h4>相关插图</h4>
                    <ManualImageRow images={images!.slice(0, 6)} />
                  </section>
                ) : null}
              </div>
            ) : null}

            {activeTab === "trace" && hasTrace ? (
              <div className="reply-details-pane">
                {!hasDocs ? <h4 className="reply-details-solo-title">执行过程</h4> : null}
                <TurnRail steps={steps || []} compact />
              </div>
            ) : null}
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}

export function ChatStream() {
  const messages = useCabinStore((s) => s.messages);
  const liveText = useCabinStore((s) => s.liveText);
  const liveSteps = useCabinStore((s) => s.liveSteps);
  const contexts = useCabinStore((s) => s.contexts);
  const endRef = useRef<HTMLDivElement>(null);
  const liveAnswer = extractAnswer(liveText);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, liveAnswer, liveSteps, contexts]);

  return (
    <div className="chat-stream">
      <div className="chat-stream-inner">
        <AnimatePresence initial={false}>
          {messages.map((m) => (
            <motion.article
              key={m.id}
              className={`bubble ${m.role}`}
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              transition={{ duration: 0.16 }}
            >
              <header>{m.role === "user" ? "我" : "小特"}</header>
              {m.role === "assistant" ? (
                <AnswerBody text={extractAnswer(m.content) || m.content} />
              ) : (
                <pre className="bubble-body">{m.content}</pre>
              )}
              {m.role === "assistant" ? (
                <ReplyDetails
                  docs={m.contexts}
                  citePages={m.citePages}
                  images={m.relatedImages}
                  steps={m.steps}
                />
              ) : null}
            </motion.article>
          ))}
        </AnimatePresence>

        {(liveAnswer || liveSteps.length > 0) && (
          <motion.article
            className="bubble assistant live"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.16 }}
          >
            <header>小特 · 正在回复</header>
            {liveSteps.length > 0 && !liveAnswer ? (
              <div className="live-status">
                正在处理…（
                {toShowcaseSteps(liveSteps).at(-1)?.title ||
                  liveSteps[liveSteps.length - 1]?.title ||
                  "思考中"}
                ）
              </div>
            ) : null}
            {liveAnswer ? <AnswerBody text={liveAnswer} /> : null}
          </motion.article>
        )}

        <div ref={endRef} />
      </div>
    </div>
  );
}
