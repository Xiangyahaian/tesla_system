import { useEffect, useState } from "react";
import { fetchModelStatus, fetchTools } from "@/lib/api";
import { useCabinStore } from "@/store/cabinStore";
import { TopBar } from "@/components/layout/TopBar";

export function SettingsPage() {
  const model = useCabinStore((s) => s.model);
  const setModel = useCabinStore((s) => s.setModel);
  const ttsEnabled = useCabinStore((s) => s.ttsEnabled);
  const setTtsEnabled = useCabinStore((s) => s.setTtsEnabled);
  const sessionId = useCabinStore((s) => s.sessionId);
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
      <TopBar title="Setup" subtitle="模型 · 语音 · 工具目录" />
      <div className="settings-body">
        <section className="settings-card">
          <h3>会话</h3>
          <div className="settings-row">
            <span>Session ID</span>
            <code>{sessionId}</code>
          </div>
          <div className="settings-row">
            <span>LLM</span>
            <select
              className="model-select"
              value={model}
              onChange={(e) => setModel(e.target.value as "remote" | "local")}
            >
              <option value="remote">Qwen Flash（远程）</option>
              <option value="local">Local</option>
            </select>
          </div>
          <div className="settings-row">
            <span>TTS 播报</span>
            <button
              type="button"
              className={`toggle${ttsEnabled ? " on" : ""}`}
              onClick={() => setTtsEnabled(!ttsEnabled)}
              aria-pressed={ttsEnabled}
            >
              {ttsEnabled ? "开启" : "关闭"}
            </button>
          </div>
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
