import { NavLink } from "react-router-dom";
import { useCabinStore } from "@/store/cabinStore";

const LINKS = [
  { to: "/", label: "Drive", sub: "驾驶" },
  { to: "/apps", label: "Apps", sub: "应用" },
  { to: "/agent", label: "Agent", sub: "轨迹" },
  { to: "/settings", label: "Setup", sub: "设置" },
] as const;

export function SideRail() {
  const phase = useCabinStore((s) => s.phase);
  return (
    <nav className="side-rail" aria-label="座舱主导航">
      <div className="side-rail-brand">
        <div className="side-mark">C</div>
        <div className="side-brand-text">CABIN</div>
      </div>
      <ul className="side-rail-list">
        {LINKS.map((l) => (
          <li key={l.to}>
            <NavLink
              to={l.to}
              end={l.to === "/"}
              className={({ isActive }) => `side-link${isActive ? " active" : ""}`}
            >
              <span className="side-link-label">{l.label}</span>
              <span className="side-link-sub">{l.sub}</span>
            </NavLink>
          </li>
        ))}
      </ul>
      <div className={`side-phase phase-${phase}`}>
        <span className="side-phase-dot" />
        <span>{phase}</span>
      </div>
    </nav>
  );
}
