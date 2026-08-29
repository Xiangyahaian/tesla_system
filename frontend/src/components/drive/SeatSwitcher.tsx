import { SEAT_IDS, SEAT_LABELS } from "@/lib/seats";
import { useCabinStore } from "@/store/cabinStore";

/** 输入框上方：一排紧凑座位切换 */
export function SeatSwitcher() {
  const activeSeat = useCabinStore((s) => s.activeSeat);
  const setActiveSeat = useCabinStore((s) => s.setActiveSeat);

  return (
    <div className="seat-switcher" role="group" aria-label="切换座位">
      <span className="seat-switcher-label">座位</span>
      <div className="seat-switcher-row">
        {SEAT_IDS.map((id) => (
          <button
            key={id}
            type="button"
            className={`seat-switch-btn${activeSeat === id ? " on" : ""}`}
            aria-pressed={activeSeat === id}
            onClick={() => setActiveSeat(id)}
          >
            {SEAT_LABELS[id]}
          </button>
        ))}
      </div>
    </div>
  );
}
