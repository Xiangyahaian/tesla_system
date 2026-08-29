import { AnimatePresence, motion, useSpring, useTransform } from "framer-motion";
import { useEffect, useMemo, useRef, useState, type MouseEvent } from "react";
import { useCabinStore } from "@/store/cabinStore";
import { useVehicleControl } from "@/hooks/useVehicleControl";
import type { CabinStateSnapshot, SeatNode } from "@/lib/types";
import { SEAT_LABELS, type SeatId } from "@/lib/seats";
import { AmapNavPanel } from "@/components/maps/AmapNavPanel";
import { fetchWeather, type WeatherPayload } from "@/lib/api";

const WEATHER_POLL_MS = 10 * 60 * 1000;
const MODE_CN: Record<string, string> = {
  auto: "自动",
  eco: "节能",
  comfort: "舒适",
  heat: "制热",
  cool: "制冷",
  fastest: "最快",
  shortest: "最短",
  normal: "标准",
  wave: "波浪",
  sport: "运动",
  standard: "标准",
};

const WINDOW_KEY: Partial<Record<SeatId, string>> = {
  front_left: "front_left",
  front_right: "front_right",
  rear_left: "rear_left",
  rear_right: "rear_right",
};
const DOOR_KEY: Partial<Record<SeatId, string>> = {
  front_left: "front_left",
  front_right: "front_right",
  rear_left: "rear_left",
  rear_right: "rear_right",
};

type ControlOpts = { confirmHigh?: boolean; label?: string; live?: boolean };
type ControlFn = (tool: string, args?: Record<string, unknown>, opts?: ControlOpts) => void;

function cnMode(v?: string | null) {
  if (!v) return "—";
  return MODE_CN[v] || v;
}

function sliderRatio(el: HTMLElement | null, clientX: number) {
  if (!el) return 0;
  const rect = el.getBoundingClientRect();
  return Math.max(0, Math.min(1, (clientX - rect.left) / Math.max(rect.width, 1)));
}

function clamp01(n: number) {
  return Math.max(0, Math.min(1, n));
}

function useAnimatedNumber(value: number, precision = 0) {
  const spring = useSpring(value, { stiffness: 110, damping: 22, mass: 0.55 });
  const rounded = useTransform(spring, (v) =>
    precision > 0 ? v.toFixed(precision) : Math.round(v).toString(),
  );
  const [text, setText] = useState(
    precision > 0 ? value.toFixed(precision) : String(Math.round(value)),
  );
  useEffect(() => {
    spring.set(value);
  }, [spring, value]);
  useEffect(() => rounded.on("change", setText), [rounded]);
  return text;
}

function useGaugeProgress(value: number, max: number) {
  const pct = Math.max(0, Math.min(1, max <= 0 ? 0 : value / max));
  const spring = useSpring(pct, { stiffness: 88, damping: 20, mass: 0.7 });
  const [p, setP] = useState(pct);
  useEffect(() => {
    spring.set(pct);
  }, [spring, pct]);
  useEffect(() => spring.on("change", setP), [spring]);
  return p;
}

/** 精致环轨表：细轨 + 进度弧，去掉厚重表圈/螺丝/假指针 */
function PremiumGauge({
  progress,
  label,
  valueText,
  unit,
  tone = "speed",
  maxValue = 160,
}: {
  progress: number;
  label: string;
  valueText: string | number;
  unit: string;
  tone?: "speed" | "power";
  maxValue?: number;
  majorStep?: number;
  minorStep?: number;
}) {
  const size = 168;
  const cx = 84;
  const cy = 88;
  const startDeg = -210;
  const sweep = 240;
  const p = Math.max(0, Math.min(1, progress));
  const uid = `halo-${tone}`;
  const isPower = tone === "power";
  const r = 62;
  const tipDeg = startDeg + sweep * p;
  const tipRad = (tipDeg * Math.PI) / 180;
  const tipX = cx + Math.cos(tipRad) * r;
  const tipY = cy + Math.sin(tipRad) * r;

  const arc = (from: number, to: number) => {
    const a0 = ((startDeg + sweep * from) * Math.PI) / 180;
    const a1 = ((startDeg + sweep * to) * Math.PI) / 180;
    const x0 = cx + Math.cos(a0) * r;
    const y0 = cy + Math.sin(a0) * r;
    const x1 = cx + Math.cos(a1) * r;
    const y1 = cy + Math.sin(a1) * r;
    const large = sweep * (to - from) > 180 ? 1 : 0;
    return `M ${x0} ${y0} A ${r} ${r} 0 ${large} 1 ${x1} ${y1}`;
  };

  const majors = useMemo(() => {
    const out: { v: number; x: number; y: number }[] = [];
    const step = isPower ? 25 : 40;
    for (let v = 0; v <= maxValue + 0.01; v += step) {
      const t = Math.min(1, v / maxValue);
      const a = ((startDeg + sweep * t) * Math.PI) / 180;
      out.push({
        v: Math.round(v),
        x: cx + Math.cos(a) * (r - 14),
        y: cy + Math.sin(a) * (r - 14),
      });
    }
    return out;
  }, [isPower, maxValue]);

  return (
    <div className={`premium-gauge tone-${tone}`}>
      <div className="premium-gauge-frame">
        <svg viewBox={`0 0 ${size} ${size}`} className="premium-gauge-svg" aria-hidden>
          <defs>
            <linearGradient id={`${uid}-arc`} x1="0%" y1="0%" x2="100%" y2="0%">
              <stop offset="0%" stopColor={isPower ? "#5a9b78" : "#6b7280"} />
              <stop offset="100%" stopColor={isPower ? "#1f6b4a" : "#121316"} />
            </linearGradient>
          </defs>

          <path
            d={arc(0, 1)}
            fill="none"
            stroke="rgba(18,19,22,0.08)"
            strokeWidth="7"
            strokeLinecap="round"
          />
          <path
            d={arc(0, Math.max(0.001, p))}
            fill="none"
            stroke={`url(#${uid}-arc)`}
            strokeWidth="7"
            strokeLinecap="round"
          />
          <circle
            cx={tipX}
            cy={tipY}
            r="4.5"
            fill="#fff"
            stroke={isPower ? "#1f6b4a" : "#121316"}
            strokeWidth="2"
          />

          {majors.map((m) => (
            <text
              key={m.v}
              x={m.x}
              y={m.y}
              textAnchor="middle"
              dominantBaseline="middle"
              fill="rgba(18,19,22,0.38)"
              fontSize="8"
              fontFamily="Rajdhani, sans-serif"
              fontWeight="650"
            >
              {m.v}
            </text>
          ))}
        </svg>

        <div className="premium-gauge-lcd">
          <strong>{valueText}</strong>
          <span>{unit}</span>
        </div>
      </div>
      <div className="dial-caption">{label}</div>
    </div>
  );
}

function DriveCluster({
  speed,
  gear,
  parked,
  acc,
  cruiseTarget,
  battery,
  rangeKm,
  driveMode,
  outsideTemp,
  onControl,
}: {
  speed: number;
  gear: string;
  parked?: boolean;
  acc?: boolean;
  cruiseTarget?: number | null;
  battery: number;
  rangeKm?: number;
  driveMode?: string;
  outsideTemp?: string | number | null;
  onControl: (tool: string, args?: Record<string, unknown>, opts?: { confirmHigh?: boolean; label?: string }) => void;
}) {
  const speedText = useAnimatedNumber(speed);
  const battText = useAnimatedNumber(battery);
  const rangeText = useAnimatedNumber(rangeKm ?? 0);
  const speedProg = useGaugeProgress(speed, 160);
  const rawPower = acc ? Math.min(100, speed * 0.9) : Math.min(100, speed * 0.7);
  // 减速时示意回收（左侧 CHG），加速为动力（右侧 PWR）——对齐特斯拉功率条语义
  const braking = speed > 1.2 && !acc && rawPower < 25;
  const powerSigned = braking ? -Math.max(12, 40 - rawPower) : rawPower;
  const powerProg = useGaugeProgress(Math.abs(powerSigned), 100);
  const powerText = useAnimatedNumber(Math.abs(powerSigned), 0);
  const moving = speed > 1.2;
  const g = (gear || "P").toUpperCase();
  const battLow = battery < 20;

  const [now, setNow] = useState(() => new Date());
  useEffect(() => {
    const id = window.setInterval(() => setNow(new Date()), 15000);
    return () => window.clearInterval(id);
  }, []);
  const clock = `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`;
  const outsideLabel =
    outsideTemp != null && String(outsideTemp).trim() !== "" ? `${String(outsideTemp).replace(/°/g, "")}°` : "—";

  // 行程累计（本会话）
  const tripRef = useRef({ km: 0, last: performance.now(), energyWh: 0 });
  const [tripKm, setTripKm] = useState(0);
  const [avgKwh, setAvgKwh] = useState(0);
  useEffect(() => {
    let raf = 0;
    const loop = (t: number) => {
      const dt = Math.min(1, (t - tripRef.current.last) / 1000);
      tripRef.current.last = t;
      if (speed > 0.4) {
        const dkm = (speed / 3600) * dt;
        tripRef.current.km += dkm;
        // 粗估瞬时能耗：功率比例 × 速度相关
        const kw = Math.max(0, powerSigned) / 100 * (8 + speed * 0.12);
        tripRef.current.energyWh += kw * dt * (1000 / 3600);
        setTripKm(tripRef.current.km);
        setAvgKwh(
          tripRef.current.km > 0.05
            ? tripRef.current.energyWh / tripRef.current.km
            : 0,
        );
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [speed, powerSigned]);

  const status =
    parked || g === "P"
      ? "驻车"
      : acc || moving
        ? cruiseTarget != null
          ? `巡航 · 设定 ${Math.round(Number(cruiseTarget) || 0)}`
          : "巡航"
        : "就绪";

  const gears = ["P", "R", "N", "D"] as const;

  const powerBarPct = Math.max(4, Math.min(100, Math.abs(powerSigned)));

  return (
    <section
      className={`drive-cluster${moving ? " moving" : ""}${acc ? " tone-cruise" : ""}`}
      aria-label="行驶仪表"
    >
      <div className="cluster-halo" aria-hidden />

      <div className="cluster-toprow">
        <div className="cluster-gear">
          <div className="prnd" aria-label="挡位">
            {gears.map((x) => (
              <button
                key={x}
                type="button"
                className={`prnd-item${g === x ? " on" : ""}`}
                onClick={() => {
                  if (x === "P") {
                    onControl(
                      "driving.set_speed",
                      { speed_kmh: 0, gear: "P", parked: true },
                      { confirmHigh: true, label: "确认挂入 P 挡驻车？车辆将刹停。" },
                    );
                  } else if (x === "D") {
                    onControl(
                      "driving.set_speed",
                      { speed_kmh: Math.max(40, Number(cruiseTarget) || 40), gear: "D", parked: false },
                      {
                        confirmHigh: true,
                        label: "确认挂入 D 挡起步？车辆将开始跟驰加速。",
                      },
                    );
                  } else if (x === "R") {
                    onControl(
                      "driving.set_speed",
                      { speed_kmh: 0, gear: "R", parked: false },
                      { confirmHigh: true, label: "确认挂入 R 挡倒车？" },
                    );
                  } else {
                    onControl(
                      "driving.set_speed",
                      { speed_kmh: 0, gear: x, parked: false },
                      { confirmHigh: true, label: `确认挂入 ${x} 挡？` },
                    );
                  }
                }}
              >
                {x}
              </button>
            ))}
          </div>
          <span className="phase-chip">{status}</span>
          <button
            type="button"
            className={`telltale cluster-acc${acc ? " on" : ""}`}
            aria-pressed={!!acc}
            title={acc ? "关闭自适应巡航" : "开启自适应巡航"}
            onClick={() => {
              const enabling = !acc;
              onControl(
                "driving.set_adas",
                { feature: "acc", enable: enabling },
                {
                  confirmHigh: true,
                  label: enabling
                    ? "确认开启自适应巡航？车辆将挂入 D 挡，按设定车速跟驰（路况起伏，不会匀速钉死）。"
                    : "确认关闭自适应巡航？车辆将不再自动跟速。",
                },
              );
            }}
          >
            自动巡航
          </button>
        </div>
        <div className="cluster-meta-inline" aria-label="时刻与驾驶状态">
          <time dateTime={clock}>{clock}</time>
          <i aria-hidden />
          <span title="车外实况温度（与系统天气同源）">{outsideLabel}</span>
          <i aria-hidden />
          <button
            type="button"
            className="cluster-mode-btn"
            onClick={() => {
              const modes = ["comfort", "sport", "eco", "standard"];
              const cur = driveMode || "comfort";
              const next = modes[(modes.indexOf(cur) + 1) % modes.length];
              onControl("driving.set_mode", { mode: next }, { label: `驾驶模式 ${cnMode(next)}` });
            }}
          >
            {cnMode(driveMode)}
          </button>
        </div>
      </div>

      <div className="cluster-stage">
        <PremiumGauge
          progress={speedProg}
          label="车速"
          valueText={speedText}
          unit="km/h"
          tone="speed"
          maxValue={160}
        />

        <div className="cluster-hero">
          <div className="hero-eyebrow">{acc ? "ADAPTIVE CRUISE" : moving ? "DRIVING" : "READY"}</div>
          <div className="hero-speed">
            <strong>{speedText}</strong>
            <span>km/h</span>
          </div>
          {cruiseTarget != null && acc ? (
            <div className="hero-limit" title="巡航设定车速">
              SET <b>{Math.round(Number(cruiseTarget) || 0)}</b>
            </div>
          ) : (
            <div className="hero-accel">{acc ? "自适应巡航" : moving ? "手动行驶" : "静止待命"}</div>
          )}
        </div>

        <PremiumGauge
          progress={powerProg}
          label={braking ? "回收" : "动力"}
          valueText={powerText}
          unit="%"
          tone="power"
          maxValue={100}
        />
      </div>

      {/* 特斯拉风格功率条：左回收 / 右输出 */}
      <div className="power-rail" aria-label="功率计">
        <span className={`power-rail-lab${braking ? " on" : ""}`}>CHG</span>
        <div className="power-rail-track">
          <div className="power-rail-mid" />
          <motion.i
            className={`power-rail-fill${braking ? " chg" : " pwr"}`}
            initial={false}
            animate={
              braking
                ? { left: `${50 - powerBarPct / 2}%`, width: `${powerBarPct / 2}%`, right: "auto" }
                : { left: "50%", width: `${powerBarPct / 2}%` }
            }
            transition={{ type: "spring", stiffness: 120, damping: 20 }}
          />
        </div>
        <span className={`power-rail-lab${ !braking && moving ? " on" : ""}`}>PWR</span>
      </div>

      <div className="cluster-readout" aria-label="电量与行程">
        <div className={`readout-cell batt${battLow ? " low" : battery < 40 ? " mid" : ""}`} title="电量">
          <svg className="batt-svg" viewBox="0 0 48 24" aria-hidden>
            <defs>
              <linearGradient id="battFillGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="var(--batt-hi)" />
                <stop offset="55%" stopColor="var(--batt-mid)" />
                <stop offset="100%" stopColor="var(--batt-lo)" />
              </linearGradient>
              <linearGradient id="battShellGrad" x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor="#ffffff" />
                <stop offset="100%" stopColor="#eef0f4" />
              </linearGradient>
            </defs>
            {/* 外壳 */}
            <rect
              x="1.25"
              y="3.25"
              width="40.5"
              height="17.5"
              rx="4"
              fill="url(#battShellGrad)"
              stroke="currentColor"
              strokeWidth="1.75"
              className="batt-outline"
            />
            {/* 电极 */}
            <rect x="43" y="8.5" width="3.5" height="7" rx="1.2" className="batt-cap" />
            {/* 内槽 */}
            <rect x="4" y="6" width="35" height="12" rx="2.2" className="batt-well" />
            {/* 绿色电量 */}
            <motion.rect
              x="4.6"
              y="6.6"
              height="10.8"
              rx="1.8"
              className="batt-level"
              fill="url(#battFillGrad)"
              initial={false}
              animate={{ width: Math.max(2.2, (Math.min(100, Math.max(0, battery)) / 100) * 33.8) }}
              transition={{ type: "spring", stiffness: 100, damping: 18 }}
            />
            {/* 高光 */}
            <rect x="5.2" y="7.2" width="32.6" height="3.2" rx="1.2" className="batt-shine" />
          </svg>
          <div className="readout-cell-text">
            <div className="readout-val">
              <strong>{battText}</strong>
              <em>%</em>
            </div>
            <span className="readout-lab">电量</span>
          </div>
        </div>

        <div className="readout-cell" title="续航">
          <div className="readout-val">
            <strong>{rangeKm != null ? rangeText : "—"}</strong>
            <em>km</em>
          </div>
          <span className="readout-lab">续航</span>
        </div>

        <div className="readout-cell" title="本次行程">
          <div className="readout-val">
            <strong>{tripKm < 10 ? tripKm.toFixed(1) : Math.round(tripKm)}</strong>
            <em>km</em>
          </div>
          <span className="readout-lab">行程</span>
        </div>

        <div className="readout-cell" title="平均能耗">
          <div className="readout-val">
            <strong>{avgKwh > 0 ? (avgKwh / 10).toFixed(1) : "—"}</strong>
            <em>kWh/100</em>
          </div>
          <span className="readout-lab">能耗</span>
        </div>
      </div>
    </section>
  );
}

function formatClock(sec: number) {
  const s = Math.max(0, Math.floor(sec || 0));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

function MediaDeck({
  title,
  artist,
  album,
  playing,
  volume,
  muted,
  radioPlaying,
  radioLabel,
  radioBand,
  radioFreq,
  radioIndex = -1,
  positionSec = 0,
  durationSec = 0,
  currentIndex = -1,
  library = [],
  stations = [],
  onControl,
}: {
  title: string;
  artist: string;
  album?: string | null;
  playing: boolean;
  volume: number;
  muted: boolean;
  radioPlaying?: boolean;
  radioLabel?: string;
  radioBand?: string;
  radioFreq?: string;
  radioIndex?: number;
  positionSec?: number;
  durationSec?: number;
  currentIndex?: number;
  library?: {
    index: number;
    artist: string;
    title: string;
    album?: string | null;
    duration_sec?: number;
  }[];
  stations?: {
    index: number;
    band: string;
    frequency: string | number;
    station_name: string;
    category?: string | null;
  }[];
  onControl: ControlFn;
}) {
  const [dragging, setDragging] = useState(false);
  const draggingRef = useRef(false);
  const [dragRatio, setDragRatio] = useState(0);
  const trackRef = useRef<HTMLDivElement>(null);
  const seekHoldUntil = useRef(0);
  const volTrackRef = useRef<HTMLDivElement>(null);
  const [volDragging, setVolDragging] = useState(false);
  const volDraggingRef = useRef(false);
  const [localVol, setLocalVol] = useState(volume);
  const volHoldUntil = useRef(0);
  const [source, setSource] = useState<"music" | "radio">(radioPlaying ? "radio" : "music");
  const volText = useAnimatedNumber(localVol, 0);

  useEffect(() => {
    if (radioPlaying) setSource("radio");
    else if (playing) setSource("music");
  }, [radioPlaying, playing]);

  const isRadio = source === "radio";
  const live = isRadio ? !!radioPlaying : playing;
  const displayTitle = isRadio
    ? radioLabel || stations[Math.max(0, radioIndex)]?.station_name || "选择电台"
    : title;
  const displayArtist = isRadio
    ? [radioBand || "FM", radioFreq].filter(Boolean).join(" ") || "预设电台"
    : `${artist}${album ? ` · ${album}` : ""}`;
  const platterLetter = isRadio
    ? String(radioBand || "FM").slice(0, 1)
    : (artist || "T").slice(0, 1);

  const baseRef = useRef({ pos: positionSec, at: performance.now(), playing, title });
  const [smoothPos, setSmoothPos] = useState(positionSec);

  useEffect(() => {
    if (volDraggingRef.current) return;
    if (performance.now() < volHoldUntil.current) return;
    setLocalVol(volume);
  }, [volume]);

  useEffect(() => {
    baseRef.current.playing = playing;
    baseRef.current.title = title;
    if (draggingRef.current) return;
    if (performance.now() < seekHoldUntil.current) {
      if (Math.abs(positionSec - baseRef.current.pos) < 1.25) seekHoldUntil.current = 0;
      else return;
    }
    baseRef.current.pos = positionSec;
    baseRef.current.at = performance.now();
    setSmoothPos(positionSec);
  }, [positionSec, playing, title]);

  useEffect(() => {
    if (!playing || dragging || isRadio) return;
    let raf = 0;
    const loop = () => {
      const b = baseRef.current;
      const elapsed = (performance.now() - b.at) / 1000;
      const dur = durationSec > 0 ? durationSec : 0;
      const next = dur > 0 ? Math.min(dur, b.pos + elapsed) : b.pos + elapsed;
      setSmoothPos(next);
      raf = window.requestAnimationFrame(loop);
    };
    raf = window.requestAnimationFrame(loop);
    return () => window.cancelAnimationFrame(raf);
  }, [playing, dragging, durationSec, title, isRadio]);

  const displayPos = dragging ? dragRatio * Math.max(durationSec, 1) : smoothPos;
  const ratio = durationSec > 0 ? clamp01(displayPos / durationSec) : 0;
  const volPct = Math.max(0, Math.min(100, localVol));

  const seekFromClientX = (clientX: number) => {
    if (durationSec <= 0) return;
    const r = sliderRatio(trackRef.current, clientX);
    setDragRatio(r);
    return r;
  };

  const commitSeek = (r: number) => {
    if (durationSec <= 0) return;
    const pos = Math.round(r * durationSec * 10) / 10;
    seekHoldUntil.current = performance.now() + 480;
    setSmoothPos(pos);
    baseRef.current = { pos, at: performance.now(), playing, title };
    onControl("media.seek_music", { position_sec: pos }, { label: "调整播放进度", live: true });
  };

  const applyVolume = (next: number, live = true) => {
    const vol = Math.max(0, Math.min(100, next));
    volHoldUntil.current = performance.now() + 420;
    setLocalVol(vol);
    onControl("media.set_volume", { volume: Math.round(vol), muted: false }, { live });
  };

  const onPlayPause = () => {
    if (isRadio) {
      onControl(
        radioPlaying ? "media.control_radio" : "media.play_radio",
        radioPlaying
          ? { action: "stop" }
          : radioLabel
            ? { station_name: radioLabel }
            : {},
        { label: radioPlaying ? "停止电台" : "播放电台" },
      );
      return;
    }
    onControl("media.control_music", { action: playing ? "pause" : "play" });
  };

  const onPrev = () => {
    if (isRadio) {
      onControl("media.switch_radio", { direction: "prev" }, { label: "上一个电台" });
      return;
    }
    onControl("media.switch_music", { direction: "prev" });
  };

  const onNext = () => {
    if (isRadio) {
      onControl("media.switch_radio", { direction: "next" }, { label: "下一个电台" });
      return;
    }
    onControl("media.switch_music", { direction: "next" });
  };

  const eqHeights = useMemo(() => [0.35, 0.7, 0.45, 0.9, 0.55, 0.8, 0.4, 0.65], []);

  return (
    <article
      className={`deck-music${live ? " live" : ""}${isRadio ? " radio" : ""}`}
    >
      <div className="media-source-tabs" role="tablist" aria-label="媒体来源">
        <button
          type="button"
          role="tab"
          aria-selected={!isRadio}
          className={!isRadio ? "on" : undefined}
          onClick={() => setSource("music")}
        >
          音乐
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={isRadio}
          className={isRadio ? "on" : undefined}
          onClick={() => setSource("radio")}
        >
          电台
        </button>
      </div>

      <div className="media-stage">
        <button
          type="button"
          className="media-platter"
          aria-label={live ? (isRadio ? "停止" : "暂停") : "播放"}
          onClick={onPlayPause}
        >
          <motion.div
            className="media-platter-spin"
            animate={{ rotate: live ? 360 : 0 }}
            transition={
              live
                ? { duration: isRadio ? 12 : 7.5, repeat: Infinity, ease: "linear" }
                : { duration: 0.6, ease: [0.22, 1, 0.36, 1] }
            }
          >
            <i className="media-groove" />
            <i className="media-groove g2" />
            <span className="media-label">
              <em>{platterLetter}</em>
            </span>
          </motion.div>
          <span className={`media-play-glyph${live ? " pause" : ""}`} aria-hidden />
          <motion.i
            className="media-platter-ring"
            animate={live ? { scale: [1, 1.06, 1], opacity: [0.35, 0.08, 0.35] } : { scale: 1, opacity: 0 }}
            transition={live ? { duration: 2.4, repeat: Infinity, ease: "easeInOut" } : {}}
          />
        </button>

        <div className="media-copy">
          <div className="media-kicker">
            <span className={`media-live-dot${live ? " on" : ""}`} />
            <em>
              {isRadio
                ? radioPlaying
                  ? "正在收听"
                  : muted
                    ? "已静音"
                    : "电台"
                : playing
                  ? "正在播放"
                  : muted
                    ? "已静音"
                    : "音乐"}
            </em>
            <div className={`media-eq${live ? " on" : ""}`} aria-hidden>
              {eqHeights.map((h, i) => (
                <motion.i
                  key={i}
                  animate={
                    live
                      ? { scaleY: [h * 0.45, h, h * 0.55, h * 0.9, h * 0.4] }
                      : { scaleY: 0.22 }
                  }
                  transition={
                    live
                      ? { duration: 0.85 + i * 0.07, repeat: Infinity, ease: "easeInOut" }
                      : { duration: 0.3 }
                  }
                />
              ))}
            </div>
          </div>

          <motion.strong
            key={`${source}-${displayTitle}`}
            className="media-title"
            initial={{ opacity: 0, y: 6 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            {displayTitle}
          </motion.strong>
          <motion.span
            key={`${source}-${displayArtist}`}
            className="media-artist"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            transition={{ duration: 0.35, delay: 0.04 }}
          >
            {displayArtist}
          </motion.span>

          {!isRadio ? (
            <div className="media-progress-block">
              <div
                ref={trackRef}
                className={`media-progress${dragging ? " dragging" : ""}${durationSec > 0 ? " interactive" : ""}`}
                role="slider"
                tabIndex={0}
                aria-label="播放进度"
                aria-valuemin={0}
                aria-valuemax={Math.round(durationSec || 0)}
                aria-valuenow={Math.round(displayPos)}
                aria-valuetext={`${formatClock(displayPos)} / ${formatClock(durationSec)}`}
                onPointerDown={(e) => {
                  if (durationSec <= 0) return;
                  e.currentTarget.setPointerCapture(e.pointerId);
                  draggingRef.current = true;
                  setDragging(true);
                  seekFromClientX(e.clientX);
                }}
                onPointerMove={(e) => {
                  if (!draggingRef.current) return;
                  seekFromClientX(e.clientX);
                }}
                onPointerUp={(e) => {
                  if (!draggingRef.current) return;
                  const r = seekFromClientX(e.clientX) ?? dragRatio;
                  draggingRef.current = false;
                  setDragging(false);
                  commitSeek(r);
                }}
                onPointerCancel={() => {
                  draggingRef.current = false;
                  setDragging(false);
                }}
                onKeyDown={(e) => {
                  if (durationSec <= 0) return;
                  if (e.key === "ArrowRight") {
                    e.preventDefault();
                    onControl("media.seek_music", { delta_sec: 5 }, { label: "快进 5 秒" });
                  } else if (e.key === "ArrowLeft") {
                    e.preventDefault();
                    onControl("media.seek_music", { delta_sec: -5 }, { label: "快退 5 秒" });
                  }
                }}
              >
                <i style={{ width: `${ratio * 100}%` }} />
                <em className="media-progress-thumb" style={{ left: `${ratio * 100}%` }} />
              </div>
              <div className="media-time-row">
                <span>{formatClock(displayPos)}</span>
                <span>{durationSec > 0 ? formatClock(durationSec) : "--:--"}</span>
              </div>
            </div>
          ) : (
            <div className="media-radio-live" aria-hidden>
              <span className={radioPlaying ? "on" : undefined}>{radioPlaying ? "LIVE" : "待机"}</span>
              <i />
            </div>
          )}

          <div className="media-transport">
            <button
              type="button"
              className="media-icon-btn"
              aria-label={isRadio ? "上一个电台" : "上一首"}
              onClick={onPrev}
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                <path fill="currentColor" d="M6 6h2v12H6V6zm3.5 6 8.5 6V6l-8.5 6z" />
              </svg>
            </button>
            <button
              type="button"
              className={`media-icon-btn primary${live ? " playing" : ""}`}
              aria-label={live ? (isRadio ? "停止" : "暂停") : "播放"}
              onClick={onPlayPause}
            >
              {live ? (
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                  <path fill="currentColor" d="M7 6h3v12H7V6zm7 0h3v12h-3V6z" />
                </svg>
              ) : (
                <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden>
                  <path fill="currentColor" d="M8 5v14l11-7L8 5z" />
                </svg>
              )}
            </button>
            <button
              type="button"
              className="media-icon-btn"
              aria-label={isRadio ? "下一个电台" : "下一首"}
              onClick={onNext}
            >
              <svg viewBox="0 0 24 24" width="16" height="16" aria-hidden>
                <path fill="currentColor" d="M16 6h2v12h-2V6zM6 18l8.5-6L6 6v12z" />
              </svg>
            </button>
          </div>

          <div className="media-volume">
            <button
              type="button"
              className="media-vol-btn"
              aria-label="音量减"
              onClick={() => applyVolume(localVol - 5)}
            >
              −
            </button>
            <div
              ref={volTrackRef}
              className={`media-vol-track${volDragging ? " dragging" : ""}`}
              role="slider"
              tabIndex={0}
              aria-label="音量"
              aria-valuemin={0}
              aria-valuemax={100}
              aria-valuenow={Math.round(volPct)}
              onPointerDown={(e) => {
                e.currentTarget.setPointerCapture(e.pointerId);
                volDraggingRef.current = true;
                setVolDragging(true);
                applyVolume(sliderRatio(volTrackRef.current, e.clientX) * 100);
              }}
              onPointerMove={(e) => {
                if (!volDraggingRef.current) return;
                applyVolume(sliderRatio(volTrackRef.current, e.clientX) * 100);
              }}
              onPointerUp={() => {
                volDraggingRef.current = false;
                setVolDragging(false);
              }}
              onPointerCancel={() => {
                volDraggingRef.current = false;
                setVolDragging(false);
              }}
              onKeyDown={(e) => {
                if (e.key === "ArrowRight" || e.key === "ArrowUp") {
                  e.preventDefault();
                  applyVolume(localVol + 5);
                } else if (e.key === "ArrowLeft" || e.key === "ArrowDown") {
                  e.preventDefault();
                  applyVolume(localVol - 5);
                }
              }}
            >
              <i style={{ width: `${volPct}%` }} />
              <em className="media-vol-thumb" style={{ left: `${volPct}%` }} />
            </div>
            <button
              type="button"
              className="media-vol-btn"
              aria-label="音量加"
              onClick={() => applyVolume(localVol + 5)}
            >
              +
            </button>
            <span className="media-vol-num">{muted && !volDragging ? "静音" : volText}</span>
          </div>
        </div>
      </div>

      <div className="media-playlist" aria-label={isRadio ? "电台列表" : "歌单"}>
        <div className="media-playlist-head">
          <strong>{isRadio ? "电台" : "歌单"}</strong>
          <span>
            {isRadio
              ? stations.length
                ? `${stations.length} 个台`
                : "电台加载中"
              : library.length
                ? `${library.length} 首`
                : "曲库加载中"}
          </span>
        </div>
        <ul className="media-playlist-list">
          {isRadio
            ? stations.map((st) => {
                const active = st.index === radioIndex;
                const activePlaying = active && !!radioPlaying;
                return (
                  <li key={`${st.index}-${st.station_name}`}>
                    <button
                      type="button"
                      className={`media-track-row${active ? " active" : ""}${activePlaying ? " playing" : ""}`}
                      onClick={() =>
                        onControl(
                          "media.play_radio",
                          { station_name: st.station_name },
                          { label: `收听 ${st.station_name}` },
                        )
                      }
                    >
                      <span className="media-track-idx" aria-hidden>
                        {activePlaying ? (
                          <i className="media-track-eq">
                            <b />
                            <b />
                            <b />
                          </i>
                        ) : (
                          String(st.index + 1).padStart(2, "0")
                        )}
                      </span>
                      <span className="media-track-meta">
                        <em>{st.station_name}</em>
                        <small>
                          {st.band}
                          {st.frequency}
                          {st.category ? ` · ${st.category}` : ""}
                        </small>
                      </span>
                      <span className="media-track-dur">{st.band}</span>
                    </button>
                  </li>
                );
              })
            : library.map((song) => {
                const active = song.index === currentIndex;
                return (
                  <li key={`${song.index}-${song.title}`}>
                    <button
                      type="button"
                      className={`media-track-row${active ? " active" : ""}${active && playing ? " playing" : ""}`}
                      onClick={() =>
                        onControl(
                          "media.play_music",
                          { artist: song.artist, title: song.title },
                          { label: `播放 ${song.title}` },
                        )
                      }
                    >
                      <span className="media-track-idx" aria-hidden>
                        {active && playing ? (
                          <i className="media-track-eq">
                            <b />
                            <b />
                            <b />
                          </i>
                        ) : (
                          String(song.index + 1).padStart(2, "0")
                        )}
                      </span>
                      <span className="media-track-meta">
                        <em>{song.title}</em>
                        <small>
                          {song.artist}
                          {song.album ? ` · ${song.album}` : ""}
                        </small>
                      </span>
                      <span className="media-track-dur">
                        {song.duration_sec && song.duration_sec > 0
                          ? formatClock(song.duration_sec)
                          : "--:--"}
                      </span>
                    </button>
                  </li>
                );
              })}
        </ul>
      </div>
    </article>
  );
}

function CabinAmbientStrip({
  vehicle,
  onControl,
}: {
  vehicle: CabinStateSnapshot | null;
  onControl: (tool: string, args?: Record<string, unknown>, opts?: { confirmHigh?: boolean; label?: string }) => void;
}) {
  const cabin = vehicle?.cabin;
  const lights = cabin?.lights;
  const displays = cabin?.displays;
  const dyn = vehicle?.dynamics;
  const sunroof = cabin?.windows?.sunroof?.percent ?? 0;

  const cycleBrightness = (target: "center_screen" | "instrument" | "hud", label: string) => {
    const cur = displays?.[target]?.brightness ?? 50;
    const next = cur >= 100 ? 20 : Math.min(100, cur + 20);
    onControl("cabin.set_display_brightness", { target, brightness: next }, { label: `调节${label}` });
  };

  return (
    <div className="cabin-ambient" aria-label="灯光显示与车身">
      <button
        type="button"
        className={`ambient-cell${lights?.ambient?.enable ? " on" : ""}`}
        onClick={() =>
          onControl("cabin.set_light", {
            target: "ambient",
            enable: !lights?.ambient?.enable,
            brightness: lights?.ambient?.enable ? 0 : 50,
          })
        }
      >
        <em>氛围灯</em>
        <strong>{lights?.ambient?.enable ? `${lights.ambient.brightness ?? 0}%` : "关"}</strong>
      </button>
      <button
        type="button"
        className={`ambient-cell${lights?.dome?.enable ? " on" : ""}`}
        onClick={() =>
          onControl("cabin.set_light", {
            target: "dome",
            enable: !lights?.dome?.enable,
            brightness: lights?.dome?.enable ? 0 : 50,
          })
        }
      >
        <em>顶灯</em>
        <strong>{lights?.dome?.enable ? `${lights.dome.brightness ?? 0}%` : "关"}</strong>
      </button>
      <button type="button" className="ambient-cell on soft" onClick={() => cycleBrightness("center_screen", "中控亮度")}>
        <em>中控</em>
        <strong>{displays?.center_screen?.brightness ?? 50}%</strong>
      </button>
      <button type="button" className="ambient-cell on soft" onClick={() => cycleBrightness("instrument", "仪表亮度")}>
        <em>仪表</em>
        <strong>{displays?.instrument?.brightness ?? 50}%</strong>
      </button>
      <button type="button" className="ambient-cell on soft" onClick={() => cycleBrightness("hud", "HUD亮度")}>
        <em>HUD</em>
        <strong>{displays?.hud?.brightness ?? 50}%</strong>
      </button>
      <button
        type="button"
        className={`ambient-cell${dyn?.child_lock ? " on" : ""}`}
        onClick={() =>
          onControl("driving.set_child_lock", { enable: !dyn?.child_lock }, {
            label: `${dyn?.child_lock ? "关闭" : "开启"}儿童锁`,
          })
        }
      >
        <em>儿童锁</em>
        <strong>{dyn?.child_lock ? "开" : "关"}</strong>
      </button>
      <button
        type="button"
        className={`ambient-cell${sunroof > 0 ? " on" : ""}`}
        onClick={() =>
          onControl("cabin.set_windows", { percent: sunroof > 0 ? 0 : 100, positions: ["sunroof"] }, {
            label: sunroof > 0 ? "关闭天窗" : "打开天窗",
          })
        }
      >
        <em>天窗</em>
        <strong>{sunroof}%</strong>
      </button>
      <button
        type="button"
        className={`ambient-cell${cabin?.trunk?.open ? " on" : ""}`}
        onClick={() =>
          onControl(
            "cabin.set_trunk",
            { open: !cabin?.trunk?.open },
            { confirmHigh: true, label: cabin?.trunk?.open ? "关闭后备箱？" : "打开后备箱？" },
          )
        }
      >
        <em>后备箱</em>
        <strong>{cabin?.trunk?.open ? "开" : "关"}</strong>
      </button>
      <button
        type="button"
        className={`ambient-cell${cabin?.frunk?.open ? " on" : ""}`}
        onClick={() =>
          onControl(
            "cabin.set_frunk",
            { open: !cabin?.frunk?.open },
            { confirmHigh: true, label: cabin?.frunk?.open ? "关闭前备箱？" : "打开前备箱？" },
          )
        }
      >
        <em>前备箱</em>
        <strong>{cabin?.frunk?.open ? "开" : "关"}</strong>
      </button>
      <button
        type="button"
        className={`ambient-cell${cabin?.charge_port?.open ? " on" : ""}`}
        onClick={() =>
          onControl("cabin.set_charge_port", { open: !cabin?.charge_port?.open }, {
            label: `${cabin?.charge_port?.open ? "关闭" : "打开"}充电口`,
          })
        }
      >
        <em>充电口</em>
        <strong>{cabin?.charge_port?.open ? "开" : "关"}</strong>
      </button>
    </div>
  );
}

function SharedDeck({
  vehicle,
  onControl,
  busy,
  weather,
}: {
  vehicle: CabinStateSnapshot | null;
  onControl: ControlFn;
  busy?: boolean;
  weather?: WeatherPayload | null;
}) {
  const media = vehicle?.media;
  const nav = vehicle?.navigation;
  const apps = vehicle?.apps;
  const music = media?.music;
  const radio = media?.radio;
  const playing = !!music?.playing;
  const title = music?.title || (playing ? "正在播放" : "未在播放");
  const artist = music?.artist || "点击播放";
  const [mapOpen, setMapOpen] = useState(true);
  const [inboxOpen, setInboxOpen] = useState(false);
  const mapEpoch = useCabinStore((s) => s.mapEpoch);

  useEffect(() => {
    setMapOpen(true);
  }, [mapEpoch]);

  const remainKm =
    nav?.remaining_m != null && nav.navigating ? `${(nav.remaining_m / 1000).toFixed(1)} km` : null;
  const livePlace = nav?.position?.name || "当前位置";
  const conn = vehicle?.connectivity;
  const notes = vehicle?.notifications;
  const wifiOn = !!conn?.wifi?.on;
  const wifiSsid = conn?.wifi?.ssid || "手机热点";
  const messages = notes?.messages || [];
  const unreadList = messages.filter((m) => !m.read);
  const unread = unreadList.length;
  const missed = Number(notes?.missed_calls || 0);
  const phoneStatus = notes?.phone_status || "空闲";
  const weatherLine = weather?.ok
    ? [weather.place, weather.summary].filter(Boolean).join(" · ")
    : weather?.summary || "天气加载中…";
  const weatherTitle = weather?.ok
    ? [weather.weather, weather.temperature ? `${weather.temperature}°` : "", weather.wind, weather.humidity ? `湿度${weather.humidity}%` : ""]
        .filter(Boolean)
        .join(" · ")
    : weather?.error || "正在获取当前位置天气";

  const openInbox = (e?: MouseEvent) => {
    e?.stopPropagation();
    setInboxOpen(true);
  };

  const markOneRead = (id?: string) => {
    if (!id) return;
    onControl("notifications.mark_read", { ids: [id] }, { label: "标记已读" });
  };

  return (
    <section className="shared-deck" aria-label="共享状态">
      <div className="deck-bento">
        <MediaDeck
          title={title}
          artist={artist}
          album={music?.album}
          playing={playing}
          volume={media?.volume ?? 0}
          muted={!!media?.muted}
          radioPlaying={!!radio?.playing}
          radioLabel={String(radio?.station_name || "")}
          radioBand={String(radio?.band || "FM")}
          radioFreq={radio?.frequency != null ? String(radio.frequency) : ""}
          radioIndex={Number(radio?.index ?? -1)}
          positionSec={Number(music?.position_sec ?? 0)}
          durationSec={Number(music?.duration_sec ?? 0)}
          currentIndex={Number(music?.index ?? -1)}
          library={media?.library || []}
          stations={media?.radio_stations || []}
          onControl={onControl}
        />

        <article
          className={`deck-nav${nav?.navigating ? " live" : ""}${mapOpen ? " expanded" : ""}`}
          role="button"
          tabIndex={0}
          onClick={() => setMapOpen(true)}
          onKeyDown={(e) => {
            if (e.key === "Enter" || e.key === " ") {
              e.preventDefault();
              setMapOpen(true);
            }
          }}
        >
          <header className="deck-nav-head">
            <div className="deck-nav-kicker">
              <em>导航</em>
              <b className={`deck-nav-state${nav?.navigating ? " on" : ""}${nav?.arrived && !nav?.navigating ? " arrived" : ""}`}>
                {nav?.navigating
                  ? "导航中"
                  : nav?.arrived
                    ? "已到达"
                    : nav?.mode === "cruising"
                      ? "巡航"
                      : "待命"}
              </b>
            </div>
            <div className="deck-nav-actions" onClick={(e) => e.stopPropagation()}>
              <button type="button" className="deck-inline-btn" onClick={() => setMapOpen((v) => !v)}>
                {mapOpen ? "收起" : "地图"}
              </button>
              {nav?.navigating ? (
                <button type="button" className="deck-inline-btn danger" onClick={() => onControl("navigation.stop", {})}>
                  结束
                </button>
              ) : null}
            </div>
          </header>

          <div className="deck-nav-main">
            <strong title={nav?.navigating ? nav.destination || livePlace : livePlace}>
              {nav?.navigating ? nav.destination || "目的地" : "未设定导航"}
            </strong>
            <span>
              {nav?.navigating
                ? `目前所在 · ${livePlace}`
                : `当前位置 · ${livePlace}`}
            </span>
          </div>

          <div className="deck-nav-metrics" aria-label="导航摘要">
            {nav?.navigating ? (
              <>
                <div>
                  <em>剩余</em>
                  <strong>{remainKm || "—"}</strong>
                </div>
                <div>
                  <em>预计</em>
                  <strong>{nav.eta_min != null ? `${nav.eta_min} 分` : "—"}</strong>
                </div>
                <div>
                  <em>路况</em>
                  <strong>{nav.traffic || "畅通"}</strong>
                </div>
              </>
            ) : (
              <>
                <div>
                  <em>起点</em>
                  <strong>我的位置</strong>
                </div>
                <div>
                  <em>终点</em>
                  <strong>未设定</strong>
                </div>
                <div>
                  <em>路况</em>
                  <strong>{nav?.traffic || "畅通"}</strong>
                </div>
              </>
            )}
          </div>

          <div className={`deck-nav-progress${nav?.navigating ? " on" : ""}`} aria-hidden>
            <i
              style={{
                width: nav?.navigating
                  ? `${Math.max(
                      6,
                      Math.min(
                        100,
                        ((Number(nav.progress_m) || 0) / Math.max(1, Number(nav.distance_m) || 1)) * 100,
                      ),
                    )}%`
                  : "18%",
              }}
            />
          </div>
        </article>

        <article className="deck-place">
          <em>系统</em>
          <strong>{apps?.active || "无前台应用"}</strong>
          <div className="deck-sys-rows" aria-label="连接与通知">
            <button
              type="button"
              className="deck-sys-row"
              onClick={() =>
                onControl(
                  "connectivity.set_wifi",
                  { enable: !wifiOn },
                  { label: wifiOn ? "关闭 Wi‑Fi" : "打开 Wi‑Fi" },
                )
              }
            >
              <b>Wi‑Fi</b>
              <i>{wifiOn ? `已连接 · ${wifiSsid}` : "未连接"}</i>
            </button>
            <div className="deck-sys-row static" title={weatherTitle}>
              <b>天气</b>
              <i>{weatherLine}</i>
            </div>
            <button type="button" className="deck-sys-row" onClick={openInbox}>
              <b>消息</b>
              <i>
                {unread > 0 ? `未读 ${unread}` : "无未读"}
              </i>
            </button>
            <div className="deck-sys-row static">
              <b>电话</b>
              <i>{missed > 0 ? `未接 ${missed}` : phoneStatus}</i>
            </div>
          </div>
        </article>
      </div>

      {inboxOpen ? (
        <div className="msg-inbox-mask" role="presentation" onClick={() => setInboxOpen(false)}>
          <div
            className="msg-inbox"
            role="dialog"
            aria-label="消息"
            onClick={(e) => e.stopPropagation()}
          >
            <header>
              <strong>消息</strong>
              <button type="button" className="deck-inline-btn" onClick={() => setInboxOpen(false)}>
                关闭
              </button>
            </header>
            <p className="msg-inbox-hint">
              点击一条即标记已读。对话里问消息时，口头说「确认」才会读；详细内容在依据与过程。
            </p>
            <ul>
              {messages.length === 0 ? (
                <li className="empty">暂无消息</li>
              ) : (
                [...messages].reverse().map((m) => (
                  <li key={m.id || `${m.app}-${m.ts}`}>
                    <button
                      type="button"
                      className={m.read ? "read" : "unread"}
                      onClick={() => markOneRead(m.id)}
                    >
                      <em>
                        {m.app} · {m.from}
                        {!m.read ? " · 未读" : " · 已读"}
                      </em>
                      <span>{m.text}</span>
                    </button>
                  </li>
                ))
              )}
            </ul>
            {unread > 0 ? (
              <footer>
                <button
                  type="button"
                  className="deck-inline-btn"
                  onClick={() =>
                    onControl("notifications.mark_read", { all_unread: true }, { label: "全部已读" })
                  }
                >
                  全部已读
                </button>
              </footer>
            ) : null}
          </div>
        </div>
      ) : null}

      <AmapNavPanel
        open={mapOpen}
        onClose={() => setMapOpen(false)}
        onControl={onControl}
        busy={busy}
      />

      <CabinAmbientStrip vehicle={vehicle} onControl={onControl} />
    </section>
  );
}

function cycleSeatFeature(
  onControl: (tool: string, args?: Record<string, unknown>, opts?: { confirmHigh?: boolean; label?: string }) => void,
  feature: "heat" | "ventilation" | "massage",
  zones: string[],
  node?: SeatNode,
) {
  if (!node?.enable) {
    onControl("seat.set", { feature, enable: true, level: 2, positions: zones });
    return;
  }
  const next = (node.level ?? 1) + 1;
  if (next > 3) {
    onControl("seat.set", { feature, enable: false, level: 0, positions: zones });
  } else {
    onControl("seat.set", { feature, enable: true, level: next, positions: zones });
  }
}

function SeatFeatLevel({ enable, level }: { enable?: boolean; level?: number }) {
  const lv = enable ? Math.max(0, Math.min(3, level ?? 0)) : 0;
  return (
    <span className="seat-level" aria-hidden>
      {Array.from({ length: 3 }).map((_, i) => (
        <i key={i} className={i < lv ? "on" : ""} />
      ))}
    </span>
  );
}

function SeatCabinStudio({
  vehicle,
  selected,
  onSelect,
  onControl,
}: {
  vehicle: CabinStateSnapshot | null;
  selected: SeatId;
  onSelect: (id: SeatId) => void;
  onControl: ControlFn;
}) {
  const climate = vehicle?.climate;
  const seats = vehicle?.seats;
  const cabin = vehicle?.cabin;
  const zone = climate?.zones?.[selected];
  const on = !!zone?.on;
  const temp = zone?.temp ?? 22;
  const tempText = useAnimatedNumber(temp, 0);
  const fan = zone?.fan ?? 0;
  const heat = seats?.heat?.[selected];
  const vent = seats?.ventilation?.[selected];
  const massage = seats?.massage?.[selected];
  const windowKey = WINDOW_KEY[selected];
  const doorKey = DOOR_KEY[selected];
  const windowPct = windowKey ? cabin?.windows?.[windowKey]?.percent : undefined;
  const doorLocked = doorKey ? cabin?.doors?.[doorKey]?.locked : undefined;
  const wheel = selected === "front_left" ? seats?.steering_wheel_heat : undefined;
  const zones = [selected];
  const readingOn =
    selected === "front_left"
      ? !!cabin?.lights?.reading_left?.enable
      : selected === "front_right"
        ? !!cabin?.lights?.reading_right?.enable
        : false;

  const seatOrder: SeatId[] = ["front_left", "front_right", "rear_left", "rear_middle", "rear_right"];
  const winRef = useRef<HTMLButtonElement | null>(null);
  const [winDragging, setWinDragging] = useState(false);
  const winDraggingRef = useRef(false);
  const [localWin, setLocalWin] = useState(windowPct ?? 0);
  const winHoldUntil = useRef(0);

  useEffect(() => {
    if (winDraggingRef.current) return;
    if (performance.now() < winHoldUntil.current) return;
    if (windowPct != null) setLocalWin(windowPct);
  }, [windowPct, selected]);

  const setWindowFromClientX = (clientX: number) => {
    if (!windowKey) return;
    const pct = sliderRatio(winRef.current, clientX) * 100;
    winHoldUntil.current = performance.now() + 420;
    setLocalWin(pct);
    onControl(
      "cabin.set_windows",
      { percent: Math.round(pct), positions: [windowKey] },
      { live: true },
    );
  };

  return (
    <section className="seat-studio" aria-label="座舱气候">
      <header className="studio-head">
        <div className="studio-title">
          <h3>座舱</h3>
          <p>
            {climate?.power ? "空调开" : "空调关"} · {cnMode(climate?.mode)} ·{" "}
            {climate?.recirculation ? "内循环" : "外循环"}
          </p>
        </div>
        <div className="studio-head-actions" role="group" aria-label="整车空调">
          <button
            type="button"
            className="studio-chip"
            onClick={() => {
              const modes = ["auto", "eco", "comfort", "heat", "cool"];
              const cur = climate?.mode || "auto";
              const next = modes[(modes.indexOf(cur) + 1) % modes.length];
              onControl("climate.set_mode", { mode: next, recirculation: climate?.recirculation }, {
                label: `空调模式 ${cnMode(next)}`,
              });
            }}
          >
            {cnMode(climate?.mode)}
          </button>
          <button
            type="button"
            className={`studio-chip${climate?.recirculation ? " on" : ""}`}
            onClick={() =>
              onControl("climate.set_mode", {
                mode: climate?.mode || "auto",
                recirculation: !climate?.recirculation,
              })
            }
          >
            {climate?.recirculation ? "内循环" : "外循环"}
          </button>
          <button
            type="button"
            className={`studio-master${climate?.power ? " on" : ""}`}
            onClick={() => onControl("climate.set_power", { enable: !climate?.power })}
          >
            {climate?.power ? "总开" : "总关"}
          </button>
        </div>
      </header>

      <div className="seat-rail" role="listbox" aria-label="选择座位">
        {seatOrder.map((id) => {
          const z = climate?.zones?.[id];
          const active = id === selected;
          const lit = !!z?.on;
          return (
            <motion.button
              key={id}
              type="button"
              role="option"
              aria-selected={active}
              aria-label={`${SEAT_LABELS[id]} ${lit ? "空调开" : "空调关"} ${z?.temp != null ? Math.round(z.temp) + "度" : ""}`}
              className={`seat-rail-item${active ? " selected" : ""}${lit ? " lit" : ""}`}
              onClick={() => onSelect(id)}
              whileTap={{ scale: 0.98 }}
              transition={{ type: "spring", stiffness: 420, damping: 28 }}
            >
              {active ? (
                <motion.span
                  layoutId="seat-rail-glow"
                  className="seat-rail-glow"
                  transition={{ type: "spring", stiffness: 380, damping: 32 }}
                />
              ) : null}
              <span className="seat-rail-name">
                {SEAT_LABELS[id]}
                {active ? <em>你</em> : null}
              </span>
              <strong className="seat-rail-temp">
                {Math.round(z?.temp ?? 22)}
                <small>°</small>
              </strong>
              <i className={`seat-rail-dot${lit ? " on" : ""}`} aria-hidden />
            </motion.button>
          );
        })}
      </div>

      <AnimatePresence mode="wait" initial={false}>
        <motion.div
          key={selected}
          className="seat-panel"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.16 }}
        >
          <div className="seat-panel-head">
            <div>
              <span className="seat-kicker">当前座位</span>
              <h4>{SEAT_LABELS[selected]}</h4>
            </div>
            <button
              type="button"
              className={`seat-zone-toggle${on ? " on" : ""}`}
              onClick={() => onControl("climate.set_power", { enable: !on, zones })}
            >
              <span>分区</span>
              <strong>{on ? "开" : "关"}</strong>
            </button>
          </div>

          <div className={`climate-hero${on ? "" : " dim"}`}>
            <motion.button
              type="button"
              className="climate-step"
              aria-label="降温"
              whileTap={{ scale: 0.92 }}
              onClick={() => onControl("climate.adjust_temperature", { delta: -1, zones })}
            >
              −
            </motion.button>
            <div className="climate-temp">
              <strong>
                {zone?.temp != null || on ? tempText : "—"}
                {(zone?.temp != null || on) && <small>°</small>}
              </strong>
              <span>目标温度</span>
            </div>
            <motion.button
              type="button"
              className="climate-step"
              aria-label="升温"
              whileTap={{ scale: 0.92 }}
              onClick={() => onControl("climate.adjust_temperature", { delta: 1, zones })}
            >
              +
            </motion.button>
          </div>

          <div className="climate-fan">
            <span className="seat-label">风速</span>
            <div className="fan-meter" role="group" aria-label="风速">
              {Array.from({ length: 5 }).map((_, i) => {
                const level = i + 1;
                const active = fan >= level;
                return (
                  <button
                    key={level}
                    type="button"
                    className={active ? "on" : ""}
                    aria-label={`风速 ${level}`}
                    aria-pressed={active}
                    onClick={() => onControl("climate.set_fan", { level, zones })}
                  >
                    <motion.i
                      initial={false}
                      animate={{ scaleY: active ? 1 : 0.35, opacity: active ? 1 : 0.45 }}
                      transition={{ type: "spring", stiffness: 320, damping: 26 }}
                    />
                  </button>
                );
              })}
            </div>
            <em className="seat-value">{fan || "—"}</em>
          </div>

          <div className="seat-feats">
            {(
              [
                { key: "heat", label: "加热", node: heat, feature: "heat" as const },
                { key: "vent", label: "通风", node: vent, feature: "ventilation" as const },
                { key: "massage", label: "按摩", node: massage, feature: "massage" as const },
              ] as const
            ).map((item) => (
              <motion.button
                key={item.key}
                type="button"
                className={`seat-feat${item.node?.enable ? " on" : ""}`}
                whileTap={{ scale: 0.98 }}
                onClick={() => cycleSeatFeature(onControl, item.feature, zones, item.node)}
              >
                <span className="seat-label">{item.label}</span>
                <strong className="seat-value">
                  {item.node?.enable ? `${item.node.level ?? 0}` : "关"}
                </strong>
                <SeatFeatLevel enable={item.node?.enable} level={item.node?.level} />
              </motion.button>
            ))}
          </div>

          <div className={`seat-window${windowPct == null ? " mute" : ""}`}>
            <div className="seat-window-meta">
              <span className="seat-label">车窗</span>
              <strong className="seat-value">
                {windowPct != null ? `${Math.round(localWin)}%` : "—"}
              </strong>
            </div>
            {windowPct != null ? (
              <button
                ref={winRef}
                type="button"
                className={`seat-window-track${winDragging ? " dragging" : ""}`}
                aria-label="调节车窗"
                aria-valuemin={0}
                aria-valuemax={100}
                aria-valuenow={Math.round(localWin)}
                onPointerDown={(e) => {
                  e.currentTarget.setPointerCapture(e.pointerId);
                  winDraggingRef.current = true;
                  setWinDragging(true);
                  setWindowFromClientX(e.clientX);
                }}
                onPointerMove={(e) => {
                  if (!winDraggingRef.current) return;
                  setWindowFromClientX(e.clientX);
                }}
                onPointerUp={() => {
                  winDraggingRef.current = false;
                  setWinDragging(false);
                }}
                onPointerCancel={() => {
                  winDraggingRef.current = false;
                  setWinDragging(false);
                }}
              >
                <i
                  className="seat-window-fill"
                  style={{ width: `${Math.max(0, Math.min(100, localWin))}%` }}
                />
                <em
                  className="seat-window-thumb"
                  style={{ left: `${Math.max(0, Math.min(100, localWin))}%` }}
                />
              </button>
            ) : (
              <div className="seat-window-track ghost" aria-hidden />
            )}
          </div>

          <div className="seat-toggles">
            {doorLocked != null ? (
              <button
                type="button"
                className={`seat-toggle${doorLocked ? "" : " warn"}`}
                onClick={() =>
                  onControl(
                    "cabin.set_door_locks",
                    { locked: !doorLocked, positions: [doorKey!] },
                    { confirmHigh: true, label: doorLocked ? "解锁车门？" : "锁上车门？" },
                  )
                }
              >
                {doorLocked ? "车门已锁" : "车门解锁"}
              </button>
            ) : null}
            {selected === "front_left" || selected === "front_right" ? (
              <button
                type="button"
                className={`seat-toggle${readingOn ? " on" : ""}`}
                onClick={() => {
                  const target = selected === "front_left" ? "reading_left" : "reading_right";
                  const node = cabin?.lights?.[target];
                  onControl("cabin.set_light", {
                    target,
                    enable: !node?.enable,
                    brightness: node?.enable ? 0 : 50,
                  });
                }}
              >
                阅读灯 {readingOn ? "开" : "关"}
              </button>
            ) : null}
            {wheel ? (
              <button
                type="button"
                className={`seat-toggle${wheel.enable ? " on" : ""}`}
                onClick={() =>
                  onControl("seat.steering_wheel_heat", {
                    enable: !wheel.enable,
                    level: 2,
                  })
                }
              >
                方向盘 {wheel.enable ? `${wheel.level ?? 0}` : "关"}
              </button>
            ) : null}
          </div>
        </motion.div>
      </AnimatePresence>
    </section>
  );
}

export function VehicleConsole() {
  const vehicle = useCabinStore((s) => s.vehicle) as CabinStateSnapshot | null;
  const activeSeat = useCabinStore((s) => s.activeSeat);
  const setActiveSeat = useCabinStore((s) => s.setActiveSeat);
  const sessionId = useCabinStore((s) => s.sessionId) || "default";
  const { run, tick, busy } = useVehicleControl();
  const dyn = vehicle?.dynamics;
  const speed = dyn?.speed_kmh ?? 0;
  const [weather, setWeather] = useState<WeatherPayload | null>(null);
  const posBucket = useMemo(() => {
    const p = vehicle?.navigation?.position;
    if (p?.lng == null || p?.lat == null) return "default";
    return `${Number(p.lng).toFixed(2)},${Number(p.lat).toFixed(2)}`;
  }, [vehicle?.navigation?.position?.lng, vehicle?.navigation?.position?.lat]);

  useEffect(() => {
    const ac = new AbortController();
    const id = window.setInterval(() => {
      if (document.hidden) return;
      void tick(ac.signal);
    }, 400);
    return () => {
      window.clearInterval(id);
      ac.abort();
    };
  }, [tick]);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const w = await fetchWeather(sessionId);
        if (!cancelled) setWeather(w);
      } catch {
        if (!cancelled) setWeather({ ok: false, summary: "天气暂不可用" });
      }
    };
    void load();
    const id = window.setInterval(() => void load(), WEATHER_POLL_MS);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
  }, [sessionId, posBucket]);

  const onControl = (
    tool: string,
    args: Record<string, unknown> = {},
    opts?: ControlOpts,
  ) => {
    void run(tool, args, opts);
  };

  return (
    <aside className="vehicle-console" aria-label="车辆中控状态">
      <div className="vc-body">
        <DriveCluster
          speed={speed}
          gear={dyn?.gear || "P"}
          parked={dyn?.parked}
          acc={!!vehicle?.driving?.adas?.acc}
          cruiseTarget={dyn?.cruise_set_kmh ?? dyn?.cruise_target_kmh}
          battery={vehicle?.driving?.battery_percent ?? 0}
          rangeKm={vehicle?.driving?.range_km}
          driveMode={vehicle?.driving?.mode}
          outsideTemp={weather?.ok ? weather.temperature : null}
          onControl={onControl}
        />
        <SharedDeck
          vehicle={vehicle}
          onControl={onControl}
          busy={busy}
          weather={weather}
        />
        <SeatCabinStudio
          vehicle={vehicle}
          selected={activeSeat}
          onSelect={setActiveSeat}
          onControl={onControl}
        />
      </div>
    </aside>
  );
}
