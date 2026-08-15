/** 对话框只留口语：去掉轨迹、名单、markdown */
export function extractAnswer(raw: string): string {
  if (!raw) return "";
  const cleaned = raw.replace(/\*\*/g, "").replace(/__/g, "").replace(/`/g, "");
  const lines = cleaned.split(/\r?\n/);
  const out: string[] = [];
  let started = false;
  for (const line of lines) {
    const t = line.trim();
    if (t.startsWith(">")) continue;
    if (t === "---") continue;
    if (/^参考[:：]/.test(t) || /^【\d+[,\s\d]*】$/.test(t)) continue;
    if (/^消息如下[:：]/.test(t)) continue;
    if (/^(微信|短信|邮件|钉钉|企业微信|QQ|iMessage)\s*[·•.\-]\s*.+[:：]/.test(t)) continue;
    if (/想去哪家[，,]?跟我说导航/.test(t)) continue;
    if (/(依据面板|过程面板|检索成功|口语候选)/.test(t)) continue;
    if (/^\d+[\.、)]\s*\S+/.test(t) && /(米|路|街|号)/.test(t)) continue;
    if (t.includes(" · ") && /(路|街|号|店|米)/.test(t) && !/[吗呢吧啊噢哦～]$/.test(t)) continue;
    if (!t && !started) continue;
    started = true;
    out.push(line.replace(/\*\*/g, ""));
  }
  return out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
}

export type RetrievedDoc = {
  index: number;
  title: string;
  page?: string | number | null;
  content: string;
  preview?: string;
  kind?: string;
};

export function normalizeContexts(data: unknown): RetrievedDoc[] {
  if (!Array.isArray(data)) return [];
  return data.map((item, i) => {
    if (typeof item === "string") {
      const text = item.trim();
      return {
        index: i + 1,
        title: `手册片段 ${i + 1}`,
        content: text,
        preview: text.slice(0, 140) + (text.length > 140 ? "…" : ""),
      };
    }
    const obj = (item || {}) as Record<string, unknown>;
    const content = String(obj.content ?? obj.text ?? obj.page_content ?? "");
    const kind = obj.kind != null ? String(obj.kind) : undefined;
    const defaultTitle =
      kind === "message"
        ? `消息 ${i + 1}`
        : kind === "amap_poi"
          ? `周边地点 ${i + 1}`
          : `手册片段 ${i + 1}`;
    return {
      index: Number(obj.index ?? i + 1),
      title: String(obj.title ?? defaultTitle),
      page: (obj.page as string | number | null | undefined) ?? null,
      content,
      preview: String(obj.preview ?? content.slice(0, 140)),
      kind,
    };
  });
}

/** 依据面板文案：手册 / 周边 / 消息 */
export function contextSourceLabel(docs?: RetrievedDoc[] | null): {
  short: string;
  tab: string;
  section: string;
  meta: string;
} {
  const allMsg = !!docs?.length && docs.every((d) => d.kind === "message");
  if (allMsg) {
    return {
      short: "条消息",
      tab: "消息原文",
      section: "消息原文",
      meta: "消息",
    };
  }
  const allPoi = !!docs?.length && docs.every((d) => d.kind === "amap_poi");
  if (allPoi) {
    return {
      short: "篇周边",
      tab: "检索依据",
      section: "周边地点",
      meta: "地点",
    };
  }
  return {
    short: "篇手册",
    tab: "手册依据",
    section: "手册原文",
    meta: "原文",
  };
}
