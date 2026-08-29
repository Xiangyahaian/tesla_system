import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { useLocation, useNavigate } from "react-router-dom";
import {
  createSession,
  deleteSession,
  fetchSessions,
  renameSession,
  type SessionSummary,
} from "@/lib/api";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";
import { sessionDisplayName } from "@/lib/sessionTitle";

const BUCKETS = ["今天", "昨天", "近 7 天", "近 30 天", "更早"] as const;

type Bucket = (typeof BUCKETS)[number];

function sessionMs(s: SessionSummary) {
  const t = s.updated_at || s.last_active || s.created_at || 0;
  return t > 0 && t < 1e12 ? t * 1000 : t;
}

function bucketOf(ms: number): Bucket {
  const start = new Date();
  start.setHours(0, 0, 0, 0);
  const today = start.getTime();
  if (ms >= today) return "今天";
  if (ms >= today - 86400000) return "昨天";
  if (ms >= today - 7 * 86400000) return "近 7 天";
  if (ms >= today - 30 * 86400000) return "近 30 天";
  return "更早";
}

function relativeTime(ts?: number) {
  if (!ts) return "";
  const ms = ts < 1e12 ? ts * 1000 : ts;
  const diff = Date.now() - ms;
  if (diff < 45 * 1000) return "刚刚";
  if (diff < 60 * 60 * 1000) return `${Math.max(1, Math.round(diff / 60000))} 分钟前`;
  if (diff < 24 * 60 * 60 * 1000) return `${Math.max(1, Math.round(diff / 3600000))} 小时前`;
  if (diff < 7 * 24 * 60 * 60 * 1000) return `${Math.max(1, Math.round(diff / 86400000))} 天前`;
  const d = new Date(ms);
  return `${d.getMonth() + 1}/${d.getDate()}`;
}

function displayTitle(s: SessionSummary) {
  return sessionDisplayName(s);
}

function displayPreview(s: SessionSummary, title: string) {
  const preview = (s.preview || "").replace(/\s+/g, " ").trim();
  if (!preview || preview === title) {
    const n = s.message_count ?? 0;
    return n ? `${n} 条对话` : "还没有对话";
  }
  return preview.slice(0, 80);
}

type Props = {
  variant?: "page" | "drawer";
  onConsumed?: () => void;
};

export function SessionManagerPanel({ variant = "page", onConsumed }: Props) {
  const navigate = useNavigate();
  const location = useLocation();
  const sessionId = useCabinStore((s) => s.sessionId);
  const authSessionId = useCabinStore((s) => s.authSessionId);
  const historyEpoch = useCabinStore((s) => s.historyEpoch);
  const { switchSession } = useCabinRuntime();
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [openingId, setOpeningId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [editingId, setEditingId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState("");
  const [pendingDelete, setPendingDelete] = useState<string | null>(null);

  const finishOpen = useCallback(() => {
    onConsumed?.();
    if (location.pathname !== "/") navigate("/");
  }, [location.pathname, navigate, onConsumed]);

  const reload = useCallback(async () => {
    try {
      const data = await fetchSessions();
      setSessions(data.sessions || []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载会话失败");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload, sessionId, historyEpoch]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = [...sessions].sort((a, b) => sessionMs(b) - sessionMs(a));
    if (!q) return rows;
    return rows.filter((s) => {
      const hay = `${sessionDisplayName(s)} ${s.title || ""} ${s.preview || ""} ${s.owner_nickname || ""}`.toLowerCase();
      return hay.includes(q);
    });
  }, [query, sessions]);

  const groups = useMemo(() => {
    const map = new Map<Bucket, SessionSummary[]>();
    for (const label of BUCKETS) map.set(label, []);
    for (const s of filtered) {
      const b = bucketOf(sessionMs(s) || 0);
      map.get(b)!.push(s);
    }
    if (query.trim()) {
      return [{ label: "搜索结果", items: filtered }].filter((g) => g.items.length);
    }
    return BUCKETS.map((label) => ({ label, items: map.get(label) || [] })).filter((g) => g.items.length);
  }, [filtered, query]);

  const openSession = async (s: SessionSummary) => {
    if (busy || openingId || editingId) return;
    if (s.session_id === sessionId) {
      finishOpen();
      return;
    }
    setOpeningId(s.session_id);
    setError(null);
    try {
      await switchSession(s.session_id, s.title);
      finishOpen();
    } catch (e) {
      setError(e instanceof Error ? e.message : "打开会话失败");
    } finally {
      setOpeningId(null);
    }
  };

  const onCreate = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await createSession();
      setSessions(res.sessions || []);
      await switchSession(res.session_id, res.title);
      finishOpen();
    } catch (e) {
      setError(e instanceof Error ? e.message : "新建失败");
    } finally {
      setBusy(false);
    }
  };

  const onRename = async (id: string) => {
    const title = editTitle.trim();
    if (!title) {
      setEditingId(null);
      return;
    }
    setBusy(true);
    try {
      const res = await renameSession(id, title);
      setSessions(res.sessions || []);
      if (id === sessionId) useCabinStore.getState().setSessionTitle(title);
      setEditingId(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    } finally {
      setBusy(false);
    }
  };

  const onDelete = async (s: SessionSummary) => {
    if (s.session_id === "default" || s.is_home) return;
    setBusy(true);
    try {
      const res = await deleteSession(s.session_id);
      setSessions(res.sessions || []);
      setPendingDelete(null);
      if (s.session_id === sessionId) {
        const home = authSessionId || res.sessions?.find((x) => x.is_home)?.session_id;
        if (home) {
          const homeRow = (res.sessions || []).find((x) => x.session_id === home);
          await switchSession(home, homeRow?.title || "主会话");
        }
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={`session-desk is-${variant}`}>
      {variant === "page" ? (
        <div className="session-studio-head">
          <div>
            <h3>历史记录</h3>
            <p>
              点一条即可载入并回到驾驶助手。主会话用于登录，不可删除。
              驾驶页「新会话」会另开一条，当前对话留在本列表。
            </p>
            <p className="session-store-hint">
              保存在本机 <code>state/cabin_sessions.db</code>。用户目录{" "}
              <code>state/sessions/&lt;user&gt;/</code> 共享车况和记忆；每段对话在{" "}
              <code>sessions/&lt;id&gt;/</code> 单独落盘。
            </p>
          </div>
          <span className="session-count">{sessions.length} 条</span>
        </div>
      ) : null}

      <div className="session-desk-toolbar">
        <label className="session-search">
          <svg viewBox="0 0 24 24" aria-hidden>
            <circle cx="11" cy="11" r="6.5" />
            <path d="M16.2 16.2L21 21" />
          </svg>
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="搜索自己的会话"
            aria-label="搜索会话"
          />
        </label>
        <button type="button" className="session-new" disabled={busy || !!openingId} onClick={() => void onCreate()}>
          新会话
        </button>
      </div>

      {error ? <div className="session-banner">{error}</div> : null}

      <div className="session-desk-list" role="list">
        {!loaded ? (
          <div className="session-skel" aria-hidden>
            {Array.from({ length: 6 }).map((_, i) => (
              <div key={i} className="session-skel-row" />
            ))}
          </div>
        ) : null}

        {loaded
          ? groups.map((g) => (
              <section key={g.label} className="session-group">
                <h4>{g.label}</h4>
                <AnimatePresence initial={false}>
                  {g.items.map((s) => {
                    const active = s.session_id === sessionId;
                    const editing = editingId === s.session_id;
                    const confirming = pendingDelete === s.session_id;
                    const locked = s.session_id === "default" || !!s.is_home;
                    const title = displayTitle(s);
                    const preview = displayPreview(s, title);
                    const opening = openingId === s.session_id;
                    return (
                      <motion.div
                        key={s.session_id}
                        role="listitem"
                        layout
                        initial={{ opacity: 0, y: 6 }}
                        animate={{ opacity: 1, y: 0 }}
                        exit={{ opacity: 0, height: 0 }}
                        transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
                        className={`session-item${active ? " is-active" : ""}${opening ? " is-opening" : ""}`}
                      >
                        {editing ? (
                          <form
                            className="session-item-rename"
                            onSubmit={(e: FormEvent) => {
                              e.preventDefault();
                              void onRename(s.session_id);
                            }}
                          >
                            <input
                              value={editTitle}
                              autoFocus
                              maxLength={80}
                              aria-label="会话标题"
                              onChange={(e) => setEditTitle(e.target.value)}
                              onKeyDown={(e) => {
                                if (e.key === "Escape") setEditingId(null);
                              }}
                            />
                            <button type="submit" className="session-glyph" disabled={busy} aria-label="保存">
                              <svg viewBox="0 0 24 24" aria-hidden>
                                <path d="M5 12.5l4.2 4.2L19 7.5" />
                              </svg>
                            </button>
                            <button type="button" className="session-glyph" onClick={() => setEditingId(null)} aria-label="取消">
                              <svg viewBox="0 0 24 24" aria-hidden>
                                <path d="M6 6l12 12M18 6L6 18" />
                              </svg>
                            </button>
                          </form>
                        ) : confirming ? (
                          <div className="session-item-confirm">
                            <span>删除后无法恢复</span>
                            <div>
                              <button
                                type="button"
                                className="session-icon-btn danger"
                                disabled={busy}
                                onClick={() => void onDelete(s)}
                              >
                                删除
                              </button>
                              <button type="button" className="session-icon-btn" onClick={() => setPendingDelete(null)}>
                                取消
                              </button>
                            </div>
                          </div>
                        ) : (
                          <>
                            <button
                              type="button"
                              className="session-item-main"
                              disabled={busy || !!openingId}
                              onClick={() => void openSession(s)}
                            >
                              <i className="session-dot" aria-hidden />
                              <span className="session-item-copy">
                                <strong>
                                  {title}
                                  {s.is_home ? <em>主</em> : null}
                                  {active ? <em className="now">当前</em> : null}
                                </strong>
                                <span>{opening ? "正在载入…" : preview}</span>
                              </span>
                              <time dateTime={sessionMs(s) ? new Date(sessionMs(s)).toISOString() : undefined}>
                                {relativeTime(s.updated_at || s.last_active || s.created_at)}
                              </time>
                            </button>
                            <div className="session-item-ops">
                              <button
                                type="button"
                                title="重命名"
                                aria-label="重命名"
                                className="session-glyph"
                                disabled={busy}
                                onClick={(e) => {
                                  e.stopPropagation();
                                  setPendingDelete(null);
                                  setEditingId(s.session_id);
                                  setEditTitle(s.title || displayTitle(s));
                                }}
                              >
                                <svg viewBox="0 0 24 24" aria-hidden>
                                  <path d="M4 17.5V20h2.5L18 8.5 15.5 6 4 17.5z" />
                                  <path d="M13.7 4.8l2.5 2.5" />
                                </svg>
                              </button>
                              {!locked ? (
                                <button
                                  type="button"
                                  title="删除"
                                  aria-label="删除"
                                  className="session-glyph danger"
                                  disabled={busy}
                                  onClick={(e) => {
                                    e.stopPropagation();
                                    setEditingId(null);
                                    setPendingDelete(s.session_id);
                                  }}
                                >
                                  <svg viewBox="0 0 24 24" aria-hidden>
                                    <path d="M5 7h14M10 7V5h4v2M8 7l.8 12h6.4L16 7" />
                                  </svg>
                                </button>
                              ) : null}
                            </div>
                          </>
                        )}
                      </motion.div>
                    );
                  })}
                </AnimatePresence>
              </section>
            ))
          : null}

        {loaded && !filtered.length ? (
          <div className="session-empty">
            {error ? "会话列表加载失败，请检查本机服务后刷新" : query ? "没有匹配的会话" : "还没有会话，点右上角「新会话」开始"}
          </div>
        ) : null}
      </div>
    </div>
  );
}
