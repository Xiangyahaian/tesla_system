import { useCabinStore } from "@/store/cabinStore";

export function StatusStrip() {
  const vehicle = useCabinStore((s) => s.vehicle);
  const busy = useCabinStore((s) => s.busy);
  const confirm = useCabinStore((s) => s.confirm);
  const lastError = useCabinStore((s) => s.lastError);
  const speed = vehicle?.dynamics?.speed_kmh;
  const gear = vehicle?.dynamics?.gear || "P";
  const activeApp = vehicle?.apps?.active || "—";

  return (
    <div className="status-strip" role="status">
      <div className="status-cell">
        <span className="status-k">Gear</span>
        <span className="status-v">{gear}</span>
      </div>
      <div className="status-cell">
        <span className="status-k">Speed</span>
        <span className="status-v">{speed != null ? `${Math.round(speed)}` : "0"}
          <small>km/h</small>
        </span>
      </div>
      <div className="status-cell grow">
        <span className="status-k">Foreground</span>
        <span className="status-v truncate">{activeApp}</span>
      </div>
      <div className="status-cell">
        <span className="status-k">Link</span>
        <span className={`status-pill ${busy ? "busy" : confirm ? "warn" : "ok"}`}>
          {confirm ? "CONFIRM" : busy ? "BUSY" : "READY"}
        </span>
      </div>
      {lastError ? (
        <div className="status-cell error" title={lastError}>
          <span className="status-k">Error</span>
          <span className="status-v truncate">{lastError}</span>
        </div>
      ) : null}
    </div>
  );
}
