/** 导航几何：折线测距 / 沿线插值（与后端 advance_along_polyline 对齐） */

export type LngLat = [number, number];

export function haversineM(a: LngLat, b: LngLat): number {
  const R = 6371000;
  const p1 = (a[1] * Math.PI) / 180;
  const p2 = (b[1] * Math.PI) / 180;
  const dp = ((b[1] - a[1]) * Math.PI) / 180;
  const dl = ((b[0] - a[0]) * Math.PI) / 180;
  const x =
    Math.sin(dp / 2) ** 2 + Math.cos(p1) * Math.cos(p2) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.min(1, Math.sqrt(x)));
}

export function polylineLengthM(pts: LngLat[]): number {
  let t = 0;
  for (let i = 1; i < pts.length; i++) t += haversineM(pts[i - 1], pts[i]);
  return t;
}

/** 预计算累计弧长，O(1) 近似二分定位 */
export function buildArcTable(pts: LngLat[]): { pts: LngLat[]; cum: number[]; total: number } {
  const cum = [0];
  for (let i = 1; i < pts.length; i++) {
    cum.push(cum[i - 1] + haversineM(pts[i - 1], pts[i]));
  }
  return { pts, cum, total: cum[cum.length - 1] || 0 };
}

export function advanceAlongArc(
  table: { pts: LngLat[]; cum: number[]; total: number },
  distM: number,
): { pos: LngLat; progress: number; remaining: number; heading: number } {
  const { pts, cum, total } = table;
  if (!pts.length) {
    return { pos: [116.316356, 39.957053], progress: 0, remaining: 0, heading: 0 };
  }
  if (pts.length === 1 || total <= 0) {
    return { pos: pts[0], progress: 0, remaining: 0, heading: 0 };
  }
  const target = Math.max(0, Math.min(total, distM));
  // 二分找段
  let lo = 0;
  let hi = cum.length - 1;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (cum[mid] < target) lo = mid + 1;
    else hi = mid;
  }
  const i = Math.max(1, lo);
  const segStart = cum[i - 1];
  const segLen = cum[i] - segStart || 1e-6;
  const ratio = (target - segStart) / segLen;
  const a = pts[i - 1];
  const b = pts[i];
  const pos: LngLat = [a[0] + (b[0] - a[0]) * ratio, a[1] + (b[1] - a[1]) * ratio];
  const heading = (Math.atan2(b[0] - a[0], b[1] - a[1]) * 180) / Math.PI;
  return { pos, progress: target, remaining: Math.max(0, total - target), heading: (heading + 360) % 360 };
}

/**
 * 互补滤波式进度融合（类导航 SDK dead-reckoning）：
 * 本地按车速积分，再向服务端进度做指数收敛，避免 4Hz 硬跳。
 */
export class RouteDeadReckoner {
  private table: ReturnType<typeof buildArcTable> | null = null;
  private localProgress = 0;
  private serverProgress = 0;
  private speedMps = 0;
  private lastTs = 0;
  /** 向 server 收敛时间常数（秒）——略大更稳，少抖 */
  private tau = 1.35;

  setRoute(pts: LngLat[], progressM = 0) {
    this.table = pts.length ? buildArcTable(pts) : null;
    this.localProgress = progressM;
    this.serverProgress = progressM;
    this.lastTs = performance.now();
  }

  clear() {
    this.table = null;
    this.localProgress = 0;
    this.serverProgress = 0;
    this.speedMps = 0;
    this.lastTs = 0;
  }

  /** direction: 1 沿折线正向，-1 反向（道路巡航往返） */
  setServerSample(progressM: number, speedKmh: number, direction = 1) {
    const next = Math.max(0, progressM);
    // 仅会话重置/重规划等大幅跳变时硬同步；正常巡航用滤波收敛
    if (Math.abs(next - this.serverProgress) > 220 || Math.abs(next - this.localProgress) > 220) {
      this.localProgress = next;
      this.lastTs = performance.now();
    }
    this.serverProgress = next;
    const dir = direction < 0 ? -1 : 1;
    // 车速做轻平滑，避免演示 ACC 噪声直接灌进积分
    const raw = (Math.max(0, speedKmh) / 3.6) * dir;
    this.speedMps = this.speedMps ? this.speedMps * 0.72 + raw * 0.28 : raw;
  }

  /** 每帧调用，返回插值后的位姿 */
  step(now = performance.now()): {
    pos: LngLat;
    progress: number;
    remaining: number;
    heading: number;
  } | null {
    if (!this.table) return null;
    if (!this.lastTs) this.lastTs = now;
    const dt = Math.min(0.1, Math.max(0, (now - this.lastTs) / 1000));
    this.lastTs = now;

    // 积分
    this.localProgress += this.speedMps * dt;
    // 误差很小时不硬拉，避免红点微抖；大误差再指数收敛
    const err = this.serverProgress - this.localProgress;
    if (Math.abs(err) > 0.8) {
      const alpha = 1 - Math.exp(-dt / this.tau);
      this.localProgress += err * alpha;
    }

    const total = this.table.total;
    if (this.localProgress > total) this.localProgress = total;
    if (this.localProgress < 0) this.localProgress = 0;

    const pose = advanceAlongArc(this.table, this.localProgress);
    let heading = pose.heading;
    if (this.speedMps < 0) heading = (heading + 180) % 360;
    return { ...pose, heading };
  }

  get hasRoute() {
    return !!this.table && this.table.pts.length >= 2;
  }
}

export function routeFingerprint(poly?: number[][] | null): string {
  if (!poly?.length) return "";
  const a = poly[0];
  const b = poly[poly.length - 1];
  const mid = poly[Math.floor(poly.length / 2)] || a;
  return `${poly.length}:${a?.[0]},${a?.[1]}:${mid?.[0]},${mid?.[1]}:${b?.[0]},${b?.[1]}`;
}

export const BIT_ORIGIN = {
  name: "北京理工大学中关村校区南门",
  lng: 116.316356,
  lat: 39.957053,
} as const;
