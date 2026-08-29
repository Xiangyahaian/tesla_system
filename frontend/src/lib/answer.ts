/** 对话框展示 vs 语音播报：Agent 可用【听】【看】控制念什么 */

const RAW_ERROR_RE =
  /Error code:|Traceback \(most recent call last\)|Arrearage|invalid_request_error|openai\.|httpx\.|APIStatusError|BadRequestError|request_id|TAVILY_API_KEY|BOCHA_API_KEY|BAILIAN_API_KEY|Access denied, please make sure your account|\b[A-Z][A-Za-z]+(?:Error|Exception|Timeout)\s*\(|\{['"]error['"]/;

const SPOKEN_ERROR_FALLBACK = "这步没做成。你可以换个说法再试，或先切到本地模型。";

export function looksLikeRawError(text: string): boolean {
  return !!text && RAW_ERROR_RE.test(text);
}

export function publicErrorText(text: string, fallback = SPOKEN_ERROR_FALLBACK): string {
  const t = (text || "").trim();
  if (!t || looksLikeRawError(t)) return fallback;
  return t;
}

/** 去掉 emoji / 装饰符号，避免手册回答里再出现灯泡、对勾等 */
export function stripEmoji(text: string): string {
  if (!text) return "";
  return text
    .replace(/[\uFE0F\u200D]/g, "")
    .replace(/[\u{1F000}-\u{1FFFF}]/gu, "")
    .replace(/[\u2600-\u27BF]/g, "");
}

/** 去掉轨迹/名单后的屏幕展示文案（保留步骤与小提示，去掉控制标记） */
export function extractAnswer(raw: string): string {
  if (!raw) return "";
  let cleaned = stripEmoji(raw).replace(/\*\*/g, "").replace(/__/g, "").replace(/`/g, "");
  // 控制标记只影响语音，屏幕上仍展示其内容
  cleaned = cleaned.replace(/【听】/g, "").replace(/【看】/g, "\n");
  cleaned = cleaned.replace(/\[\[说\]\]/g, "").replace(/\[\[\/说\]\]/g, "");
  cleaned = cleaned.replace(/\[\[看\]\]/g, "\n").replace(/\[\[\/看\]\]/g, "");

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
    if (/用户也可以直接说|完整店名|第几个/.test(t)) continue;
    if (/(依据面板|过程面板|检索成功|口语候选|尚未开始导航|不要擅自)/.test(t)) continue;
    if (/^\d+[\.、)]\s*\S+/.test(t) && /(米|路|街|号)/.test(t)) continue;
    if (t.includes(" · ") && /(路|街|号|店|米)/.test(t) && !/[吗呢吧啊噢哦～]$/.test(t)) continue;
    if (looksLikeRawError(t)) continue;
    if (!t && !started) continue;
    started = true;
    out.push(line.replace(/\*\*/g, ""));
  }
  const joined = out.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  const cleanedFinal = dedupeUnreadNudgeLines(joined);
  if (!cleanedFinal && looksLikeRawError(raw)) return SPOKEN_ERROR_FALLBACK;
  if (looksLikeRawError(cleanedFinal)) return SPOKEN_ERROR_FALLBACK;
  return cleanedFinal;
}

/** 同一条回答里未读提醒只保留一处（防直播+落盘重复 emit） */
function dedupeUnreadNudgeLines(text: string): string {
  const unreadRe = /未读消息/;
  const detailRe = /您有|条未读/;
  let seen = false;
  const kept: string[] = [];
  for (const line of text.split(/\r?\n/)) {
    const t = line.trim();
    if (unreadRe.test(t) && detailRe.test(t)) {
      if (seen) continue;
      seen = true;
    }
    kept.push(line);
  }
  return kept.join("\n").trim();
}

function cleanSpeakChunk(text: string): string {
  return stripEmoji(text)
    .replace(/^>.*$/gm, "")
    .replace(/【\d+(?:\s*[,，、]\s*\d+)*】/g, "")
    .replace(/^参考[:：].*$/gm, "")
    .replace(/^小提示[:：].*$/gm, "")
    .replace(/[#*`_]/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/**
 * Agent 控制的播报文本：优先【听】…【看】之间（或到文末）。
 * 无标记时：只念结论口语，跳过小提示/参考/冗长步骤列表。
 */
export function extractSpeakText(raw: string): string {
  if (!raw) return "";
  const cleaned = raw.replace(/\*\*/g, "").replace(/__/g, "").replace(/`/g, "");

  const tagged =
    cleaned.match(/【听】([\s\S]*?)(?=【看】|$)/)?.[1] ??
    cleaned.match(/\[\[说\]\]([\s\S]*?)\[\[\/说\]\]/)?.[1] ??
    null;
  if (tagged != null) {
    const spoken = cleanSpeakChunk(tagged).slice(0, 160);
    return looksLikeRawError(spoken) ? SPOKEN_ERROR_FALLBACK : spoken;
  }

  // 仅有【看】时只播标记前的口语，未读提醒等屏幕文案不念
  if (/【看】/.test(cleaned)) {
    const oral = cleaned.split("【看】")[0]?.trim() || "";
    if (oral) {
      const spoken = cleanSpeakChunk(oral).slice(0, 160);
      return looksLikeRawError(spoken) ? SPOKEN_ERROR_FALLBACK : spoken;
    }
  }

  // 无标记：从展示文案推导「该念的部分」
  const display = extractAnswer(raw);
  if (!display) return "";

  const lines = display.split(/\r?\n/).map((l) => l.trim()).filter(Boolean);
  const oral: string[] = [];
  for (const line of lines) {
    if (/^小提示[:：]/.test(line)) break;
    if (/^参考[:：]/.test(line)) break;
    if (/^注意[:：]/.test(line)) break;
    // 步骤列表：只念结论，不念 1.2.3.（开车时听步骤不安全也嘈杂）
    if (/^\d+[\.、)]\s+/.test(line)) break;
    if (/^[-•]\s+/.test(line)) break;
    oral.push(line);
  }
  if (!oral.length) {
    // 全文都是步骤：只念第一条去编号
    const first = lines[0]?.replace(/^\d+[\.、)]\s+/, "").replace(/^[-•]\s+/, "") || "";
    const spoken = cleanSpeakChunk(first).slice(0, 120);
    return looksLikeRawError(spoken) ? SPOKEN_ERROR_FALLBACK : spoken;
  }
  const spoken = cleanSpeakChunk(oral.join(" ")).slice(0, 160);
  return looksLikeRawError(spoken) ? SPOKEN_ERROR_FALLBACK : spoken;
}

export type RetrievedImage = {
  image_path: string;
  title?: string;
};

export type RetrievedDoc = {
  index: number;
  title: string;
  page?: string | number | null;
  content: string;
  preview?: string;
  kind?: string;
  url?: string;
  images?: RetrievedImage[];
};

function normalizeImages(raw: unknown): RetrievedImage[] | undefined {
  if (!Array.isArray(raw)) return undefined;
  const out: RetrievedImage[] = [];
  const seen = new Set<string>();
  for (const item of raw) {
    const obj = (item || {}) as Record<string, unknown>;
    const path = String(obj.image_path ?? obj.relative_path ?? "").trim();
    if (!path || seen.has(path)) continue;
    seen.add(path);
    const title = String(obj.title ?? "").trim();
    out.push(title ? { image_path: path, title } : { image_path: path });
  }
  return out.length ? out : undefined;
}

export function collectDocImages(docs?: RetrievedDoc[] | null): RetrievedImage[] {
  if (!docs?.length) return [];
  const out: RetrievedImage[] = [];
  const seen = new Set<string>();
  for (const d of docs) {
    for (const img of d.images || []) {
      if (!img.image_path || seen.has(img.image_path)) continue;
      seen.add(img.image_path);
      out.push(img);
    }
  }
  return out;
}

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
          : kind === "web"
            ? `网页 ${i + 1}`
            : `手册片段 ${i + 1}`;
    return {
      index: Number(obj.index ?? i + 1),
      title: String(obj.title ?? defaultTitle),
      page: (obj.page as string | number | null | undefined) ?? null,
      content,
      preview: String(obj.preview ?? content.slice(0, 140)),
      kind,
      url: obj.url != null ? String(obj.url) : undefined,
      images: normalizeImages(obj.images),
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
  const allWeb = !!docs?.length && docs.every((d) => d.kind === "web");
  if (allWeb) {
    return {
      short: "条网页",
      tab: "检索依据",
      section: "网页来源",
      meta: "网页",
    };
  }
  return {
    short: "篇手册",
    tab: "手册依据",
    section: "手册原文",
    meta: "原文",
  };
}
