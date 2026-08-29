export type AmapConfig = {
  ok: boolean;
  provider: string;
  configured: boolean;
  js_key: string;
  security_code: string;
  origin: {
    name: string;
    address?: string;
    lng: number;
    lat: number;
    location: string;
  };
};

type AMapNS = {
  Map: new (
    container: HTMLElement,
    opts?: Record<string, unknown>,
  ) => {
    setCenter: (c: [number, number]) => void;
    setZoom: (z: number) => void;
    setFitView: (overlays?: unknown[], immediately?: boolean, avoid?: number[]) => void;
    destroy: () => void;
    add: (o: unknown) => void;
    remove: (o: unknown) => void;
  };
  Marker: new (opts: Record<string, unknown>) => {
    setPosition: (p: [number, number]) => void;
    setMap: (m: unknown) => void;
  };
  Polyline: new (opts: Record<string, unknown>) => {
    setPath: (p: [number, number][]) => void;
    setMap: (m: unknown) => void;
  };
  Icon: new (opts: Record<string, unknown>) => unknown;
  Size: new (w: number, h: number) => unknown;
  Pixel: new (x: number, y: number) => unknown;
  Buildings: new (opts?: Record<string, unknown>) => unknown;
  TileLayer: new (opts?: Record<string, unknown>) => unknown;
};

declare global {
  interface Window {
    AMap?: AMapNS;
    _AMapSecurityConfig?: { securityJsCode?: string };
    __amapLoaderPromise?: Promise<AMapNS>;
  }
}

let cachedConfig: AmapConfig | null = null;

export async function fetchAmapConfig(): Promise<AmapConfig> {
  if (cachedConfig) return cachedConfig;
  const res = await fetch("/api/maps/config");
  if (!res.ok) throw new Error(`maps config ${res.status}`);
  cachedConfig = (await res.json()) as AmapConfig;
  return cachedConfig;
}

export function clearAmapConfigCache() {
  cachedConfig = null;
}

export async function loadAmap(): Promise<{ AMap: AMapNS; config: AmapConfig }> {
  const config = await fetchAmapConfig();
  if (!config.js_key) {
    throw new Error("未配置 AMAP_JS_KEY，无法加载高德 JS 地图");
  }
  if (window.AMap) return { AMap: window.AMap, config };

  if (!window.__amapLoaderPromise) {
    window.__amapLoaderPromise = new Promise<AMapNS>((resolve, reject) => {
      if (config.security_code) {
        window._AMapSecurityConfig = { securityJsCode: config.security_code };
      }
      const script = document.createElement("script");
      script.src = `https://webapi.amap.com/maps?v=2.0&key=${encodeURIComponent(config.js_key)}`;
      script.async = true;
      script.onload = () => {
        if (window.AMap) resolve(window.AMap);
        else reject(new Error("AMap 加载失败"));
      };
      script.onerror = () => reject(new Error("高德 JS API 脚本加载失败"));
      document.head.appendChild(script);
    });
  }

  const AMap = await window.__amapLoaderPromise;
  return { AMap, config };
}
