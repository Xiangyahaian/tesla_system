import { memo, useEffect, useRef, useState, useCallback } from "react";
import { fetchAmapConfig, loadAmap } from "@/lib/amap";
import {
  BIT_ORIGIN,
  RouteDeadReckoner,
  routeFingerprint,
  type LngLat,
} from "@/lib/navMath";
import { useCabinStore } from "@/store/cabinStore";
import { PlaceSearchField } from "@/components/maps/PlaceSearchField";
import type { PlaceSearchHit } from "@/lib/api";

const QUICK_DESTS = ["中关村软件园", "五道口地铁站", "西单大悦城", "北京西站"];

type MapApi = {
  destroy: () => void;
  setCenter: (c: LngLat, immediately?: boolean) => void;
  setZoom: (z: number, immediately?: boolean) => void;
  getZoom: () => number;
  setFitView: (overlays?: unknown[], immediately?: boolean, avoid?: number[]) => void;
  panTo?: (c: LngLat) => void;
  zoomIn?: () => void;
  zoomOut?: () => void;
  resize?: () => void;
  add: (o: unknown) => void;
  remove: (o: unknown) => void;
};

type MarkerApi = {
  setPosition: (p: LngLat) => void;
  setMap: (m: unknown) => void;
  setAngle?: (deg: number) => void;
};
type PolyApi = {
  setPath: (p: LngLat[]) => void;
  setMap: (m: unknown) => void;
  setOptions?: (o: Record<string, unknown>) => void;
};

type Props = {
  open: boolean;
  onClose: () => void;
  onControl: (
    tool: string,
    args?: Record<string, unknown>,
    opts?: { confirmHigh?: boolean; label?: string },
  ) => void;
  busy?: boolean;
};

function AmapNavPanelImpl({ open, onClose, onControl, busy }: Props) {
  const hostRef = useRef<HTMLDivElement | null>(null);
  const mapRef = useRef<MapApi | null>(null);
  const carRef = useRef<MarkerApi | null>(null);
  const startRef = useRef<MarkerApi | null>(null);
  const endRef = useRef<MarkerApi | null>(null);
  const routeRef = useRef<PolyApi | null>(null);
  const passedRef = useRef<PolyApi | null>(null);
  const reckonRef = useRef(new RouteDeadReckoner());
  const followRef = useRef(true);
  const userInteracting = useRef(false);
  const interactTimer = useRef(0);
  const rafRef = useRef(0);
  const hudRef = useRef<HTMLDivElement | null>(null);
  const lastHudMs = useRef(0);
  const lastCamPos = useRef<LngLat | null>(null);
  const camPos = useRef<LngLat | null>(null);
  const lastPassedMs = useRef(0);
  const lastLoopTs = useRef(0);
  const lastKeyRef = useRef("");

  const mapEpoch = useCabinStore((s) => s.mapEpoch);

  const [error, setError] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  const [follow, setFollow] = useState(true);
  const [originInput, setOriginInput] = useState<string>("当前位置");
  const [destInput, setDestInput] = useState("");
  const [navigatingUi, setNavigatingUi] = useState(false);
  const [useLiveOrigin, setUseLiveOrigin] = useState(true);
  const originFocusedRef = useRef(false);
  const destFocusedRef = useRef(false);
  const useLiveOriginRef = useRef(true);
  const cruiseFpRef = useRef("");
  const displayPos = useRef<LngLat | null>(null);
  const sessionId = useCabinStore((s) => s.sessionId) || "default";
  const livePlaceName = useCabinStore((s) => s.vehicle?.navigation?.position?.name) || "当前位置";

  followRef.current = follow;
  useLiveOriginRef.current = useLiveOrigin;

  const markInteract = useCallback(() => {
    userInteracting.current = true;
    window.clearTimeout(interactTimer.current);
    interactTimer.current = window.setTimeout(() => {
      userInteracting.current = false;
    }, 2200);
  }, []);

  const liveSeed = (): LngLat => {
    const pos = useCabinStore.getState().vehicle?.navigation?.position;
    const lng = Number(pos?.lng);
    const lat = Number(pos?.lat);
    if (Number.isFinite(lng) && Number.isFinite(lat)) return [lng, lat];
    if (displayPos.current) return displayPos.current;
    return [BIT_ORIGIN.lng, BIT_ORIGIN.lat];
  };

  // 地图实例常驻：收起不销毁，避免再展开时闪回南门初始点
  useEffect(() => {
    let cancelled = false;
    let map: MapApi | null = null;
    const elHost = () => hostRef.current;

    (async () => {
      try {
        const c = await fetchAmapConfig();
        if (cancelled) return;
        if (!c.js_key) {
          setError("地图暂时无法加载，请稍后再试");
          return;
        }
        const { AMap } = await loadAmap();
        const host = elHost();
        if (cancelled || !host) return;

        const origin: LngLat = liveSeed();

        map = new AMap.Map(host, {
          zoom: 16,
          center: origin,
          viewMode: "2D",
          mapStyle: "amap://styles/whitesmoke",
          // 关闭地图自带动画，避免与我们每帧 setCenter 打架导致红点抖
          animateEnable: false,
          jogEnable: false,
          dragEnable: true,
          zoomEnable: true,
          doubleClickZoom: true,
          scrollWheel: true,
          touchZoom: true,
          keyboardEnable: true,
          showBuildingBlock: false,
        }) as unknown as MapApi;
        mapRef.current = map;

        host.addEventListener("wheel", markInteract, { passive: true });
        host.addEventListener("pointerdown", markInteract);

        const mkDot = (color: string, size = 14) =>
          `<div style="width:${size}px;height:${size}px;border-radius:50%;background:${color};border:2px solid #fff;box-shadow:0 1px 6px rgba(0,0,0,.35)"></div>`;

        const car = new AMap.Marker({
          position: origin,
          offset: new AMap.Pixel(-11, -11),
          zIndex: 120,
          content: mkDot("#b91c1c", 18),
          title: "本车",
        }) as unknown as MarkerApi;
        car.setMap(map);
        carRef.current = car;

        const start = new AMap.Marker({
          position: origin,
          offset: new AMap.Pixel(-8, -8),
          zIndex: 90,
          content: mkDot("#1a1c22", 12),
          title: "起点",
        }) as unknown as MarkerApi;
        start.setMap(map);
        startRef.current = start;

        const end = new AMap.Marker({
          position: origin,
          offset: new AMap.Pixel(-8, -8),
          zIndex: 90,
          content: mkDot("#2563eb", 12),
          title: "终点",
        }) as unknown as MarkerApi;
        endRef.current = end;

        const route = new AMap.Polyline({
          path: [],
          strokeColor: "#1a1c22",
          strokeWeight: 7,
          strokeOpacity: 0.88,
          lineJoin: "round",
          lineCap: "round",
          showDir: true,
          zIndex: 50,
        }) as unknown as PolyApi;
        route.setMap(map);
        routeRef.current = route;

        const passed = new AMap.Polyline({
          path: [],
          strokeColor: "#94a3b8",
          strokeWeight: 7,
          strokeOpacity: 0.75,
          lineJoin: "round",
          lineCap: "round",
          zIndex: 55,
        }) as unknown as PolyApi;
        passed.setMap(map);
        passedRef.current = passed;

        displayPos.current = origin;
        car.setPosition(origin);
        map.setCenter(origin, true);
        setReady(true);
        setError(null);
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      }
    })();

    return () => {
      cancelled = true;
      window.clearTimeout(interactTimer.current);
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
      const host = elHost();
      if (host) {
        host.removeEventListener("wheel", markInteract);
        host.removeEventListener("pointerdown", markInteract);
      }
      try {
        map?.destroy();
      } catch {
        /* ignore */
      }
      mapRef.current = null;
      carRef.current = null;
      startRef.current = null;
      endRef.current = null;
      routeRef.current = null;
      passedRef.current = null;
      reckonRef.current.clear();
      cruiseFpRef.current = "";
      lastKeyRef.current = "";
      displayPos.current = null;
      setReady(false);
    };
  }, [markInteract]);

  // 会话重置 / 切会话：不销毁地图，硬同步到南门（或当前快照位），清导航 HUD
  useEffect(() => {
    if (!ready || !mapRef.current) return;
    // 首次 ready 时 mapEpoch 为 0，跳过以免与初始化抢镜头
    if (mapEpoch <= 0) return;
    const nav = useCabinStore.getState().vehicle?.navigation;
    const lng = Number(nav?.position?.lng ?? BIT_ORIGIN.lng);
    const lat = Number(nav?.position?.lat ?? BIT_ORIGIN.lat);
    const place = String(nav?.position?.name || "当前位置");
    const origin: LngLat = [lng, lat];

    reckonRef.current.clear();
    cruiseFpRef.current = "";
    lastKeyRef.current = "";
    lastCamPos.current = origin;
    camPos.current = origin;
    lastPassedMs.current = 0;
    lastLoopTs.current = 0;
    displayPos.current = origin;
    carRef.current?.setPosition(origin);
    startRef.current?.setPosition(origin);
    routeRef.current?.setPath([]);
    passedRef.current?.setPath([]);
    endRef.current?.setMap(null);
    setDestInput("");
    setNavigatingUi(false);
    if (!originFocusedRef.current) setOriginInput(place);
    if (hudRef.current) {
      const speed = Number(useCabinStore.getState().vehicle?.dynamics?.speed_kmh || 0);
      hudRef.current.textContent =
        speed > 0.5 ? `${place} · ${Math.round(speed)} km/h` : `${place} · 未开启导航`;
    }
    try {
      mapRef.current.setZoom(16, true);
      mapRef.current.setCenter(origin, true);
    } catch {
      /* ignore */
    }
    setFollow(true);
  }, [mapEpoch, ready]);

  // 展开时：尺寸恢复后 resize，并把镜头贴回当前车位（不重建、不闪南门）
  useEffect(() => {
    if (!open || !ready || !mapRef.current) return;
    const map = mapRef.current;
    const center = displayPos.current || liveSeed();
    const sync = () => {
      try {
        map.resize?.();
      } catch {
        /* ignore */
      }
      map.setCenter(center, true);
      camPos.current = center;
      lastCamPos.current = center;
      carRef.current?.setPosition(center);
    };
    const id = window.requestAnimationFrame(sync);
    const t = window.setTimeout(sync, 80);
    return () => {
      window.cancelAnimationFrame(id);
      window.clearTimeout(t);
    };
  }, [open, ready]);

  useEffect(() => {
    if (!ready) return;

    let lastNav = false;

    const applyNav = () => {
      const v = useCabinStore.getState().vehicle;
      const nav = v?.navigation;
      const navigating = !!nav?.navigating;
      const poly = (nav?.polyline || [])
        .map((p) => [Number(p[0]), Number(p[1])] as LngLat)
        .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
      const key = routeFingerprint(poly);

      if (navigating !== lastNav) {
        lastNav = navigating;
        setNavigatingUi(navigating);
        // 仅在结束导航时清空终点，避免状态推送把正在输入的搜索词抹掉
        if (!navigating) {
          setDestInput("");
          setUseLiveOrigin(true);
        }
      }

      // 仅「开启导航」时渲染路线与终点；走廊折线只在后台驱动定位，不画到地图上
      if (navigating && key && poly.length >= 2) {
        const routeChanged = key !== lastKeyRef.current;
        if (routeChanged) {
          lastKeyRef.current = key;
          routeRef.current?.setPath(poly);
          routeRef.current?.setOptions?.({
            strokeColor: "#1a1c22",
            strokeWeight: 7,
            strokeOpacity: 0.88,
            showDir: true,
          });
          passedRef.current?.setPath([]);
          startRef.current?.setPosition(poly[0]);
          endRef.current?.setPosition(poly[poly.length - 1]);
          endRef.current?.setMap(mapRef.current);
          // 路线变化才重建推算器；每次状态推送都 setRoute 会把车标/镜头打回进度点并狂跳
          reckonRef.current.setRoute(poly, Number(nav?.progress_m || 0));
          cruiseFpRef.current = "";
          if (open) {
            try {
              mapRef.current?.setFitView([routeRef.current].filter(Boolean), true, [56, 80, 56, 130]);
            } catch {
              /* ignore */
            }
          }
        }
        if (nav?.origin_name && !originFocusedRef.current) {
          setOriginInput(String(nav.origin_name));
        }
        if (nav?.destination && !destFocusedRef.current) {
          setDestInput(String(nav.destination));
        }
      } else {
        if (lastKeyRef.current) {
          lastKeyRef.current = "";
          routeRef.current?.setPath([]);
          passedRef.current?.setPath([]);
          endRef.current?.setMap(null);
        }
        if (poly.length >= 2) {
          const progress = Number(nav?.progress_m || 0);
          // 重置会话后折线指纹往往不变，但 reckon 已被 clear；必须重新绑定
          const needBind = key !== cruiseFpRef.current || !reckonRef.current.hasRoute;
          if (needBind) {
            cruiseFpRef.current = key;
            reckonRef.current.setRoute(poly, progress);
            const plng = Number(nav?.position?.lng);
            const plat = Number(nav?.position?.lat);
            const snap: LngLat =
              Number.isFinite(plng) && Number.isFinite(plat) ? [plng, plat] : poly[0];
            displayPos.current = snap;
            camPos.current = snap;
            lastCamPos.current = snap;
            carRef.current?.setPosition(snap);
            if (open && followRef.current) {
              mapRef.current?.setCenter(snap, true);
            }
          }
        } else if (cruiseFpRef.current) {
          cruiseFpRef.current = "";
          reckonRef.current.clear();
        }
      }

      // 未开导航且仍用「我的位置」：起点跟随实时定位地名
      if (!navigating && !originFocusedRef.current && useLiveOriginRef.current) {
        const live = String(nav?.position?.name || "").trim();
        if (live) setOriginInput(live);
      }

      // 巡航/导航：服务端进度 + 车速校正（含往返方向）
      if (reckonRef.current.hasRoute) {
        reckonRef.current.setServerSample(
          Number(nav?.progress_m || 0),
          Number(v?.dynamics?.speed_kmh || 0),
          navigating ? 1 : Number(nav?.cruise_dir || 1),
        );
      }
    };

    applyNav();
    const unsub = useCabinStore.subscribe(applyNav);

    const loop = (now: number) => {
      const v = useCabinStore.getState().vehicle;
      const nav = v?.navigation;
      const speed = Number(v?.dynamics?.speed_kmh || 0);
      const mode = String(nav?.mode || (nav?.navigating ? "navigating" : "cruising"));

      const prevTs = lastLoopTs.current || now;
      lastLoopTs.current = now;
      const frameDt = Math.min(0.05, Math.max(0, (now - prevTs) / 1000));

      let target: LngLat | null = null;
      const routePose = reckonRef.current.hasRoute ? reckonRef.current.step(now) : null;
      if (routePose) {
        target = routePose.pos;
        // 已驶过折线：节流更新，避免每帧 setPath 拖垮主线程
        if (
          mode === "navigating" &&
          nav?.origin?.lng != null &&
          nav?.origin?.lat != null &&
          passedRef.current &&
          now - lastPassedMs.current > 120
        ) {
          lastPassedMs.current = now;
          const draw = displayPos.current || target;
          passedRef.current.setPath([
            [Number(nav.origin.lng), Number(nav.origin.lat)],
            draw,
          ]);
        }
      } else {
        const lng = Number(nav?.position?.lng);
        const lat = Number(nav?.position?.lat);
        if (Number.isFinite(lng) && Number.isFinite(lat)) {
          target = [lng, lat];
        }
      }

      // 统一平滑位姿：车标与镜头共用，避免相对抖动
      let pos: LngLat | null = null;
      if (target) {
        const cur = displayPos.current;
        if (!cur) {
          displayPos.current = target;
          pos = target;
        } else {
          const settle = followRef.current && !userInteracting.current ? 0.1 : 0.14;
          const a = 1 - Math.exp(-frameDt / settle);
          pos = [cur[0] + (target[0] - cur[0]) * a, cur[1] + (target[1] - cur[1]) * a];
          displayPos.current = pos;
        }
      }

      if (pos && carRef.current) {
        const following = open && followRef.current && !userInteracting.current;

        if (following) {
          // 跟随时：镜头与红点锁同一坐标，屏幕上红点钉在视野中心不抖
          camPos.current = pos;
          lastCamPos.current = pos;
          try {
            mapRef.current?.setCenter(pos, true);
          } catch {
            /* ignore */
          }
          carRef.current.setPosition(pos);
          if (mode === "navigating") startRef.current?.setPosition(pos);
        } else {
          carRef.current.setPosition(pos);
          if (mode === "navigating") startRef.current?.setPosition(pos);
        }

        if (now - lastHudMs.current > 400 && hudRef.current) {
          lastHudMs.current = now;
          if (mode === "navigating" && !!nav?.navigating && routePose) {
            const remainKm = (routePose.remaining / 1000).toFixed(1);
            // 用后端平滑后的 eta_min，不要用瞬时车速现场反推（会跟着演示车速大幅跳动）
            const eta = nav?.eta_min;
            const dest = nav?.destination || "";
            hudRef.current.textContent =
              routePose.remaining <= 12
                ? `已到达 · ${dest}`
                : `前往 ${dest} · 剩余 ${remainKm} km · 约 ${eta ?? "--"} 分`;
          } else if (mode === "parked") {
            const dest = nav?.destination || nav?.position?.name || "";
            hudRef.current.textContent =
              nav?.arrived && dest ? `已到达 · ${dest}` : "驻车";
          } else if (mode === "navigating" && !!nav?.navigating) {
            hudRef.current.textContent = `导航中 · ${Math.round(speed)} km/h`;
          } else {
            const place = nav?.position?.name || "当前位置";
            hudRef.current.textContent =
              speed > 0.5 ? `${place} · ${Math.round(speed)} km/h` : `${place} · 未开启导航`;
          }
        }
      }
      rafRef.current = requestAnimationFrame(loop);
    };
    rafRef.current = requestAnimationFrame(loop);

    return () => {
      unsub();
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    };
  }, [ready, open]);

  const startNav = () => {
    const destination = destInput.trim();
    if (!destination || destination === "未开启导航" || busy) return;
    const originRaw = originInput.trim();
    const args: Record<string, unknown> = {
      destination,
      preference: "fastest",
    };
    // 「我的位置」/ 实时路名 → 从当前定位出发
    if (!useLiveOrigin && originRaw && originRaw !== "当前位置" && originRaw !== livePlaceName) {
      args.origin = originRaw;
    }
    onControl("navigation.navigate_to", args, {
      label: `导航：${useLiveOrigin ? "当前位置" : originRaw || "当前位置"} → ${destination}`,
    });
  };

  const swapEnds = () => {
    if (navigatingUi || busy) return;
    const nextOrigin = destInput.trim();
    const nextDest = useLiveOrigin ? livePlaceName : originInput.trim();
    setOriginInput(nextOrigin || livePlaceName);
    setDestInput(nextDest === "当前位置" ? "" : nextDest);
    setUseLiveOrigin(false);
  };

  const onPickOrigin = (hit: PlaceSearchHit | { name: string; kind: "my_location" }) => {
    if ("kind" in hit && hit.kind === "my_location") {
      setUseLiveOrigin(true);
      setOriginInput(livePlaceName || "当前位置");
      return;
    }
    setUseLiveOrigin(false);
    setOriginInput(hit.name);
  };

  const onPickDest = (hit: PlaceSearchHit | { name: string; kind: "my_location" }) => {
    if ("kind" in hit && hit.kind === "my_location") return;
    setDestInput(hit.name);
  };

  const zoomBy = (delta: number) => {
    const map = mapRef.current;
    if (!map) return;
    markInteract();
    try {
      if (delta > 0 && map.zoomIn) map.zoomIn();
      else if (delta < 0 && map.zoomOut) map.zoomOut();
      else map.setZoom(Math.min(20, Math.max(3, (map.getZoom?.() || 16) + delta)), false);
    } catch {
      /* ignore */
    }
  };

  const locateMe = () => {
    const nav = useCabinStore.getState().vehicle?.navigation;
    const lng = Number(nav?.position?.lng ?? BIT_ORIGIN.lng);
    const lat = Number(nav?.position?.lat ?? BIT_ORIGIN.lat);
    const center: LngLat = [lng, lat];
    camPos.current = center;
    lastCamPos.current = center;
    mapRef.current?.setZoom(17, true);
    mapRef.current?.setCenter(center, true);
    setFollow(true);
  };

  const fitRoute = () => {
    if (!routeRef.current || !mapRef.current) return;
    markInteract();
    try {
      mapRef.current.setFitView([routeRef.current], false, [48, 64, 48, 110]);
    } catch {
      /* ignore */
    }
  };

  return (
    <div
      className={`amap-nav-panel amap-nav-pro${!open ? " is-collapsed" : ""}`}
      role="region"
      aria-label="导航地图"
      aria-hidden={!open}
    >
      <header className="amap-nav-head">
        <div>
          <em>导航</em>
          <strong ref={hudRef}>北京理工大学中关村校区南门</strong>
        </div>
        <div className="amap-head-actions">
          <button type="button" className="deck-inline-btn" onClick={onClose}>
            收起地图
          </button>
        </div>
      </header>

      <div className="amap-route-bar">
        <div className="amap-route-rail" aria-label="起终点">
          <PlaceSearchField
            kind="origin"
            value={originInput}
            placeholder="搜索起点"
            disabled={!!busy || navigatingUi}
            sessionId={sessionId}
            livePlaceName={livePlaceName}
            allowMyLocation
            onChange={(v) => {
              setOriginInput(v);
              setUseLiveOrigin(false);
            }}
            onPick={onPickOrigin}
            onFocusChange={(f) => {
              originFocusedRef.current = f;
            }}
          />
          <button
            type="button"
            className="amap-route-swap"
            title="交换起终点"
            aria-label="交换起终点"
            disabled={!!busy || navigatingUi}
            onClick={swapEnds}
          >
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M7 7h11M18 7l-3-3M18 7l-3 3M17 17H6M6 17l3-3M6 17l3 3" />
            </svg>
          </button>
          <PlaceSearchField
            kind="dest"
            value={destInput}
            placeholder="搜索终点"
            disabled={!!busy}
            sessionId={sessionId}
            onChange={setDestInput}
            onPick={onPickDest}
            onSubmit={startNav}
            onFocusChange={(f) => {
              destFocusedRef.current = f;
            }}
          />
        </div>
        <div className="amap-route-actions">
          {navigatingUi ? (
            <button
              type="button"
              className="deck-inline-btn amap-go-btn"
              disabled={!!busy}
              onClick={() => onControl("navigation.stop", {})}
            >
              结束导航
            </button>
          ) : (
            <button
              type="button"
              className="deck-inline-btn primary amap-go-btn"
              disabled={!!busy || !destInput.trim()}
              onClick={startNav}
            >
              开始导航
            </button>
          )}
        </div>
      </div>

      <div className="amap-nav-body">
        <div className="amap-map-host" ref={hostRef} />
        {error ? <div className="amap-map-error">{error}</div> : null}
        {!ready && !error ? <div className="amap-map-loading">地图加载中…</div> : null}

        <div className="amap-fab-stack" aria-label="地图控制">
          <button type="button" title="放大" aria-label="放大" onClick={() => zoomBy(1)}>
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <button type="button" title="缩小" aria-label="缩小" onClick={() => zoomBy(-1)}>
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M5 12h14" />
            </svg>
          </button>
          <button type="button" title="定位车辆" aria-label="定位车辆" onClick={locateMe}>
            <svg viewBox="0 0 24 24" aria-hidden>
              <circle cx="12" cy="12" r="3.2" />
              <path d="M12 3v3.2M12 17.8V21M3 12h3.2M17.8 12H21" />
            </svg>
          </button>
          <button
            type="button"
            title={follow ? "关闭跟随" : "开启跟随"}
            aria-label={follow ? "关闭跟随" : "开启跟随"}
            aria-pressed={follow}
            className={follow ? "on" : ""}
            onClick={() =>
              setFollow((v) => {
                const next = !v;
                if (next) {
                  const p = displayPos.current || liveSeed();
                  camPos.current = p;
                  lastCamPos.current = p;
                  try {
                    mapRef.current?.setCenter(p, true);
                  } catch {
                    /* ignore */
                  }
                }
                return next;
              })
            }
          >
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M12 3.5l6.5 16.2-6.5-3.4-6.5 3.4L12 3.5z" />
            </svg>
          </button>
          <button
            type="button"
            title="视野适配路线"
            aria-label="视野适配路线"
            onClick={fitRoute}
            disabled={!navigatingUi}
          >
            <svg viewBox="0 0 24 24" aria-hidden>
              <path d="M4 9V4h5M20 9V4h-5M4 15v5h5M20 15v5h-5" />
            </svg>
          </button>
        </div>
      </div>

      <footer className="amap-nav-foot">
        <div className="amap-quick">
          {QUICK_DESTS.map((d) => (
            <button
              key={d}
              type="button"
              className="deck-inline-btn"
              disabled={!!busy}
              onClick={() => {
                setDestInput(d);
                const originRaw = originInput.trim();
                const args: Record<string, unknown> = {
                  destination: d,
                  preference: "fastest",
                };
                if (
                  !useLiveOrigin &&
                  originRaw &&
                  originRaw !== "当前位置" &&
                  originRaw !== livePlaceName
                ) {
                  args.origin = originRaw;
                }
                onControl("navigation.navigate_to", args, { label: `导航到${d}` });
              }}
            >
              {d}
            </button>
          ))}
        </div>
      </footer>
    </div>
  );
}

export const AmapNavPanel = memo(AmapNavPanelImpl);
