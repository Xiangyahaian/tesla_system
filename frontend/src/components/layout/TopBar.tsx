import { useCabinStore } from "@/store/cabinStore";
import { ManualPreviewButton } from "@/components/drive/ManualPreviewButton";

export function TopBar({ title, subtitle }: { title: string; subtitle?: string }) {
  const model = useCabinStore((s) => s.model);
  const setModel = useCabinStore((s) => s.setModel);

  return (
    <header className="cabin-top">
      <div className="page-heading">
        <h1 className="page-title">{title}</h1>
        {subtitle ? <p className="page-subtitle">{subtitle}</p> : null}
      </div>
      <div className="top-actions">
        <ManualPreviewButton />
        <select
          className="model-select"
          value={model}
          onChange={(e) => setModel(e.target.value as "remote" | "local")}
          aria-label="模型"
        >
          <option value="remote">云端模型</option>
          <option value="local">本地模型</option>
        </select>
        <a className="link-quiet" href="/legacy" target="_blank" rel="noreferrer">
          旧版界面
        </a>
      </div>
    </header>
  );
}
