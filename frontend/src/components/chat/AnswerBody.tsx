import { stripEmoji } from "@/lib/answer";

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

type StepItem = { text: string; bullets: string[] };

type Block =
  | { type: "p"; text: string }
  | { type: "steps"; items: StepItem[] }
  | { type: "tip"; text: string }
  | { type: "refs"; nums: string[] }
  | { type: "nudge"; text: string };

function normCompare(s: string) {
  return s
    .replace(/【\d+(?:\s*[,，、]\s*\d+)*】/g, "")
    .replace(/[。！？!?,.，、；;：:\s]/g, "")
    .trim();
}

function isUnreadNudge(line: string) {
  return /未读消息/.test(line) && /您有|条未读/.test(line);
}

function parseBlocks(text: string): Block[] {
  const lines = stripEmoji(text).split(/\r?\n/);
  const blocks: Block[] = [];
  let steps: StepItem[] | null = null;
  let orphanBullets: string[] = [];

  const flushSteps = () => {
    if (orphanBullets.length) {
      if (!steps) steps = [];
      if (steps.length === 0) {
        steps.push({ text: "", bullets: [...orphanBullets] });
      } else {
        steps[steps.length - 1].bullets.push(...orphanBullets);
      }
      orphanBullets = [];
    }
    if (steps?.length) {
      blocks.push({ type: "steps", items: steps });
      steps = null;
    }
  };

  for (const raw of lines) {
    const line = raw.trim();
    if (!line) continue;

    if (isUnreadNudge(line)) {
      flushSteps();
      blocks.push({ type: "nudge", text: line });
      continue;
    }

    const step = line.match(/^(\d+)[\.、\)]\s*(.+)$/);
    if (step) {
      if (orphanBullets.length && steps?.length) {
        steps[steps.length - 1].bullets.push(...orphanBullets);
        orphanBullets = [];
      }
      if (!steps) steps = [];
      steps.push({ text: step[2], bullets: [] });
      continue;
    }

    const bullet = line.match(/^[-•*]\s+(.+)$/);
    if (bullet) {
      if (steps?.length) {
        steps[steps.length - 1].bullets.push(bullet[1]);
      } else {
        orphanBullets.push(bullet[1]);
      }
      continue;
    }

    flushSteps();
    if (/^(小提示|提示|注意)[:：]/.test(line)) {
      blocks.push({
        type: "tip",
        text: line.replace(/^(小提示|提示|注意)[:：]\s*/, ""),
      });
    } else if (/^参考[:：]/.test(line)) {
      const nums = Array.from(line.matchAll(/【([^】]+)】/g))
        .flatMap((m) => m[1].split(/[,，、\s]+/))
        .map((s) => s.trim())
        .filter(Boolean);
      if (nums.length) blocks.push({ type: "refs", nums });
    } else {
      blocks.push({ type: "p", text: line });
    }
  }
  flushSteps();
  return postProcessBlocks(blocks);
}

function postProcessBlocks(blocks: Block[]): Block[] {
  const merged: Block[] = [];
  for (const b of blocks) {
    const prev = merged[merged.length - 1];
    if (b.type === "steps" && prev?.type === "steps") {
      prev.items.push(...b.items);
    } else {
      merged.push(b);
    }
  }

  if (merged.length >= 2 && merged[0].type === "p" && merged[1].type === "steps") {
    const lead = normCompare(merged[0].text);
    const first = normCompare(merged[1].items[0]?.text || "");
    if (lead && first && (lead === first || first.includes(lead) || lead.includes(first))) {
      merged[1].items.shift();
      if (merged[1].items.length === 0) merged.splice(1, 1);
    }
  }

  const nudgeIdx = merged.map((b, i) => (b.type === "nudge" ? i : -1)).filter((i) => i >= 0);
  if (nudgeIdx.length > 1) {
    const keep = nudgeIdx[nudgeIdx.length - 1];
    return merged.filter((b, i) => b.type !== "nudge" || i === keep);
  }
  return merged;
}

export function AnswerBody({ text }: { text: string }) {
  if (!text) return null;
  const blocks = parseBlocks(text);

  return (
    <div className="answer-body">
      {blocks.map((b, i) => {
        if (b.type === "steps") {
          return (
            <ol key={i} className="answer-steps">
              {b.items.map((it, j) => (
                <li key={j}>
                  {it.text ? renderWithCites(it.text) : null}
                  {it.bullets.length > 0 ? (
                    <ul className="answer-substeps">
                      {it.bullets.map((bt, k) => (
                        <li key={k}>{renderWithCites(bt)}</li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ol>
          );
        }
        if (b.type === "tip") {
          return (
            <div key={i} className="answer-tip">
              <span>小提示</span>
              {renderWithCites(b.text)}
            </div>
          );
        }
        if (b.type === "refs") {
          return (
            <div key={i} className="answer-refs" aria-label="参考文档">
              <em>参考</em>
              {b.nums.map((n) => (
                <span key={n} className="cite-chip">
                  【{n}】
                </span>
              ))}
            </div>
          );
        }
        if (b.type === "nudge") {
          return (
            <p key={i} className="answer-screen-only">
              {renderWithCites(b.text)}
            </p>
          );
        }
        return (
          <p key={i} className={i === 0 ? "answer-lead" : undefined}>
            {renderWithCites(b.text)}
          </p>
        );
      })}
    </div>
  );
}
