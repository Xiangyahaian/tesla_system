import { useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import type { TraceStep } from "@/lib/types";
import { formatElapsed, toShowcaseSteps, type ShowcaseStep } from "@/lib/trace";
import { ContextDocs, ManualImageRow } from "@/components/chat/ContextDocs";

function statusWord(status?: string) {
  switch ((status || "ok").toLowerCase()) {
    case "error":
    case "blocked":
      return "失败";
    case "warn":
    case "need_confirm":
      return "待确认";
    default:
      return "完成";
  }
}

function StepRow({ step }: { step: ShowcaseStep }) {
  const [open, setOpen] = useState(false);
  const hasDocs = !!(step.docs && step.docs.length);
  const hasImages = !!(step.images && step.images.length);
  const hasLines = !!(step.detailLines && step.detailLines.length);
  const hasDetail = hasLines || hasDocs || hasImages;
  const tone = (step.status || "ok").toLowerCase();
  const elapsed = formatElapsed(step.elapsedMs);

  return (
    <li className={`trace-step tone-${tone}`}>
      <div className="trace-step-rail" aria-hidden>
        <span className="trace-step-dot">{step.index}</span>
        <span className="trace-step-line" />
      </div>
      <div className="trace-step-card">
        {hasDetail ? (
          <button
            type="button"
            className={`trace-step-head${open ? " open" : ""}`}
            onClick={() => setOpen((v) => !v)}
            aria-expanded={open}
          >
            <div className="trace-step-meta">
              <span className="trace-step-phase">{step.typeLabel}</span>
              <span className="trace-step-status">{statusWord(step.status)}</span>
            </div>
            <div className="trace-step-main">
              <span className="trace-step-title">{step.title}</span>
              {step.summary ? <span className="trace-step-summary">{step.summary}</span> : null}
            </div>
            {elapsed ? <span className="trace-step-elapsed">{elapsed}</span> : <span />}
            <span className={`trace-step-chevron${open ? " open" : ""}`} aria-hidden />
          </button>
        ) : (
          <div className="trace-step-head static">
            <div className="trace-step-meta">
              <span className="trace-step-phase">{step.typeLabel}</span>
              <span className="trace-step-status">{statusWord(step.status)}</span>
            </div>
            <div className="trace-step-main">
              <span className="trace-step-title">{step.title}</span>
              {step.summary ? <span className="trace-step-summary">{step.summary}</span> : null}
            </div>
            {elapsed ? <span className="trace-step-elapsed">{elapsed}</span> : <span />}
          </div>
        )}
        <AnimatePresence initial={false}>
          {open && hasDetail ? (
            <motion.div
              className="trace-step-detail"
              initial={{ height: 0, opacity: 0 }}
              animate={{ height: "auto", opacity: 1 }}
              exit={{ height: 0, opacity: 0 }}
              transition={{ duration: 0.22, ease: [0.22, 1, 0.36, 1] }}
            >
              {hasImages ? (
                <div className="trace-step-media">
                  <ManualImageRow images={step.images!} />
                </div>
              ) : null}
              {hasDocs ? <ContextDocs docs={step.docs!} embedded /> : null}
              {hasLines ? (
                <ul>
                  {step.detailLines!.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              ) : null}
            </motion.div>
          ) : null}
        </AnimatePresence>
      </div>
    </li>
  );
}

export function TurnRail({
  steps,
  compact = false,
  endedAt,
}: {
  steps: TraceStep[];
  /** 对话气泡内更紧凑 */
  compact?: boolean;
  endedAt?: number;
}) {
  const showcase = toShowcaseSteps(steps, endedAt);
  if (!showcase.length) return null;

  return (
    <ol className={`trace-rail${compact ? " compact" : ""}`} aria-label="本轮执行过程">
      {showcase.map((s) => (
        <StepRow key={s.id} step={s} />
      ))}
    </ol>
  );
}
