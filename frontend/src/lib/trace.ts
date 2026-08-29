import type { TraceStep } from "@/lib/types";
import { collectDocImages, normalizeContexts, type RetrievedDoc, type RetrievedImage } from "@/lib/answer";

/** 能体现 Agent 能力的步骤（剔除会话/循环/装配等基建噪声） */
const SHOWCASE_TYPES = new Set([
  "intent",
  "tool",
  "policy",
  "confirm",
  "search",
  "knowledge",
  "response",
  "memory",
  "error",
]);

const INTENT_CN: Record<string, string> = {
  tool: "控车",
  multi_tool: "多工具编排",
  search: "查车况",
  knowledge: "查手册",
  chat: "闲聊",
  confirm: "确认执行",
  cancel: "取消操作",
};

const TYPE_LABEL: Record<string, string> = {
  intent: "识别意图",
  tool: "执行工具",
  policy: "安全策略",
  confirm: "等待确认",
  search: "读取车况",
  knowledge: "检索手册",
  response: "生成回复",
  memory: "更新画像",
  error: "异常",
};

const TOOL_CN: Record<string, string> = {
  "climate.set_power": "空调开关",
  "climate.set_temperature": "设定温度",
  "climate.adjust_temperature": "调节温度",
  "climate.set_fan": "调节风量",
  "climate.set_mode": "空调模式",
  "seat.set": "座椅功能",
  "seat.steering_wheel_heat": "方向盘加热",
  "cabin.set_windows": "车窗/天窗",
  "cabin.adjust_windows": "调节车窗",
  "cabin.set_door_locks": "车门锁",
  "cabin.set_trunk": "后备箱",
  "cabin.set_frunk": "前备箱",
  "cabin.set_charge_port": "充电口",
  "cabin.set_lights": "灯光",
  "cabin.set_displays": "屏幕亮度",
  "media.play_music": "播放音乐",
  "media.pause": "暂停媒体",
  "media.control_music": "播放控制",
  "media.switch_music": "切换歌曲",
  "media.seek_music": "调整进度",
  "media.play_radio": "播放电台",
  "media.control_radio": "电台控制",
  "media.switch_radio": "切换电台",
  "media.set_volume": "音量",
  "maps.search_nearby": "搜索周边",
  "web.search": "网页搜索",
  "navigation.navigate_to": "开始导航",
  "navigation.start": "开始导航",
  "navigation.stop": "结束导航",
  "driving.set_adas": "驾驶辅助",
  "driving.set_gear": "换挡",
  "driving.set_speed": "设定车速",
  "driving.set_child_lock": "儿童锁",
  "apps.open": "打开应用",
  "apps.close": "关闭应用",
};

const SEAT_CN: Record<string, string> = {
  front_left: "主驾",
  front_right: "副驾",
  rear_left: "左后",
  rear_middle: "中后",
  rear_right: "右后",
  sunroof: "天窗",
};

const ARG_CN: Record<string, string> = {
  enable: "开关",
  zones: "区域",
  positions: "位置",
  temperature: "温度",
  delta: "调节",
  level: "档位",
  mode: "模式",
  feature: "功能",
  percent: "开合",
  artist: "歌手",
  title: "曲目",
  destination: "目的地",
  query: "关键词",
  count: "条数",
  recirculation: "循环",
  locked: "锁定",
  open: "开启",
};

const FEATURE_CN: Record<string, string> = {
  heat: "加热",
  ventilation: "通风",
  massage: "按摩",
};

export type ShowcaseStep = {
  id: string;
  type: string;
  typeLabel: string;
  title: string;
  summary?: string;
  detailLines?: string[];
  docs?: RetrievedDoc[];
  images?: RetrievedImage[];
  status?: string;
  index: number;
  ts?: number;
  elapsedMs?: number;
};

export function formatElapsed(ms?: number | null) {
  if (ms == null || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const s = ms / 1000;
  if (s < 10) return `${s.toFixed(1)} s`;
  return `${Math.round(s)} s`;
}

function toolLabel(name: string): string {
  return TOOL_CN[name] || name.replace(/\./g, " · ");
}

function placeLabel(v: unknown): string {
  if (Array.isArray(v)) return v.map((x) => placeLabel(x)).join("、");
  const s = String(v);
  return SEAT_CN[s] || s;
}

function valueLabel(key: string, value: unknown): string {
  if (key === "zones" || key === "positions") return placeLabel(value);
  if (key === "feature") return FEATURE_CN[String(value)] || String(value);
  if (key === "enable" || key === "locked" || key === "open" || key === "recirculation") {
    return value ? "开" : "关";
  }
  if (key === "temperature") return `${value}°C`;
  if (key === "delta") return `${Number(value) > 0 ? "+" : ""}${value}°C`;
  if (key === "percent") return `${value}%`;
  if (key === "level") return `${value} 档`;
  if (typeof value === "boolean") return value ? "是" : "否";
  if (Array.isArray(value)) return value.map(String).join("、");
  if (value && typeof value === "object") {
    try {
      return JSON.stringify(value);
    } catch {
      return String(value);
    }
  }
  return String(value);
}

function formatArgs(args: unknown): string[] {
  if (!args || typeof args !== "object") return [];
  return Object.entries(args as Record<string, unknown>)
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `${ARG_CN[k] || k} ${valueLabel(k, v)}`);
}

function statusOf(s: TraceStep): string {
  return s.status || "ok";
}

/** 过滤并润色轨迹，只保留给人扫读的能力步骤 */
export function toShowcaseSteps(steps: TraceStep[], endedAt?: number): ShowcaseStep[] {
  const out: ShowcaseStep[] = [];
  let knowledgeMerged = false;

  for (const s of steps) {
    if (!SHOWCASE_TYPES.has(s.type)) continue;
    const detail = (s.detail || {}) as Record<string, unknown>;

    if (s.type === "intent") {
      const intent = String(detail.intent || "").toLowerCase();
      const label = INTENT_CN[intent] || s.title.replace(/^意图\s*/, "") || "已识别";
      const conf = detail.confidence != null ? Number(detail.confidence) : null;
      const reason = detail.reason ? String(detail.reason) : "";
      const seat = detail.active_seat_cn
        ? String(detail.active_seat_cn)
        : detail.active_seat
          ? String(detail.active_seat)
          : "";
      const lines = [
        reason && `依据：${reason}`,
        conf != null && !Number.isNaN(conf) ? `置信度 ${(conf * 100).toFixed(0)}%` : "",
        seat && `当前座位：${SEAT_CN[seat] || seat}`,
      ].filter(Boolean) as string[];
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.intent,
        title: label,
        summary: reason || undefined,
        detailLines: lines.length ? lines : undefined,
        status: statusOf(s),
        index: 0,
      });
      continue;
    }

    if (s.type === "tool") {
      const name = String(detail.tool || s.title || "").replace(/^执行\s*/, "");
      const toolName = name.includes(".") ? name : s.title.replace(/^执行\s*/, "");
      const result = detail.result != null ? String(detail.result) : "";
      const argLines = formatArgs(detail.arguments);
      const pois = Array.isArray(detail.pois) ? detail.pois : [];
      const messages = Array.isArray(detail.messages) ? detail.messages : [];
      const messageLines = Array.isArray(detail.message_lines)
        ? detail.message_lines.map(String)
        : [];
      const candidates = Array.isArray(detail.candidates) ? detail.candidates : [];
      const source = detail.source != null ? String(detail.source) : "";
      const toolApi = detail.tool_api != null ? String(detail.tool_api) : "";
      const count = detail.count != null ? Number(detail.count) : pois.length;
      const poiLines = pois.map((raw, i) => {
        const p = (raw || {}) as Record<string, unknown>;
        const dist = p.distance != null && p.distance !== "" ? `${p.distance}米` : "";
        return [i + 1, p.name, dist, p.address].filter(Boolean).join(" · ");
      });
      const msgLines =
        messageLines.length > 0
          ? messageLines
          : messages.map((raw, i) => {
              const m = (raw || {}) as Record<string, unknown>;
              const flag = m.unread ? "未读" : "已读";
              return [i + 1, `[${flag}]`, m.app, m.from, m.text].filter(Boolean).join(" · ");
            });
      const candLines = candidates.map((raw, i) => {
        const p = (raw || {}) as Record<string, unknown>;
        return [p.index ?? i + 1, p.name, p.address].filter(Boolean).join(" · ");
      });
      const detailLines = [
        ...argLines.map((line) => `参数 · ${line}`),
        source || toolApi
          ? `来源 · ${source === "amap_mcp" ? "高德 MCP" : source === "amap_rest" ? "高德 REST" : source}${toolApi ? ` · ${toolApi}` : ""}`
          : "",
        pois.length ? `检索结果 · 共 ${count || pois.length} 家` : "",
        ...poiLines.map((line) => `地点 · ${line}`),
        messages.length || msgLines.length
          ? `消息 · 共 ${detail.count ?? messages.length ?? msgLines.length} 条（未读 ${detail.unread_count ?? "?"}）`
          : "",
        ...msgLines.map((line) => String(line)),
        candidates.length ? `待确认目的地 · ${candidates.length} 处` : "",
        ...candLines.map((line) => `选项 · ${line}`),
        !pois.length && !candidates.length && !msgLines.length && result ? `结果 · ${result}` : "",
        candidates.length && result ? `结果 · ${result}` : "",
        msgLines.length && result ? `结果 · ${result}` : "",
      ].filter(Boolean);
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.tool,
        title: toolLabel(toolName),
        summary: pois.length
          ? `${source === "amap_mcp" ? "MCP" : "地图"}检索到 ${count || pois.length} 家`
          : messages.length || msgLines.length
            ? `已读取 ${detail.count ?? messages.length ?? msgLines.length} 条消息`
          : candidates.length
            ? `目的地待确认 · ${candidates.length} 处`
          : result || (argLines.length ? argLines.join(" · ") : undefined),
        detailLines: detailLines.length ? detailLines : undefined,
        status: statusOf(s),
        index: 0,
      });
      continue;
    }

    if (s.type === "knowledge") {
      if (!knowledgeMerged) {
        knowledgeMerged = true;
        const later = steps.find((x) => {
          if (x.type !== "knowledge") return false;
          const d = (x.detail || {}) as Record<string, unknown>;
          return d.doc_count != null || !!d.error || (x.status || "") === "error";
        });
        const laterDetail = ((later?.detail || {}) as Record<string, unknown>) || {};
        const err = String(laterDetail.error || detail.error || "");
        const failed = (later?.status || s.status || "") === "error" || !!err;
        const nRaw = laterDetail.doc_count ?? detail.doc_count;
        const n = nRaw != null ? Number(nRaw) : null;
        const docs = normalizeContexts(laterDetail.docs ?? detail.docs);
        const images = collectDocImages(docs);
        const imgN = images.length;
        out.push({
          id: (later || s).id,
          type: s.type,
          typeLabel: TYPE_LABEL.knowledge,
          title: failed ? "检索手册失败" : n != null && n > 0 ? `命中 ${n} 篇手册` : "未命中手册",
          summary: failed
            ? "知识库连不上，没有取到原文"
            : n != null && n > 0
              ? imgN > 0
                ? `已取回原文，含 ${imgN} 张插图`
                : "已从知识库取回相关原文"
              : "手册里没有贴合的片段",
          detailLines: failed
            ? [err ? `报错：${err}` : "知识库不可用"].filter(Boolean)
            : docs.length
              ? undefined
              : n != null
                ? [`检索结果：${n} 篇`]
                : undefined,
          docs: docs.length ? docs : undefined,
          images: imgN ? images : undefined,
          status: failed ? "error" : statusOf(later || s),
          index: 0,
        });
      }
      continue;
    }

    if (s.type === "search") {
      const seat = detail.active_seat_cn || detail.active_seat;
      const err = detail.error != null ? String(detail.error) : "";
      const failed = (s.status || "") === "error" || !!err;
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.search,
        title: failed ? s.title || "读取车况失败" : "读取实时车况",
        summary: failed
          ? "口语生成失败，已改走车况兜底"
          : seat
            ? `围绕 ${SEAT_CN[String(seat)] || seat} 座位`
            : "读取车辆状态快照",
        detailLines: [
          seat ? `当前座位：${SEAT_CN[String(seat)] || seat}` : "",
          err ? `报错：${err}` : "",
        ].filter(Boolean),
        status: failed ? "error" : statusOf(s),
        index: 0,
      });
      continue;
    }

    if (s.type === "error") {
      const err = detail.error != null ? String(detail.error) : "";
      const kind = detail.kind != null ? String(detail.kind) : "";
      const mode = detail.llm_mode != null ? String(detail.llm_mode) : "";
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.error,
        title: s.title || "调用失败",
        summary: kind ? `原因类型：${kind}` : "见报错详情",
        detailLines: [
          kind ? `类型：${kind}` : "",
          mode ? `模型：${mode === "local" ? "本地" : "云端"}` : "",
          err ? `报错：${err}` : "",
        ].filter(Boolean),
        status: "error",
        index: 0,
      });
      continue;
    }

    if (s.type === "policy") {
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.policy,
        title: s.title || "策略拦截",
        summary: detail.message ? String(detail.message) : undefined,
        detailLines: detail.message ? [String(detail.message)] : undefined,
        status: statusOf(s),
        index: 0,
      });
      continue;
    }

    if (s.type === "confirm") {
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.confirm,
        title: s.title || "需要确认",
        summary: detail.summary ? String(detail.summary) : detail.message ? String(detail.message) : undefined,
        detailLines: [
          detail.message ? String(detail.message) : "",
          detail.summary ? `待执行：${detail.summary}` : "",
        ].filter(Boolean),
        status: statusOf(s),
        index: 0,
      });
      continue;
    }

    if (s.type === "response") {
      const preview = detail.answer != null ? String(detail.answer) : "";
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.response,
        title: "生成回复",
        summary: preview ? (preview.length > 72 ? `${preview.slice(0, 70)}…` : preview) : "已完成回答",
        detailLines: preview ? [preview] : undefined,
        status: statusOf(s),
        index: 0,
      });
      continue;
    }

    if (s.type === "memory") {
      const bits = [
        detail.memories_updated ? "记忆" : "",
        detail.persona_updated ? "人设" : "",
        detail.preferences_updated ? "偏好" : "",
      ].filter(Boolean);
      const notes = Array.isArray(detail.notes) ? detail.notes.map(String) : [];
      out.push({
        id: s.id,
        type: s.type,
        typeLabel: TYPE_LABEL.memory,
        title: s.title || "更新记忆/人设/偏好",
        summary: bits.length ? `已更新：${bits.join("、")}` : undefined,
        detailLines: notes.length ? notes.map(String) : undefined,
        status: statusOf(s),
        index: 0,
      });
      continue;
    }

    out.push({
      id: s.id,
      type: s.type,
      typeLabel: TYPE_LABEL[s.type] || s.type,
      title: s.title,
      status: statusOf(s),
      index: 0,
    });
  }

  const tsById = new Map(steps.map((s) => [s.id, s.ts]));
  return out.map((step, i) => {
    const ts = tsById.get(step.id);
    const nextId = out[i + 1]?.id;
    const nextTs = (nextId ? tsById.get(nextId) : undefined) ?? endedAt;
    let elapsedMs: number | undefined;
    if (ts && nextTs && nextTs >= ts) {
      elapsedMs = Math.max(0, Math.round((nextTs - ts) * 1000));
    }
    return { ...step, index: i + 1, ts, elapsedMs };
  });
}

export function intentLabel(intent?: string): string {
  if (!intent) return "—";
  return INTENT_CN[intent.toLowerCase()] || intent;
}

export function statusLabel(status?: string): string {
  switch ((status || "").toLowerCase()) {
    case "ok":
    case "done":
    case "success":
      return "完成";
    case "warn":
    case "need_confirm":
      return "待确认";
    case "error":
    case "blocked":
      return "失败";
    case "cancelled":
      return "已取消";
    case "running":
      return "进行中";
    default:
      return status || "完成";
  }
}
