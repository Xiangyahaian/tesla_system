import { useEffect, useState } from "react";
import { fetchModelStatus, fetchTools } from "@/lib/api";
import { useCabinStore } from "@/store/cabinStore";
import { TopBar } from "@/components/layout/TopBar";
import { SessionManagerPanel } from "@/components/session/SessionManagerPanel";
import { ManualPreviewButton } from "@/components/drive/ManualPreviewButton";

export function SettingsPage() {
  const model = useCabinStore((s) => s.model);
  const setModel = useCabinStore((s) => s.setModel);
  const ttsEnabled = useCabinStore((s) => s.ttsEnabled);
  const setTtsEnabled = useCabinStore((s) => s.setTtsEnabled);
  const ttsVolume = useCabinStore((s) => s.ttsVolume);
  const setTtsVolume = useCabinStore((s) => s.setTtsVolume);
  const sessionId = useCabinStore((s) => s.sessionId);
  const sessionTitle = useCabinStore((s) => s.sessionTitle);
  const userNickname = useCabinStore((s) => s.userNickname);
  const clearUser = useCabinStore((s) => s.clearUser);
  const [tools, setTools] = useState<
    { name: string; description: string; risk: string; domain: string }[]
  >([]);
  const [status, setStatus] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    void (async () => {
      try {
        const [t, m] = await Promise.all([fetchTools(), fetchModelStatus()]);
        setTools(t.tools || []);
        setStatus(m);
      } catch {
        /* ignore offline */
      }
    })();
  }, []);

  return (
    <div className="page-settings">
      <TopBar title="系统设置" subtitle="会话管理、模型、语音播报与工具注册表" />
      <div className="settings-body">
        <section className="settings-card wide">
          <h3>用户</h3>
          <div className="settings-row">
            <span>当前昵称</span>
            <code>{userNickname || "未登录"}</code>
          </div>
          <div className="settings-row">
            <span>独立记忆</span>
            <span>每个昵称对应 SQLite 用户记录 + 独立 session / MEMORY.md</span>
          </div>
          <div className="settings-row">
            <span>切换用户</span>
            <button type="button" className="deck-inline-btn" onClick={() => clearUser()}>
              退出并更换昵称
            </button>
          </div>
        </section>

        <section className="settings-card wide">
          <h3>会话管理（SQLite）</h3>
          <div className="settings-row">
            <span>当前会话</span>
            <code>
              {sessionTitle} · {sessionId}
            </code>
          </div>
          <SessionManagerPanel />
        </section>

        <section className="settings-card">
          <h3>通用</h3>
          <div className="settings-row">
            <span>用户手册</span>
            <ManualPreviewButton />
          </div>
          <div className="settings-row">
            <span>大模型</span>
            <select
              className="model-select"
              value={model}
              onChange={(e) => setModel(e.target.value as "remote" | "local")}
            >
              <option value="remote">云端模型</option>
              <option value="local">本地模型</option>
            </select>
          </div>
          <div className="settings-row">
            <span>开启声音</span>
            <button
              type="button"
              className={`toggle${ttsEnabled ? " on" : ""}`}
              onClick={() => {
                const next = !ttsEnabled;
                setTtsEnabled(next);
                if (next) {
                  void import("@/lib/speech").then((m) => m.unlockAudioPlayback());
                }
              }}
              aria-pressed={ttsEnabled}
            >
              {ttsEnabled ? "已开启" : "已关闭"}
            </button>
          </div>
          <div className={`settings-row settings-volume${ttsEnabled ? "" : " dimmed"}`}>
            <span>音量</span>
            <div className="volume-control">
              <input
                type="range"
                min={0}
                max={100}
                step={1}
                value={Math.round(ttsVolume * 100)}
                disabled={!ttsEnabled}
                onChange={(e) => setTtsVolume(Number(e.target.value) / 100)}
                aria-label="语音播报音量"
              />
              <em>{Math.round(ttsVolume * 100)}%</em>
            </div>
          </div>
          <p className="settings-hint">
            语音输入：千问 ASR（qwen3-asr-flash）· 语音输出：CosyVoice 女声 longanhuan（情感 Instruct + 流式）
          </p>
        </section>

        <section className="settings-card">
          <h3>模型状态</h3>
          <pre className="code-block soft">{JSON.stringify(status ?? { note: "暂无" }, null, 2)}</pre>
        </section>

        <section className="settings-card wide">
          <h3>工具注册表 · {tools.length}</h3>
          <div className="tools-table">
            {tools.map((t) => (
              <div key={t.name} className="tool-row">
                <div className="tool-name">{t.name}</div>
                <div className="tool-risk" data-risk={t.risk}>
                  {t.risk}
                </div>
                <div className="tool-domain">{t.domain}</div>
                <div className="tool-desc">{t.description}</div>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}
