import { useCabinStore } from "@/store/cabinStore";

function Metric({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="hud-metric">
      <div className="hud-label">{label}</div>
      <div className="hud-value">{value}</div>
      {sub ? <div className="hud-sub">{sub}</div> : null}
    </div>
  );
}

export function VehicleHud() {
  const vehicle = useCabinStore((s) => s.vehicle);
  const climate = vehicle?.climate;
  const zone = climate?.zones?.front_left;
  const media = vehicle?.media;
  const music = media?.music;
  const nav = vehicle?.navigation;
  const apps = vehicle?.apps;
  const heat = vehicle?.seats?.heat?.front_left;

  const temp = zone?.temp != null ? `${zone.temp}°` : "--";
  const vol = media?.volume != null ? `${media.volume}` : "--";
  const track =
    music?.playing && (music.title || music.artist)
      ? `${music.artist ?? ""} ${music.title ?? ""}`.trim()
      : "未播放";
  const dest = nav?.navigating ? nav.destination || "导航中" : "无导航";
  const app = apps?.active || "无";

  return (
    <aside className="hud-panel" aria-label="车辆状态">
      <div className="hud-title">
        <span>Vehicle</span>
        <span className="hud-title-en">LIVE STATE</span>
      </div>
      <div className="hud-grid">
        <Metric
          label="Climate"
          value={climate?.power ? temp : "OFF"}
          sub={climate?.power ? `Fan ${zone?.fan ?? "-"}` : "空调关闭"}
        />
        <Metric label="Volume" value={vol} sub={media?.muted ? "静音" : "媒体"} />
        <Metric label="Media" value={track} />
        <Metric
          label="Seat Heat"
          value={heat?.enable ? `L${heat.level ?? 1}` : "OFF"}
          sub="主驾"
        />
        <Metric label="Nav" value={String(dest)} sub={nav?.eta_min ? `ETA ${nav.eta_min}m` : undefined} />
        <Metric label="App" value={String(app)} />
      </div>
    </aside>
  );
}
