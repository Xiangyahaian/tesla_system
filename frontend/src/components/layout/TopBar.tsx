import { useCabinStore } from "@/store/cabinStore";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";

export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  const model = useCabinStore((s) => s.model);
  const setModel = useCabinStore((s) => s.setModel);
  const { doReset } = useCabinRuntime();

  return (
    <header className="cabin-top">
      <div className="brand-block">
        <div className="brand-mark">{title}</div>
        {subtitle ? <div className="brand-sub">{subtitle}</div> : null}
      </div>
      <div className="top-actions">
        <select
          className="model-select"
          value={model}
          onChange={(e) => setModel(e.target.value as "remote" | "local")}
          aria-label="模型"
        >
          <option value="remote">Qwen Flash</option>
          <option value="local">Local</option>
        </select>
        <a className="link-quiet" href="/legacy" target="_blank" rel="noreferrer">
          Legacy
        </a>
        <button type="button" className="btn ghost compact" onClick={() => void doReset()}>
          重置会话
        </button>
      </div>
    </header>
  );
}
