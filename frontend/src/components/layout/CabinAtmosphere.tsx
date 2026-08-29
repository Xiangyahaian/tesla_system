import { useEffect, useRef } from "react";
import { useCabinStore } from "@/store/cabinStore";
import {
  advanceAlongArc,
  buildArcTable,
  routeFingerprint,
  type LngLat,
} from "@/lib/navMath";

type ArcTable = ReturnType<typeof buildArcTable>;

function wrap180(d: number) {
  let x = d;
  while (x > 180) x -= 360;
  while (x < -180) x += 360;
  return x;
}

/**
 * 第一人称街谷：坐在车道中央往前看，两侧高楼，
 * 导航/巡航折线驱动前方道路弯曲；不是俯视地图。
 */
export function CabinAtmosphere() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d", { alpha: false });
    if (!ctx) return;

    let raf = 0;
    let timer = 0;
    let last = performance.now();
    let w = 0;
    let h = 0;
    let dpr = 1;
    let visible = !document.hidden;

    let speedSmooth = 0;
    let travel = 0;
    let table: ArcTable | null = null;
    let routeKey = "";
    let progressLocal = 0;
    let progressVis = 0;
    let travelDir = 1;
    let lastDt = 1 / 60;
    /** 目标弯道采样（米）；显示用 bendDisp 做时间平滑 */
    let bendTarget: { z: number; x: number }[] = [];
    let bendDisp: { z: number; x: number }[] = [];
    let hdgFilt: { d: number; h: number }[] = [];
    /** 每栋楼横向低通，压掉远景抖动 */
    const bldCx = new Map<number, number>();

    const laneHalf = 2.0;
    const nearZ = 2.8;
    /** 建筑近裁：比路面更近，允许楼从身侧掠到镜头后再没 */
    const clipZ = 0.78;
    const farZ = 140;
    /** 固定深度栅格：避免每帧采样点错位把远景拧抖 */
    const BEND_Z = [2.8, 4.2, 6, 8.2, 11, 14.5, 19, 25, 32, 41, 52, 66, 82, 102, 126, 150];

    const schedule = (delayMs: number) => {
      if (!visible) return;
      if (delayMs > 0) {
        timer = window.setTimeout(() => {
          timer = 0;
          raf = requestAnimationFrame(tick);
        }, delayMs);
      } else {
        raf = requestAnimationFrame(tick);
      }
    };

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      dpr = Math.min(window.devicePixelRatio || 1, 1.5);
      w = parent.clientWidth;
      h = parent.clientHeight;
      canvas.width = Math.max(1, Math.floor(w * dpr));
      canvas.height = Math.max(1, Math.floor(h * dpr));
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    resize();
    const ro = new ResizeObserver(resize);
    if (canvas.parentElement) ro.observe(canvas.parentElement);

    const onVis = () => {
      visible = !document.hidden;
      if (visible) {
        last = performance.now();
        schedule(0);
      } else {
        cancelAnimationFrame(raf);
        window.clearTimeout(timer);
      }
    };
    document.addEventListener("visibilitychange", onVis);

    /** 第一人称投影：眼高 camH，看向前方。z 只做数值保护，不把楼「钉」在近平面上。 */
    const project = (x: number, y: number, z: number, horizonY: number, focal: number, camH: number) => {
      const zz = Math.max(clipZ * 0.92, z);
      const scale = focal / zz;
      return {
        sx: w * 0.5 + x * scale,
        sy: horizonY + (camH - y) * scale,
        scale,
      };
    };

    const headingRaw = (dist: number, sign: number) => {
      if (!table) return 0;
      const pose = advanceAlongArc(table, Math.max(0, Math.min(table.total, dist)));
      let hd = pose.heading;
      if (sign < 0) hd = (hd + 180 + 360) % 360;
      return hd;
    };

    /** ±win 米圆形加权平均，把折线尖角收成连续弯道 */
    const headingBlend = (dist: number, sign: number, win = 42) => {
      if (!table) return 0;
      const offs = [-1, -0.55, -0.22, 0, 0.22, 0.55, 1];
      let cx = 0;
      let cy = 0;
      for (const o of offs) {
        const rad = (headingRaw(dist + o * win * sign, sign) * Math.PI) / 180;
        const wt = 1 - Math.abs(o) * 0.32;
        cx += Math.cos(rad) * wt;
        cy += Math.sin(rad) * wt;
      }
      return (Math.atan2(cy, cx) * 180) / Math.PI;
    };

    const lerpHeading = (samples: { d: number; h: number }[], d: number) => {
      if (!samples.length) return 0;
      if (d <= samples[0].d) return samples[0].h;
      const last = samples[samples.length - 1];
      if (d >= last.d) return last.h;
      let i = 1;
      while (i < samples.length && samples[i].d < d) i++;
      const a = samples[i - 1];
      const b = samples[i];
      const t = (d - a.d) / Math.max(1e-3, b.d - a.d);
      return a.h + t * (b.h - a.h);
    };

    /**
     * 前方路形：先把航向在路径上展开成连续曲线，再沿固定深度积分。
     * 航向做时间低通，拐弯跟手、远景不跟折线顶点抖。
     */
    const sampleBend = (fromProg: number, dir: number) => {
      const out: { z: number; x: number }[] = [];
      if (!table || table.pts.length < 2) return out;
      const sign = dir < 0 ? -1 : 1;
      const remain =
        sign > 0 ? Math.max(0, table.total - fromProg) : Math.max(0, fromProg);
      const maxD = Math.min(BEND_Z[BEND_Z.length - 1], Math.max(64, remain));
      const hdg: { d: number; h: number }[] = [];
      for (let d = 0; d <= maxD + 8; d += 5) {
        hdg.push({ d, h: headingBlend(fromProg + d * sign, sign) });
      }
      for (let i = 1; i < hdg.length; i++) {
        hdg[i].h = hdg[i - 1].h + wrap180(hdg[i].h - hdg[i - 1].h);
      }
      if (hdgFilt.length >= 2) {
        for (const s of hdg) {
          const prev = lerpHeading(hdgFilt, s.d);
          const tau = 0.24 + Math.min(0.55, (s.d / 140) * 0.55);
          s.h = prev + (s.h - prev) * (1 - Math.exp(-lastDt / tau));
        }
      }
      hdgFilt = hdg.map((s) => ({ ...s }));
      const camH = lerpHeading(hdg, 0);
      let x = 0;
      let psi = 0;
      let prevD = 0;
      let prevH = camH;
      let lastX = 0;
      for (const z of BEND_Z) {
        if (z <= maxD) {
          const h = lerpHeading(hdg, z);
          const step = z - prevD;
          psi += ((h - prevH) * Math.PI) / 180;
          x += Math.sin(psi) * step;
          prevD = z;
          prevH = h;
          const lim = 1.05 * z + 3.2;
          lastX = lim * Math.tanh(x / Math.max(lim, 1e-3));
        }
        out.push({ z, x: lastX });
      }
      if (out.length >= 4) {
        const xs = out.map((p) => p.x);
        for (let i = 1; i < out.length - 1; i++) {
          out[i].x = xs[i - 1] * 0.2 + xs[i] * 0.6 + xs[i + 1] * 0.2;
        }
      }
      return out;
    };

    const sampleX = (samples: { z: number; x: number }[], z: number) => {
      if (samples.length < 2) return 0;
      if (z <= samples[0].z) return samples[0].x * (z / Math.max(samples[0].z, 1e-3));
      const last = samples[samples.length - 1];
      if (z >= last.z) return last.x;
      let i = 1;
      while (i < samples.length && samples[i].z < z) i++;
      const a = samples[i - 1];
      const b = samples[i];
      const t = (z - a.z) / Math.max(1e-3, b.z - a.z);
      return a.x + (b.x - a.x) * t;
    };

    const centerAtZ = (z: number) => {
      const samples = bendDisp.length >= 2 ? bendDisp : bendTarget;
      return sampleX(samples, z);
    };

    /** 同深度对齐平滑；远处时间常数更大，弯道跟手但远景不抖 */
    const smoothBend = (dt: number) => {
      if (!bendTarget.length) {
        if (bendDisp.length) {
          const a = 1 - Math.exp(-dt / 0.34);
          for (const p of bendDisp) p.x += (0 - p.x) * a;
          if (bendDisp.every((p) => Math.abs(p.x) < 0.03)) bendDisp = [];
        }
        return;
      }
      if (!bendDisp.length || bendDisp.length !== bendTarget.length) {
        bendDisp = bendTarget.map((p) => ({ ...p }));
        return;
      }
      for (let i = 0; i < bendTarget.length; i++) {
        const z = bendTarget[i].z;
        const tau = 0.28 + Math.min(0.55, (z / farZ) * 0.7);
        const a = 1 - Math.exp(-dt / tau);
        bendDisp[i].z = z;
        bendDisp[i].x += (bendTarget[i].x - bendDisp[i].x) * a;
      }
    };

    /** 程序化建筑：世界坐标安置，不短循环；近裁不硬夹，避免窗「被删」 */
    type Bld = {
      depth: number;
      width: number;
      height: number;
      setback: number;
      floors: number;
      cols: number;
      style: 0 | 1 | 2 | 3;
      wall: [number, number, number];
      trim: [number, number, number];
      roof: [number, number, number];
      glass: [number, number, number];
      podium: number;
      litMask: number;
    };

    const hash01 = (n: number) => {
      let x = (n | 0) * 374761393 + 668265263;
      x = (x ^ (x >>> 13)) * 1274126177;
      x = x ^ (x >>> 16);
      return (x >>> 0) / 4294967296;
    };

    const PALETTES: [number, number, number][] = [
      [150, 154, 162],
      [168, 162, 152],
      [132, 140, 152],
      [158, 154, 148],
      [124, 132, 144],
      [172, 168, 160],
      [140, 146, 156],
      [160, 156, 150],
    ];

    const makeBuilding = (slot: number, side: -1 | 1): Bld => {
      const a = hash01(slot * 17 + (side < 0 ? 3 : 9));
      const b = hash01(slot * 29 + (side < 0 ? 5 : 11));
      const c = hash01(slot * 47 + (side < 0 ? 7 : 13));
      const d = hash01(slot * 61 + (side < 0 ? 19 : 23));
      const style = (Math.floor(a * 4) % 4) as 0 | 1 | 2 | 3;
      const wall = PALETTES[Math.floor(b * PALETTES.length) % PALETTES.length];
      const depth = 9 + c * 8;
      const width = 7 + d * 5;
      const height =
        style === 0 ? 11 + a * 9 : style === 1 ? 8 + a * 5 : style === 2 ? 10 + a * 7 : 12 + a * 10;
      const floors = Math.max(2, Math.min(6, Math.round(height / 3.2)));
      return {
        depth,
        width,
        height,
        setback: 5.8 + b * 2.4,
        floors,
        cols: 2 + Math.floor(d * 3),
        style,
        wall,
        trim: [wall[0] - 14, wall[1] - 12, wall[2] - 10],
        roof: [wall[0] + 22, wall[1] + 20, wall[2] + 18],
        glass: style === 3 ? [168, 192, 214] : [200, 210, 222],
        podium: style === 2 ? 2.8 + c * 1.2 : 0,
        litMask: Math.floor(hash01(slot * 91 + (side < 0 ? 1 : 2)) * 0xffffffff),
      };
    };

    const rgb = (c: [number, number, number], mul = 1, a = 1) =>
      a < 1
        ? `rgba(${(Math.max(0, Math.min(255, c[0] * mul)) | 0)},${(Math.max(0, Math.min(255, c[1] * mul)) | 0)},${(Math.max(0, Math.min(255, c[2] * mul)) | 0)},${a})`
        : `rgb(${(Math.max(0, Math.min(255, c[0] * mul)) | 0)},${(Math.max(0, Math.min(255, c[1] * mul)) | 0)},${(Math.max(0, Math.min(255, c[2] * mul)) | 0)})`;

    const fillPoly = (pts: { sx: number; sy: number }[], color: string) => {
      if (pts.length < 3) return;
      ctx.fillStyle = color;
      ctx.beginPath();
      ctx.moveTo(pts[0].sx, pts[0].sy);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i].sx, pts[i].sy);
      ctx.closePath();
      ctx.fill();
    };

    const draw = (spd: number) => {
      const horizonY = h * 0.46;
      const focal = h * 1.05;
      const camH = 1.25;
      // 镜头始终朝车头：不做整屏「探弯」平移（那会造成直道也在甩）
      const steerPx = 0;

      const sky = ctx.createLinearGradient(0, 0, 0, horizonY + 8);
      sky.addColorStop(0, "#c8d0e0");
      sky.addColorStop(0.55, "#e6eaf2");
      sky.addColorStop(1, "#f1f3f7");
      ctx.fillStyle = sky;
      ctx.fillRect(0, 0, w, h);

      const fog = ctx.createLinearGradient(0, horizonY - 50, 0, horizonY + 24);
      fog.addColorStop(0, "rgba(210,216,228,0)");
      fog.addColorStop(1, "rgba(198,204,216,0.5)");
      ctx.fillStyle = fog;
      ctx.fillRect(0, horizonY - 50, w, 74);

      const proj = (x: number, y: number, z: number) => {
        const p = project(x, y, z, horizonY, focal, camH);
        return { sx: p.sx + steerPx, sy: p.sy, scale: p.scale };
      };

      type Place = { side: -1 | 1; z0: number; z1: number; b: Bld; slot: number };
      const places: Place[] = [];
      const seenSlots = new Set<number>();
      const PITCH = 26;
      for (const side of [-1, 1] as const) {
        const first = Math.floor((travel - 12) / PITCH) - 1;
        for (let s = first; s <= first + 16; s++) {
          if (s < -2) continue;
          const slot = s * 2 + (side < 0 ? 0 : 1);
          const b = makeBuilding(slot, side);
          const world0 = s * PITCH + hash01(s * 3 + (side < 0 ? 1 : 2)) * 3;
          const z0 = world0 - travel;
          const z1 = z0 + b.depth;
          if (z1 < clipZ || z0 > farZ) continue;
          places.push({ side, z0, z1, b, slot });
        }
      }
      places.sort((p, q) => q.z1 - p.z1);

      for (const { side, z0, z1, b, slot } of places) {
        const zA = Math.max(z0, clipZ);
        const zB = z1;
        if (zB - zA < 0.1) continue;
        const uA = (zA - z0) / Math.max(1e-4, z1 - z0);
        const zMid = (zA + zB) * 0.5;
        const farDamp = Math.min(1, Math.max(0, (zMid - 28) / 90));
        const rawCx = centerAtZ(zMid) * (1 - farDamp * 0.62);
        const prevCx = bldCx.get(slot);
        const cxTau = 0.16 + farDamp * 0.55;
        const cx =
          prevCx == null ? rawCx : prevCx + (rawCx - prevCx) * (1 - Math.exp(-lastDt / cxTau));
        bldCx.set(slot, cx);
        const curb = laneHalf + b.setback;
        const innerN = cx + side * curb;
        const outerN = innerN + side * b.width;
        const innerF = innerN;
        const outerF = outerN;
        const farLod = zA > 42;
        const skipStroke = zA > 30;
        seenSlots.add(slot);

        const H = b.height;
        const Hp = b.podium > 0 ? Math.min(b.podium, H * 0.32) : 0;

        const nIG = proj(innerN, 0, zA);
        const nOG = proj(outerN, 0, zA);
        const nIR = proj(innerN, H, zA);
        const nOR = proj(outerN, H, zA);
        const fIG = proj(innerF, 0, zB);
        const fOG = proj(outerF, 0, zB);
        const fIR = proj(innerF, H, zB);
        const fOR = proj(outerF, H, zB);

        const minS = Math.min(nIG.sx, nOG.sx, fIG.sx, fOG.sx, nIR.sx, fIR.sx);
        const maxS = Math.max(nIG.sx, nOG.sx, fIG.sx, fOG.sx, nIR.sx, fIR.sx);
        if (maxS < -w * 0.4 || minS > w * 1.4) continue;

        const sliver = zB - zA;
        const passA = sliver < 2.4 ? Math.max(0, sliver / 2.4) : 1;

        const fogK = Math.max(0.4, Math.min(1, 1.08 - zA / farZ));
        const sun = side < 0 ? 0.94 : 1.04;
        ctx.globalAlpha = passA;

        fillPoly([nIR, nOR, fOR, fIR], rgb(b.roof, 0.8 * fogK * sun));
        fillPoly([fIG, fOG, fOR, fIR], rgb(b.trim, 0.72 * fogK));
        fillPoly([nOG, fOG, fOR, nOR], rgb(b.wall, 0.74 * fogK * (side < 0 ? 0.9 : 0.82)));
        fillPoly([nIG, nOG, nOR, nIR], rgb(b.trim, 0.84 * fogK * sun));
        fillPoly([nIG, fIG, fIR, nIR], rgb(b.wall, 0.96 * fogK * sun));

        if (farLod) {
          ctx.globalAlpha = 1;
          continue;
        }

        const visU = (u: number) => {
          const uc = Math.max(u, uA);
          const z = z0 + (z1 - z0) * uc;
          const t = (uc - uA) / Math.max(1e-4, 1 - uA);
          return { z, inn: innerN + (innerF - innerN) * t };
        };
        const visAt = (u: number, y: number, xOff = 0) => {
          const p = visU(u);
          return proj(p.inn + xOff, y, p.z);
        };

        ctx.strokeStyle = rgb(b.trim, 0.9 * fogK, 0.28);
        ctx.lineWidth = 1;
        if (!skipStroke) {
          for (let f = 1; f < b.floors; f++) {
            const y = (H * f) / b.floors;
            if (Hp > 0 && y < Hp + 0.3) continue;
            const a = visAt(uA, y, side * 0.05);
            const bb = visAt(1, y, side * 0.05);
            ctx.beginPath();
            ctx.moveTo(a.sx, a.sy);
            ctx.lineTo(bb.sx, bb.sy);
            ctx.stroke();
          }
        }

        if (Hp > 0.5) {
          const nIP = proj(innerN, Hp, zA);
          const fIP = proj(innerF, Hp, zB);
          fillPoly([nIG, fIG, fIP, nIP], rgb(b.trim, 0.58 * fogK));
          ctx.globalAlpha = 0.4 * fogK * passA;
          fillPoly(
            [
              visAt(Math.max(uA, 0.04), 0.45, side * 0.25),
              visAt(0.96, 0.45, side * 0.25),
              visAt(0.96, Hp - 0.35, side * 0.25),
              visAt(Math.max(uA, 0.04), Hp - 0.35, side * 0.25),
            ],
            rgb(b.glass, 1),
          );
          ctx.globalAlpha = passA;
          const doorU = 0.35 + hash01(slot * 5) * 0.3;
          if (doorU > uA - 0.08) {
            const p = visU(doorU);
            fillPoly(
              [
                proj(p.inn + side * 0.2, 0, Math.max(clipZ, p.z - 0.7)),
                proj(p.inn + side * 0.2, 0, Math.max(clipZ, p.z + 0.7)),
                proj(p.inn + side * 0.2, 2.1, Math.max(clipZ, p.z + 0.7)),
                proj(p.inn + side * 0.2, 2.1, Math.max(clipZ, p.z - 0.7)),
              ],
              rgb([48, 52, 60], 0.95 * fogK),
            );
          }
        }

        const y0 = Hp > 0 ? Hp + 0.55 : 1.0;
        const y1 = H - 0.9;
        const winRows = b.floors;
        const winCols = b.cols;
        ctx.globalAlpha = (b.style === 3 ? 0.5 : 0.36) * fogK * passA;
        for (let r = 0; r < winRows; r++) {
          const ya = y0 + ((y1 - y0) * (r + 0.12)) / winRows;
          const yb = y0 + ((y1 - y0) * (r + 0.78)) / winRows;
          if (ya < Hp + 0.15) continue;
          for (let c = 0; c < winCols; c++) {
            const wu0 = (c + 0.16) / winCols;
            const wu1 = (c + 0.84) / winCols;
            if (wu1 < uA) continue;
            const bit = (b.litMask >>> ((r * 5 + c) & 31)) & 1;
            fillPoly(
              [visAt(wu0, ya, side * 0.1), visAt(wu1, ya, side * 0.1), visAt(wu1, yb, side * 0.1), visAt(wu0, yb, side * 0.1)],
              bit ? rgb(b.glass, 1.08) : rgb([86, 94, 106], 0.95),
            );
          }
        }
        ctx.globalAlpha = passA;

        if (!skipStroke) {
          ctx.strokeStyle = rgb(b.trim, 0.88 * fogK, 0.3);
          ctx.lineWidth = 1;
          for (let c = 1; c < winCols; c++) {
            const u = c / winCols;
            if (u < uA) continue;
            const a = visAt(u, y0, side * 0.06);
            const bb = visAt(u, y1, side * 0.06);
            ctx.beginPath();
            ctx.moveTo(a.sx, a.sy);
            ctx.lineTo(bb.sx, bb.sy);
            ctx.stroke();
          }
        }

        const cap = 0.45;
        fillPoly(
          [proj(innerN, H, zA), proj(innerF, H, zB), proj(innerF, H + cap, zB), proj(innerN, H + cap, zA)],
          rgb(b.trim, 0.88 * fogK),
        );

        if (b.style !== 3 && hash01(slot * 11) > 0.45 && uA < 0.72) {
          const br = 1 + Math.floor(hash01(slot * 13) * Math.max(1, winRows - 1));
          const y = y0 + ((y1 - y0) * (br + 0.5)) / winRows;
          const out = side * 0.85;
          fillPoly(
            [
              visAt(Math.max(0.2, uA), y, out),
              visAt(0.8, y, out),
              visAt(0.8, y + 0.9, out),
              visAt(Math.max(0.2, uA), y + 0.9, out),
            ],
            rgb(b.trim, 0.75 * fogK),
          );
        }
        ctx.globalAlpha = 1;
      }
      for (const k of [...bldCx.keys()]) {
        if (!seenSlots.has(k)) bldCx.delete(k);
      }

      const sampleZs = (z0: number, z1: number) => {
        const out: number[] = [];
        let z = z0;
        while (z < z1) {
          out.push(z);
          z += z < 12 ? 0.8 : z < 28 ? 1.4 : z < 55 ? 2.2 : 3.4;
        }
        out.push(z1);
        return out;
      };

      ctx.globalAlpha = 1;
      for (const side of [-1, 1] as const) {
        const edge: { sx: number; sy: number }[] = [];
        const outer: { sx: number; sy: number }[] = [];
        for (const z of sampleZs(nearZ, 85)) {
          const cx = centerAtZ(z);
          edge.push(proj(cx + side * laneHalf, 0.02, z));
          outer.push(proj(cx + side * (laneHalf + 2.4), 0.02, z));
        }
        if (edge.length < 2) continue;
        ctx.beginPath();
        ctx.moveTo(edge[0].sx, edge[0].sy);
        for (let i = 1; i < edge.length; i++) ctx.lineTo(edge[i].sx, edge[i].sy);
        for (let i = outer.length - 1; i >= 0; i--) ctx.lineTo(outer[i].sx, outer[i].sy);
        ctx.closePath();
        ctx.fillStyle = "rgba(170,176,186,0.35)";
        ctx.fill();
      }

      const zs = sampleZs(nearZ, farZ);

      const leftEdge: { x: number; y: number }[] = [];
      const rightEdge: { x: number; y: number }[] = [];

      for (const z of zs) {
        const cx = centerAtZ(z);
        const L = proj(cx - laneHalf, 0, z);
        const R = proj(cx + laneHalf, 0, z);
        const M = proj(cx, 0, z);
        if (M.sy < horizonY - 4) continue;
        leftEdge.push({ x: L.sx, y: L.sy });
        rightEdge.push({ x: R.sx, y: R.sy });
      }

      if (leftEdge.length >= 2) {
        ctx.beginPath();
        ctx.moveTo(leftEdge[0].x, leftEdge[0].y);
        for (let i = 1; i < leftEdge.length; i++) ctx.lineTo(leftEdge[i].x, leftEdge[i].y);
        for (let i = rightEdge.length - 1; i >= 0; i--) ctx.lineTo(rightEdge[i].x, rightEdge[i].y);
        ctx.closePath();
        const road = ctx.createLinearGradient(0, horizonY, 0, h);
        road.addColorStop(0, "rgba(96,104,118,0.26)");
        road.addColorStop(1, "rgba(52,58,70,0.52)");
        ctx.fillStyle = road;
        ctx.fill();

        // 边线：近粗远细，用米制半宽画成实心带，更像路缘标线
        const edgeHalf = 0.09;
        for (const side of [-1, 1] as const) {
          for (let i = 0; i < zs.length - 1; i++) {
            const z0 = zs[i];
            const z1 = zs[i + 1];
            if (z0 > 95) break;
            const cx0 = centerAtZ(z0);
            const cx1 = centerAtZ(z1);
            const x0 = cx0 + side * laneHalf;
            const x1 = cx1 + side * laneHalf;
            const a = proj(x0 - edgeHalf, 0.04, z0);
            const b = proj(x0 + edgeHalf, 0.04, z0);
            const c = proj(x1 + edgeHalf, 0.04, z1);
            const d = proj(x1 - edgeHalf, 0.04, z1);
            if (a.sy < horizonY - 2 && b.sy < horizonY - 2) continue;
            const fog = Math.max(0.35, 1 - z0 / 130);
            fillPoly([a, b, c, d], `rgba(245,248,255,${0.92 * fog})`);
          }
        }

        // 中间虚线：按真实标线尺度（约 6m 白 / 9m 空，宽约 15cm），透视四边形而非细描边
        const dashLen = 6;
        const gapLen = 9;
        const period = dashLen + gapLen;
        const midHalf = 0.075;
        const farMark = Math.min(farZ, 110);
        let along = Math.floor(travel / period) * period;
        const endAlong = travel + farMark + period;
        while (along < endAlong) {
          const z0 = along - travel;
          const z1 = along + dashLen - travel;
          along += period;
          const za = Math.max(nearZ, z0);
          const zb = Math.min(farMark, z1);
          if (zb - za < 0.45) continue;
          const segs = Math.max(3, Math.ceil((zb - za) / 2.2));
          for (let s = 0; s < segs; s++) {
            const t0 = za + ((zb - za) * s) / segs;
            const t1 = za + ((zb - za) * (s + 1)) / segs;
            const cx0 = centerAtZ(t0);
            const cx1 = centerAtZ(t1);
            const a = proj(cx0 - midHalf, 0.05, t0);
            const b = proj(cx0 + midHalf, 0.05, t0);
            const c = proj(cx1 + midHalf, 0.05, t1);
            const d = proj(cx1 - midHalf, 0.05, t1);
            if (a.sy < horizonY - 2 && b.sy < horizonY - 2) continue;
            const fog = Math.max(0.28, 1 - t0 / 125);
            fillPoly([a, b, c, d], `rgba(250,252,255,${0.95 * fog})`);
          }
        }
      }

      ctx.fillStyle = "rgba(70,76,90,0.16)";
      ctx.fillRect(0, horizonY - 0.5, w, 1);

      const vig = ctx.createRadialGradient(w * 0.5 + steerPx * 0.25, h * 0.66, h * 0.1, w * 0.5, h * 0.58, h * 0.88);
      vig.addColorStop(0, "rgba(20,24,32,0)");
      vig.addColorStop(1, "rgba(20,24,32,0.14)");
      ctx.fillStyle = vig;
      ctx.fillRect(0, 0, w, h);

      void spd;
    };

    const syncRoute = () => {
      const nav = useCabinStore.getState().vehicle?.navigation;
      const poly = (nav?.polyline || [])
        .map((p) => [Number(p[0]), Number(p[1])] as LngLat)
        .filter((p) => Number.isFinite(p[0]) && Number.isFinite(p[1]));
      // 导航与道路巡航走廊都跟折线；无折线才画直线
      if (poly.length < 2) {
        table = null;
        routeKey = "";
        bendTarget = [];
        travelDir = 1;
        return false;
      }
      const navigating = !!nav?.navigating;
      travelDir = navigating ? 1 : Number(nav?.cruise_dir || 1) < 0 ? -1 : 1;
      const key = routeFingerprint(poly);
      const serverProg = Math.max(0, Number(nav?.progress_m || 0));
      if (key !== routeKey) {
        routeKey = key;
        table = buildArcTable(poly);
        progressLocal = serverProg;
        progressVis = serverProg;
        hdgFilt = [];
        bendDisp = [];
        bldCx.clear();
      } else if (Math.abs(serverProg - progressLocal) > 220) {
        progressLocal = serverProg;
      }
      return true;
    };

    const tick = (now: number) => {
      if (!visible) return;
      const dt = Math.min(0.05, Math.max(0, (now - last) / 1000));
      last = now;

      const st = useCabinStore.getState();
      const demoGate = !String(st.userNickname || "").trim();
      const raw = Number(st.vehicle?.dynamics?.speed_kmh ?? 0);
      const gear = String(st.vehicle?.dynamics?.gear || "P").toUpperCase();
      const parked = !!st.vehicle?.dynamics?.parked;
      // 昵称门禁：直线巡航演示，不跟真实导航弯道
      const target = demoGate ? 48 : parked || gear === "P" ? 0 : Math.max(0, raw);
      const tau = target > speedSmooth ? 0.32 : 0.55;
      speedSmooth += (target - speedSmooth) * (1 - Math.exp(-dt / tau));
      if (speedSmooth < 0.12) speedSmooth = 0;

      if (demoGate) {
        table = null;
        routeKey = "";
        bendTarget = [];
        hdgFilt = [];
        if (speedSmooth > 0.2) travel += (speedSmooth / 3.6) * dt;
        lastDt = dt;
        smoothBend(dt);
        draw(speedSmooth);
        schedule(0);
        return;
      }

      const routeMode = syncRoute();
      const nav = st.vehicle?.navigation;
      const serverProg = Math.max(0, Number(nav?.progress_m || 0));

      if (routeMode && table) {
        const speedMps = (speedSmooth / 3.6) * (gear === "R" ? -1 : 1);
        progressLocal += speedMps * dt * travelDir;
        progressLocal += (serverProg - progressLocal) * (1 - Math.exp(-dt / 1.55));
        progressLocal = Math.max(0, Math.min(table.total, progressLocal));
        progressVis += (progressLocal - progressVis) * (1 - Math.exp(-dt / 0.2));
        progressVis = Math.max(0, Math.min(table.total, progressVis));
        bendTarget = sampleBend(progressVis, travelDir);
        travel += Math.abs(speedMps) * dt;
      } else {
        bendTarget = [];
        hdgFilt = [];
        if (speedSmooth > 0.2) travel += (speedSmooth / 3.6) * dt;
      }
      lastDt = dt;
      smoothBend(dt);

      const moving = speedSmooth > 0.2 || target > 0.2;
      draw(speedSmooth);
      schedule(moving || routeMode ? 0 : 160);
    };

    schedule(0);
    return () => {
      cancelAnimationFrame(raf);
      window.clearTimeout(timer);
      ro.disconnect();
      document.removeEventListener("visibilitychange", onVis);
    };
  }, []);

  return (
    <>
      <div className="cabin-atmosphere cabin-atmosphere--under" aria-hidden="true">
        <canvas ref={canvasRef} className="cabin-atmosphere-canvas" />
      </div>
      <div className="cabin-atmosphere cabin-atmosphere--over cabin-atmosphere--over-lite" aria-hidden="true" />
    </>
  );
}
