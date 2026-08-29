import type { ReactNode } from "react";
import type { AgentLlmPrompt } from "@/lib/api";
import { formatElapsed } from "@/lib/trace";

type DocItem = { id: string; title: string; text: string };

type UserPart =
  | { key: string; kind: "text"; label: string; text: string }
  | { key: string; kind: "docs"; label: string; docs: DocItem[] };

type ContentBlock =
  | { kind: "kv"; label: string; value: string }
  | { kind: "section"; label: string; value: string; json?: boolean }
  | { kind: "prose"; value: string }
  | { kind: "code"; value: string };

function tokenSourceLabel(src?: string) {
  if (src === "api") return "接口返回";
  if (src === "estimate") return "估算";
  if (src === "mixed") return "混合";
  return "";
}

function firstLine(text: string) {
  return (text || "")
    .split("\n")
    .map((l) => l.replace(/^#+\s*/, "").trim())
    .find(Boolean) || "";
}

function inferCallKind(p: AgentLlmPrompt) {
  const s = p.system || "";
  const u = p.user || "";
  if (s.includes("规划器") && (s.includes("逐步") || s.includes("意图"))) {
    return { title: "意图规划", hint: "决定走控车、查车况、手册还是闲聊" };
  }
  if (s.includes("对照用户手册") || u.includes("参考文档:")) {
    return { title: "手册问答", hint: "带着检索文档生成回复" };
  }
  if (s.includes("根据车辆状态如实说明") || u.includes("相关状态JSON")) {
    return { title: "查车况", hint: "按当前车辆状态生成回复" };
  }
  if (
    s.includes("工具原始结果已在依据面板") ||
    u.includes("工具结果摘要") ||
    u.includes("可供口述的材料")
  ) {
    return { title: "工具结果转口语", hint: "把工具返回改成给用户听的话" };
  }
  if (s.includes("会话压缩器")) return { title: "压缩对话", hint: "对话太长时做摘要" };
  if (
    s.includes("三份用户笔记") ||
    (s.includes("persona.md") && s.includes("memories.md") && s.includes("preferences.md")) ||
    (u.includes("---persona.md 当前---") && u.includes("---memories.md 当前---")) ||
    s.includes("长期记忆")
  ) {
    return { title: "更新记忆/人设/偏好", hint: "按本轮对话改写长期笔记并落盘" };
  }
  if (u.includes("除车控/地图外还有闲聊")) return { title: "补答闲聊", hint: "工具做完后补非工具部分" };
  if (s.includes("温暖陪伴") || s.includes("全能副驾")) return { title: "闲聊", hint: "带上下文直接回话" };
  return { title: "模型调用", hint: "一次 chat/completions 请求" };
}

function splitDocs(blob: string): { docs: DocItem[]; tail: string } {
  const marks: { id: string; start: number }[] = [];
  const re = /【(\d+)】/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(blob))) {
    marks.push({ id: m[1], start: m.index });
  }
  if (!marks.length) return { docs: [], tail: blob.trim() };

  const docs: DocItem[] = [];
  let tail = "";
  for (let i = 0; i < marks.length; i++) {
    const start = marks[i].start;
    const end = i + 1 < marks.length ? marks[i + 1].start : blob.length;
    let raw = blob.slice(start, end).trim();
    if (i === marks.length - 1) {
      const cut = raw.search(/\n\n请/);
      if (cut > 0) {
        tail = raw.slice(cut).trim();
        raw = raw.slice(0, cut).trim();
      }
    }
    const body = raw.replace(/^【\d+】/, "").trim();
    const title = firstLine(body) || `文档 ${marks[i].id}`;
    docs.push({ id: marks[i].id, title: title.slice(0, 36), text: body });
  }
  return { docs, tail };
}

function takePrefix(text: string, label: string): { value: string; rest: string } | null {
  if (!text.startsWith(label)) return null;
  const rest0 = text.slice(label.length);
  const cut = rest0.search(/\n\n/);
  if (cut < 0) return { value: rest0.trim(), rest: "" };
  return { value: rest0.slice(0, cut).trim(), rest: rest0.slice(cut).trim() };
}

function takeSuffix(text: string, label: string): { value: string; rest: string } | null {
  const idx = text.lastIndexOf(label);
  if (idx < 0) return null;
  const value = text.slice(idx + label.length).trim();
  if (!value || value.includes("\n\n")) return null;
  return { value, rest: text.slice(0, idx).trim() };
}

function parseUserParts(user: string): UserPart[] {
  let text = (user || "").trim();
  if (!text) return [];
  const parts: UserPart[] = [];

  const knowledge = text.match(/^用户问题:\s*([\s\S]*?)\n+参考文档:\s*\n?([\s\S]*)$/);
  if (knowledge) {
    const question = knowledge[1].trim();
    if (question) parts.push({ key: "q", kind: "text", label: "用户问题", text: question });
    const { docs, tail } = splitDocs(knowledge[2].trim());
    if (docs.length) parts.push({ key: "docs", kind: "docs", label: "参考文档", docs });
    if (tail) parts.push({ key: "extra", kind: "text", label: "额外交代", text: tail });
    return parts;
  }

  const spokenMark = text.startsWith("用户原话：")
    ? "用户原话："
    : text.startsWith("用户原话:")
      ? "用户原话:"
      : "";
  if (spokenMark) {
    const rest0 = text.slice(spokenMark.length);
    const nl = rest0.indexOf("\n");
    const spoken = (nl < 0 ? rest0 : rest0.slice(0, nl)).trim();
    const material = (nl < 0 ? "" : rest0.slice(nl + 1)).trim();
    if (spoken) parts.push({ key: "q", kind: "text", label: "用户原话", text: spoken });
    if (material) parts.push({ key: "extra", kind: "text", label: "交给模型的材料", text: material });
    return parts;
  }

  const ask = takeSuffix(text, "\n用户问:") || takeSuffix(text, "\n用户:");
  if (ask) {
    parts.push({ key: "q", kind: "text", label: "用户问题", text: ask.value });
    text = ask.rest;
  }

  const recent = takePrefix(text, "最近对话:");
  if (recent) {
    if (recent.value) parts.push({ key: "recent", kind: "text", label: "最近对话", text: recent.value });
    text = recent.rest;
  }

  if (text) {
    parts.push({
      key: "rest",
      kind: "text",
      label: parts.some((p) => p.key === "q") ? "其它输入" : "本轮输入",
      text,
    });
  }
  return parts;
}

function tryPrettyJson(raw: string): string | null {
  const t = (raw || "").trim();
  if (!t.startsWith("{") && !t.startsWith("[")) return null;
  try {
    return JSON.stringify(JSON.parse(t), null, 2);
  } catch {
    return null;
  }
}

function splitPlannerBlocks(text: string): ContentBlock[] | null {
  const raw = (text || "").trim();
  if (!raw.includes("当前规划步序") && !raw.includes("当前车况摘要") && !raw.includes("历史摘要")) {
    return null;
  }

  const blocks: ContentBlock[] = [];
  const sectionHeads = ["当前车况摘要", "历史摘要", "已执行工具观察", "用户原话"];
  const lines = raw.split("\n");
  let i = 0;

  while (i < lines.length) {
    const ln = lines[i];
    if (!ln.trim()) {
      i += 1;
      continue;
    }
    if (sectionHeads.some((h) => ln.startsWith(`${h}:`) || ln.startsWith(`${h}：`) || ln === h)) {
      break;
    }
    const kv = ln.match(/^([^:\n]{2,24})[：:]\s*(.*)$/);
    if (kv && !ln.startsWith("{") && kv[1].length <= 16) {
      blocks.push({ kind: "kv", label: kv[1].trim(), value: kv[2].trim() || "—" });
      i += 1;
      continue;
    }
    break;
  }

  while (i < lines.length) {
    while (i < lines.length && !lines[i].trim()) i += 1;
    if (i >= lines.length) break;

    const ln = lines[i];
    const head = sectionHeads.find((h) => ln.startsWith(`${h}:`) || ln.startsWith(`${h}：`) || ln === h);
    if (head) {
      const after = ln.replace(new RegExp(`^${head}[：:]\\s*`), "").trim();
      i += 1;
      const buf: string[] = after ? [after] : [];
      while (i < lines.length) {
        const next = lines[i];
        if (sectionHeads.some((h) => next.startsWith(`${h}:`) || next.startsWith(`${h}：`) || next === h)) {
          break;
        }
        if (head === "用户原话" && buf.length >= 1 && next && /第\d+步|请只规划/.test(next)) {
          break;
        }
        buf.push(next);
        i += 1;
      }
      const value = buf.join("\n").trim() || "—";
      const pretty = tryPrettyJson(value);
      blocks.push({
        kind: "section",
        label: head,
        value: pretty || value,
        json: !!pretty,
      });
      continue;
    }

    const rest = lines.slice(i).join("\n").trim();
    if (rest) blocks.push({ kind: "prose", value: rest });
    break;
  }

  return blocks.length ? blocks : null;
}

function toContentBlocks(text: string): ContentBlock[] {
  const t = (text || "").trim();
  if (!t) return [{ kind: "prose", value: "（空）" }];

  const planner = splitPlannerBlocks(t);
  if (planner) return planner;

  const pretty = tryPrettyJson(t);
  if (pretty) return [{ kind: "code", value: pretty }];

  if (t.length <= 120 && !t.includes("\n\n") && t.split("\n").length <= 3) {
    return [{ kind: "prose", value: t }];
  }

  return [{ kind: "code", value: t }];
}

function ContentView({ text, tone = "default" }: { text: string; tone?: "default" | "reply" | "system" }) {
  const blocks = toContentBlocks(text);
  return (
    <div className={`llm-content tone-${tone}`}>
      {blocks.map((b, idx) => {
        if (b.kind === "kv") {
          return (
            <div key={idx} className="llm-kv">
              <span className="llm-kv-label">{b.label}</span>
              <span className="llm-kv-value">{b.value}</span>
            </div>
          );
        }
        if (b.kind === "section") {
          return (
            <div key={idx} className="llm-section">
              <div className="llm-section-label">{b.label}</div>
              {b.json ? <pre className="llm-code">{b.value}</pre> : <div className="llm-section-body">{b.value}</div>}
            </div>
          );
        }
        if (b.kind === "prose") {
          return (
            <div key={idx} className="llm-prose">
              {b.value}
            </div>
          );
        }
        return (
          <pre key={idx} className="llm-code">
            {b.value}
          </pre>
        );
      })}
    </div>
  );
}

function Fold({
  label,
  note,
  children,
  defaultOpen,
}: {
  label: string;
  note?: string;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  return (
    <details className="llm-fold" open={defaultOpen}>
      <summary>
        <strong>{label}</strong>
        {note ? <span className="llm-fold-note">{note}</span> : null}
      </summary>
      <div className="llm-fold-body">{children}</div>
    </details>
  );
}

function CallCard({ prompt, index, total }: { prompt: AgentLlmPrompt; index: number; total: number }) {
  const kind = inferCallKind(prompt);
  const parts = parseUserParts(prompt.user || "");
  const question = parts.find((p): p is Extract<UserPart, { kind: "text" }> => p.kind === "text" && p.key === "q");
  const sysChars = prompt.system_chars ?? (prompt.system || "").length;
  const outChars = prompt.completion_chars ?? (prompt.output || "").length;
  const elapsed = formatElapsed(prompt.elapsed_ms);
  const src = tokenSourceLabel(prompt.token_source);
  const mode = prompt.mode === "local" ? "本地" : prompt.mode === "remote" ? "云端" : "";

  return (
    <details className="llm-call">
      <summary className="llm-call-summary">
        <span className="llm-call-num" aria-hidden>
          {index + 1}
        </span>
        <div className="llm-call-summary-main">
          <div className="llm-call-summary-title">
            {kind.title}
            {total > 1 ? <span className="llm-call-of"> · {index + 1}/{total}</span> : null}
          </div>
          {question?.text ? <div className="llm-call-summary-q">{question.text}</div> : null}
          <div className="llm-call-summary-meta">
            {[
              `${prompt.prompt_chars ?? 0} 字`,
              `${prompt.total_tokens ?? 0} token`,
              src,
              mode && prompt.model ? `${mode} ${prompt.model}` : prompt.model,
            ]
              .filter(Boolean)
              .join(" · ")}
          </div>
        </div>
        <span className="llm-call-summary-time">{elapsed || "—"}</span>
      </summary>

      <div className="llm-call-body">
        <p className="llm-call-hint">{kind.hint}</p>
        <Fold label="系统指令" note={`${sysChars} 字`}>
          <ContentView text={prompt.system || "（空）"} tone="system" />
        </Fold>
        {parts.map((part) => {
          if (part.kind === "docs") {
            return (
              <Fold key={part.key} label={part.label} note={`${part.docs.length} 篇`} defaultOpen>
                <ol className="llm-doc-list">
                  {part.docs.map((doc) => (
                    <li key={doc.id}>
                      <details className="llm-doc">
                        <summary>
                          <span className="llm-doc-id">【{doc.id}】</span>
                          {doc.title}
                        </summary>
                        <div className="llm-doc-body">
                          <ContentView text={doc.text} />
                        </div>
                      </details>
                    </li>
                  ))}
                </ol>
              </Fold>
            );
          }
          return (
            <Fold key={part.key} label={part.label} note={`${part.text.length} 字`} defaultOpen>
              <ContentView text={part.text} />
            </Fold>
          );
        })}
        {prompt.output ? (
          <Fold label="模型回复" note={`${outChars} 字 / ${prompt.completion_tokens ?? 0} token`} defaultOpen>
            <ContentView text={prompt.output} tone="reply" />
          </Fold>
        ) : null}
      </div>
    </details>
  );
}

export function PromptCalls({
  recorded,
  llmUsed,
  prompts,
}: {
  recorded: boolean;
  llmUsed?: boolean;
  prompts: AgentLlmPrompt[];
}) {
  return (
    <div className="llm-feed">
      <div className="context-title-row">
        <div className="context-title">本轮送给模型的内容</div>
        <span className="context-count">{recorded ? `${prompts.length} 次调用` : "无记录"}</span>
      </div>
      {recorded && !llmUsed ? (
        <p className="empty-hint soft">这一轮没有调用大模型，没有可展开的原文。</p>
      ) : null}
      {prompts.map((p, i) => (
        <CallCard key={i} prompt={p} index={i} total={prompts.length} />
      ))}
    </div>
  );
}
