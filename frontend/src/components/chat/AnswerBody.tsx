/** 手册回答：结论 / 步骤 / 小提示，正文内保留【n】引用编号 */

function renderWithCites(text: string) {
  const parts = text.split(/(【\d+(?:\s*[,，、]\s*\d+)*】)/g);
  return parts.map((part, i) => {
    if (/^【\d+(?:\s*[,，、]\s*\d+)*】$/.test(part)) {
      return (
        <sup key={i} className="cite-mark" title={`参考文档 ${part}`}>
          {part}
        </sup>
      );
    }
    return <span key={i}>{part}</span>;
  });
}

export function AnswerBody({ text }: { text: string }) {
  if (!text) return null;
  const lines = text.split(/\r?\n/);
  const blocks: Array<{ type: "p" | "ol" | "tip" | "refs"; items: string[] }> = [];
  let ol: string[] = [];

  const flushOl = () => {
    if (ol.length) {
      blocks.push({ type: "ol", items: ol });
      ol = [];
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) {
      flushOl();
      continue;
    }
    const step = line.match(/^(\d+)[\.、\)]\s*(.+)$/);
    if (step) {
      ol.push(step[2]);
      continue;
    }
    flushOl();
    if (/^(小提示|提示|注意)[:：]/.test(line)) {
      blocks.push({ type: "tip", items: [line.replace(/^(小提示|提示|注意)[:：]\s*/, "")] });
    } else if (/^参考[:：]/.test(line)) {
      // 总引用行：提取编号展示，不丢
      const nums = Array.from(line.matchAll(/【([^】]+)】/g))
        .flatMap((m) => m[1].split(/[,，、\s]+/))
        .map((s) => s.trim())
        .filter(Boolean);
      if (nums.length) blocks.push({ type: "refs", items: nums });
    } else {
      blocks.push({ type: "p", items: [line] });
    }
  }
  flushOl();

  return (
    <div className="answer-body">
      {blocks.map((b, i) => {
        if (b.type === "ol") {
          return (
            <ol key={i} className="answer-steps">
              {b.items.map((it, j) => (
                <li key={j}>{renderWithCites(it)}</li>
              ))}
            </ol>
          );
        }
        if (b.type === "tip") {
          return (
            <div key={i} className="answer-tip">
              <span>小提示</span>
              {renderWithCites(b.items[0])}
            </div>
          );
        }
        if (b.type === "refs") {
          return (
            <div key={i} className="answer-refs" aria-label="参考文档">
              <em>参考</em>
              {b.items.map((n) => (
                <span key={n} className="cite-chip">
                  【{n}】
                </span>
              ))}
            </div>
          );
        }
        return (
          <p key={i} className={i === 0 ? "answer-lead" : undefined}>
            {renderWithCites(b.items[0])}
          </p>
        );
      })}
    </div>
  );
}
