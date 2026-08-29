import { useCallback, useEffect, useMemo, useState } from "react";
import { deleteUser, fetchUsers, type UserSummary } from "@/lib/api";
import { formatSessionStamp } from "@/lib/sessionTitle";

export function UserAdminPanel() {
  const [users, setUsers] = useState<UserSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);

  const reload = useCallback(async () => {
    try {
      const data = await fetchUsers();
      setUsers(data.users || []);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载用户失败");
    } finally {
      setLoaded(true);
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    const rows = [...users].sort((a, b) => Number(b.last_login_at || 0) - Number(a.last_login_at || 0));
    if (!q) return rows;
    return rows.filter((u) => (u.nickname || "").toLowerCase().includes(q));
  }, [query, users]);

  const onDelete = async (u: UserSummary) => {
    const id = u.id || u.session_id;
    if (!id || u.is_admin) return;
    setBusy(true);
    try {
      const res = await deleteUser(id);
      setUsers(res.users || []);
      setPendingId(null);
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除用户失败");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="session-desk is-page user-admin">
      <div className="session-studio-head">
        <div>
          <h3>用户管理</h3>
          <p>仅管理员可见。可删除普通用户及其全部会话；管理员账号不可删除。</p>
        </div>
        <span className="session-count">{users.length} 人</span>
      </div>
      <div className="session-desk-toolbar">
        <label className="session-search">
          <svg viewBox="0 0 24 24" aria-hidden>
            <circle cx="11" cy="11" r="6.5" />
            <path d="M16.2 16.2L21 21" />
          </svg>
          <input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="搜索昵称" aria-label="搜索用户" />
        </label>
      </div>
      {error ? <div className="session-banner">{error}</div> : null}
      <div className="session-desk-list" role="list">
        {!loaded ? (
          <div className="session-skel" aria-hidden>
            {Array.from({ length: 4 }).map((_, i) => (
              <div key={i} className="session-skel-row" />
            ))}
          </div>
        ) : null}
        {loaded
          ? filtered.map((u) => {
              const id = u.id || u.session_id;
              const confirming = pendingId === id;
              const stamp = formatSessionStamp(u.last_login_at || u.created_at);
              return (
                <div key={id} className="session-item" role="listitem">
                  {confirming ? (
                    <div className="session-item-confirm">
                      <span>将删除「{u.nickname}」及其全部会话，不可恢复</span>
                      <div>
                        <button
                          type="button"
                          className="session-icon-btn danger"
                          disabled={busy}
                          onClick={() => void onDelete(u)}
                        >
                          删除
                        </button>
                        <button type="button" className="session-icon-btn" onClick={() => setPendingId(null)}>
                          取消
                        </button>
                      </div>
                    </div>
                  ) : (
                    <>
                      <div className="session-item-main user-admin-main">
                        <i className="session-dot" aria-hidden />
                        <span className="session-item-copy">
                          <strong>
                            {u.nickname}
                            {u.is_admin ? <em>管理员</em> : null}
                          </strong>
                          <span>
                            {u.session_count ?? 0} 条会话
                            {u.login_count ? ` · 登录 ${u.login_count} 次` : ""}
                            {stamp ? ` · 最近 ${stamp}` : ""}
                          </span>
                        </span>
                      </div>
                      {!u.is_admin ? (
                        <div className="session-item-ops">
                          <button
                            type="button"
                            className="session-glyph danger"
                            disabled={busy}
                            title="删除用户"
                            aria-label={`删除 ${u.nickname}`}
                            onClick={() => setPendingId(id)}
                          >
                            <svg viewBox="0 0 24 24" aria-hidden>
                              <path d="M5 7h14M10 7V5h4v2M8 7l.8 12h6.4L16 7" />
                            </svg>
                          </button>
                        </div>
                      ) : null}
                    </>
                  )}
                </div>
              );
            })
          : null}
        {loaded && !filtered.length ? (
          <div className="session-empty">{query ? "没有匹配的用户" : "还没有其他用户"}</div>
        ) : null}
      </div>
    </div>
  );
}
