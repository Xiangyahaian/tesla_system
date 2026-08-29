import type { SessionSummary } from "@/lib/api";

const STAMP_RE = /\d{4}-\d{2}-\d{2} \d{2}:\d{2}/;

export function formatSessionStamp(ts?: number | string | null) {
  if (ts == null || ts === "") return "";
  const n = typeof ts === "string" ? Number(ts) : ts;
  if (!Number.isFinite(n) || n <= 0) return "";
  const ms = n > 0 && n < 1e12 ? n * 1000 : n;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return "";
  const p = (v: number) => String(v).padStart(2, "0");
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

export function sessionDisplayName(s: Pick<SessionSummary, "title" | "is_home" | "owner_nickname" | "created_at" | "updated_at">) {
  const stamp = formatSessionStamp(s.created_at || s.updated_at);
  const raw = (s.title || "").trim();
  let base: string;
  if (s.is_home) {
    if (raw && raw !== s.owner_nickname && raw !== "新会话" && !raw.startsWith("会话 ")) {
      base = raw;
    } else {
      base = "主会话";
    }
  } else if (!raw || raw === "新会话" || raw === s.owner_nickname) {
    base = "会话";
  } else {
    base = raw;
  }
  if (stamp && STAMP_RE.test(base)) return base;
  return stamp ? `${base} · ${stamp}` : base;
}
