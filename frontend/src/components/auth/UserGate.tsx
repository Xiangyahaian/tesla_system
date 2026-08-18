import { FormEvent, useEffect, useState } from "react";
import { fetchUsers, loginUser, type UserSummary } from "@/lib/api";
import { randomNickname } from "@/lib/randomNickname";
import { useCabinStore } from "@/store/cabinStore";

type Props = {
  onEntered: () => void;
};

/** 进页昵称门禁：同昵称绑定独立 session / Auto Memory */
export function UserGate({ onEntered }: Props) {
  const [nickname, setNickname] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [users, setUsers] = useState<UserSummary[]>([]);
  const setUser = useCabinStore((s) => s.setUser);

  useEffect(() => {
    void fetchUsers()
      .then((r) => setUsers(r.users || []))
      .catch(() => setUsers([]));
  }, []);

  const enter = async (name: string) => {
    const nick = name.trim();
    if (!nick) {
      setError("请填写昵称");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const res = await loginUser(nick);
      setUser(res.nickname, res.session_id);
      onEntered();
    } catch (e) {
      setError(e instanceof Error ? e.message : "进入失败");
    } finally {
      setBusy(false);
    }
  };

  const onSubmit = (e: FormEvent) => {
    e.preventDefault();
    void enter(nickname);
  };

  const fillRandom = () => {
    setNickname(randomNickname());
    setError(null);
  };

  return (
    <div className="user-gate" role="dialog" aria-label="用户登录">
      <div className="user-gate-card">
        <em>小特 · 智能座舱</em>
        <strong>先告诉我怎么称呼你</strong>
        <p>每个昵称拥有独立记忆与车况，换人登录互不影响。</p>
        <form onSubmit={onSubmit}>
          <label>
            <span>昵称</span>
            <div className="user-gate-nick-row">
              <input
                value={nickname}
                onChange={(e) => setNickname(e.target.value)}
                placeholder="例如：小明"
                maxLength={24}
                autoFocus
                disabled={busy}
              />
              <button
                type="button"
                className="user-gate-random"
                disabled={busy}
                onClick={fillRandom}
                title="随机生成昵称"
              >
                随机
              </button>
            </div>
          </label>
          {error ? <div className="user-gate-error">{error}</div> : null}
          <button type="submit" className="user-gate-go" disabled={busy || !nickname.trim()}>
            {busy ? "进入中…" : "进入座舱"}
          </button>
        </form>
        {users.length ? (
          <div className="user-gate-recent">
            <span>最近用户</span>
            <div className="user-gate-chips">
              {users.slice(0, 8).map((u) => (
                <button
                  key={u.session_id}
                  type="button"
                  disabled={busy}
                  onClick={() => void enter(u.nickname)}
                >
                  {u.nickname}
                </button>
              ))}
            </div>
          </div>
        ) : null}
      </div>
    </div>
  );
}
