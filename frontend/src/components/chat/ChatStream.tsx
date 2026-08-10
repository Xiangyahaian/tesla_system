import { useEffect, useRef } from "react";
import { useCabinStore } from "@/store/cabinStore";
import { TurnRail } from "@/components/agent/TurnRail";

export function ChatStream() {
  const messages = useCabinStore((s) => s.messages);
  const liveText = useCabinStore((s) => s.liveText);
  const liveSteps = useCabinStore((s) => s.liveSteps);
  const contexts = useCabinStore((s) => s.contexts);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [messages, liveText, liveSteps]);

  return (
    <div className="chat-stream">
      {messages.length === 0 && !liveText ? (
        <div className="chat-empty">
          <div className="chat-empty-brand">Cabin</div>
          <p>试着说：「打开空调并播放晴天」或「自动泊车怎么用」</p>
          <p className="chat-empty-hint">左侧可切到 Apps / Agent 轨迹页</p>
        </div>
      ) : null}

      {messages.map((m) => (
        <article key={m.id} className={`bubble ${m.role}`}>
          <header>
            {m.role === "user" ? "You" : "小特"}
            {m.turnId ? <span className="bubble-turn">#{m.turnId.slice(0, 8)}</span> : null}
          </header>
          <pre className="bubble-body">{m.content}</pre>
          {m.steps && m.steps.length > 0 ? <TurnRail steps={m.steps} /> : null}
          {m.relatedImages && m.relatedImages.length > 0 ? (
            <div className="image-row">
              {m.relatedImages.slice(0, 3).map((img) => (
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
          ) : null}
          {m.citePages && m.citePages.length > 0 ? (
            <div className="cite">引用页码：{m.citePages.join(", ")}</div>
          ) : null}
        </article>
      ))}

      {(liveText || liveSteps.length > 0) && (
        <article className="bubble assistant live">
          <header>小特 · live</header>
          {liveSteps.length > 0 ? <TurnRail steps={liveSteps} /> : null}
          {liveText ? <pre className="bubble-body">{liveText}</pre> : null}
        </article>
      )}

      {contexts.length > 0 ? (
        <div className="context-strip">
          <div className="context-title">Retrieved</div>
          {contexts.slice(0, 3).map((c, i) => (
            <div key={i} className="context-item">
              {c.slice(0, 160)}
              {c.length > 160 ? "…" : ""}
            </div>
          ))}
        </div>
      ) : null}

      <div ref={endRef} />
    </div>
  );
}
