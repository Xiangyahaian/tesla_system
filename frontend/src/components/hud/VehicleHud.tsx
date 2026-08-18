import { useCabinStore } from "@/store/cabinStore";
import { ClimateRing } from "@/components/hud/ClimateRing";

function Metric({
  label,
  value,
  sub,
  tone,
}: {
  label: string;
  value: string;
  sub?: string;
  tone?: "ok" | "warn" | "mute";
}) {
  return (
    <div className={`hud-metric tone-${tone || "mute"}`}>
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
  const wheel = vehicle?.seats?.steering_wheel_heat;
  const dyn = vehicle?.dynamics;

  const temp = zone?.temp != null ? `${zone.temp}°` : "--";
  const vol = media?.volume != null ? `${media.volume}` : "--";
  const track =
    music?.playing && (music.title || music.artist)
      ? `${music.artist ?? ""} ${music.title ?? ""}`.trim()
      : "未播放";
  const dest = nav?.navigating ? nav.destination || "导航中" : "无导航";
  const app = apps?.active || "无";
  const running = (apps?.running || []).slice(0, 3).join(" · ") || "—";

  return (
    <aside className="hud-panel" aria-label="车辆状态">
      <div className="hud-title">
        <span>Vehicle</span>
        <span className="hud-title-en">LIVE STATE</span>
      </div>
      <ClimateRing power={climate?.power} temp={zone?.temp} fan={zone?.fan} />
      <div className="hud-grid">
        <Metric
          label="Dynamics"
          value={`${dyn?.gear || "P"} · ${dyn?.speed_kmh != null ? Math.round(dyn.speed_kmh) : 0}`}
          sub="gear · km/h"
        />
        <Metric
          label="Climate"
          value={climate?.power ? temp : "OFF"}
          sub={climate?.power ? `Fan ${zone?.fan ?? "-"}` : "空调关闭"}
          tone={climate?.power ? "ok" : "mute"}
        />
        <Metric label="Volume" value={vol} sub={media?.muted ? "静音" : "媒体"} />
        <Metric label="Media" value={track} tone={music?.playing ? "ok" : "mute"} />
        <Metric
          label="Seat Heat"
          value={heat?.enable ? `L${heat.level ?? 1}` : "OFF"}
          sub="主驾"
        />
        <Metric label="Wheel Heat" value={wheel?.enable ? `L${wheel.level ?? 1}` : "OFF"} />
        <Metric
          label="Nav"
          value={String(dest)}
          sub={nav?.eta_min ? `ETA ${nav.eta_min}m` : undefined}
          tone={nav?.navigating ? "ok" : "mute"}
        />
        <Metric label="App" value={String(app)} sub={running} tone={apps?.active ? "ok" : "mute"} />
      </div>
    </aside>
  );
}
