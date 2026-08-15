import { NavLink } from "react-router-dom";
import { motion } from "framer-motion";
import { useCabinStore } from "@/store/cabinStore";

const LINKS = [
  { to: "/", label: "驾驶助手" },
  { to: "/apps", label: "车机应用" },
  { to: "/agent", label: "执行轨迹" },
  { to: "/settings", label: "系统设置" },
] as const;

const PHASE_CN: Record<string, string> = {
  idle: "待命",
  listening: "聆听中",
  thinking: "理解中",
  acting: "执行中",
  speaking: "播报中",
};

/** Motionsites Securify–style pill chrome on the original cabin nav. */
export function TopNav() {
  const phase = useCabinStore((s) => s.phase);
  const vehicle = useCabinStore((s) => s.vehicle);
  const userNickname = useCabinStore((s) => s.userNickname);
  const clearUser = useCabinStore((s) => s.clearUser);
  const gear = vehicle?.dynamics?.gear || "P";
  const speed = vehicle?.dynamics?.speed_kmh;

  return (
    <motion.header
      className="top-nav top-nav-pill"
      initial={{ opacity: 0, y: -8 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
    >
      <div className="top-nav-brand pill-brand" title="小特智能座舱">
        <span className="pill-brand-glyph" aria-hidden />
        <span className="brand-cn">小特</span>
        <span className="brand-tag">cabin</span>
      </div>

      <nav className="top-nav-links pill-rail" aria-label="主导航">
        {LINKS.map((l) => (
          <NavLink
            key={l.to}
            to={l.to}
            end={l.to === "/"}
            className={({ isActive }) => `top-nav-link${isActive ? " active" : ""}`}
          >
            {l.label}
          </NavLink>
        ))}
      </nav>

      <div className="top-nav-status">
        <span className="nav-user" title="当前用户（独立记忆）">
          {userNickname || "未登录"}
        </span>
        <button type="button" className="nav-switch-user" onClick={() => clearUser()}>
          切换用户
        </button>
        <span className="nav-pill">{gear} 挡</span>
        <span className="nav-pill">{speed != null ? `${Math.round(speed)} km/h` : "0 km/h"}</span>
        <span className={`nav-phase phase-${phase}`}>{PHASE_CN[phase] || phase}</span>
      </div>
    </motion.header>
  );
}
