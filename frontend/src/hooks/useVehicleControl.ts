import { useCallback, useRef, useState } from "react";
import { executeControl, tickDynamics } from "@/lib/api";
import { useCabinStore } from "@/store/cabinStore";
import type { CabinStateSnapshot } from "@/lib/types";

type ControlResult = Awaited<ReturnType<typeof executeControl>>;

/** 中控确认弹层的 Promise 桥（不进 zustand，避免序列化） */
let hmiConfirmResolver: ((ok: boolean) => void) | null = null;

export function resolveHmiConfirm(ok: boolean) {
  const resolve = hmiConfirmResolver;
  hmiConfirmResolver = null;
  useCabinStore.getState().setHmiConfirm(null);
  resolve?.(ok);
}

function askHmiConfirm(message: string, summary?: string): Promise<boolean> {
  useCabinStore.getState().setHmiConfirm({ message, summary });
  return new Promise((resolve) => {
    hmiConfirmResolver = resolve;
  });
}

/** 中控直接控车 + 动力学节拍 */
export function useVehicleControl() {
  const sessionId = useCabinStore((s) => s.sessionId);
  const setVehicle = useCabinStore((s) => s.setVehicle);
  const setError = useCabinStore((s) => s.setError);
  const busyRef = useRef(false);
  const [busy, setBusy] = useState(false);
  const [pendingLabel, setPendingLabel] = useState<string | null>(null);

  const applyState = useCallback(
    (state: CabinStateSnapshot | null | undefined) => {
      if (state) setVehicle(state);
    },
    [setVehicle],
  );

  /** 滑条跟手：同工具只保留最新参数，不占全局 busy，避免拖动被丢掉 */
  const liveInflight = useRef(new Set<string>());
  const livePending = useRef(new Map<string, Record<string, unknown>>());

  const pumpLive = useCallback(
    async (tool: string) => {
      if (!sessionId || liveInflight.current.has(tool)) return;
      liveInflight.current.add(tool);
      try {
        while (livePending.current.has(tool)) {
          const args = livePending.current.get(tool)!;
          livePending.current.delete(tool);
          try {
            const res = await executeControl(tool, args, sessionId);
            if (!res.ok) {
              setError(res.message || res.error || "操作失败");
            } else {
              applyState(res.state);
              setError(null);
            }
          } catch (e) {
            setError(e instanceof Error ? e.message : "控车失败");
          }
        }
      } finally {
        liveInflight.current.delete(tool);
        if (livePending.current.has(tool)) void pumpLive(tool);
      }
    },
    [applyState, sessionId, setError],
  );

  const run = useCallback(
    async (
      tool: string,
      args: Record<string, unknown> = {},
      opts?: { confirmHigh?: boolean; label?: string; live?: boolean },
    ): Promise<ControlResult | null> => {
      if (!sessionId) {
        setError("请先登录昵称");
        return null;
      }
      if (opts?.live) {
        livePending.current.set(tool, args);
        void pumpLive(tool);
        return null;
      }
      if (busyRef.current) return null;
      if (opts?.confirmHigh) {
        const ok = await askHmiConfirm(
          opts.label || "该操作涉及车辆安全，确认执行？",
          "确认后将立即作用于当前车辆状态。",
        );
        if (!ok) return null;
      }
      busyRef.current = true;
      setBusy(true);
      setPendingLabel(opts?.label?.replace(/[？?]$/, "") || tool);
      try {
        const res = await executeControl(tool, args, sessionId);
        if (!res.ok) {
          setError(res.message || res.error || "操作失败");
          return res;
        }
        applyState(res.state);
        setError(null);
        return res;
      } catch (e) {
        setError(e instanceof Error ? e.message : "控车失败");
        return null;
      } finally {
        busyRef.current = false;
        setBusy(false);
        setPendingLabel(null);
      }
    },
    [applyState, pumpLive, sessionId, setError],
  );

  const tickInflight = useRef(false);
  const lastTickAt = useRef(0);

  const tick = useCallback(async (signal?: AbortSignal) => {
    if (!sessionId || tickInflight.current || signal?.aborted) return;
    const store = useCabinStore.getState();
    if (store.resetInFlight) return;
    const now = performance.now();
    const dt = lastTickAt.current
      ? Math.min(1, Math.max(0.08, (now - lastTickAt.current) / 1000))
      : 0.25;
    lastTickAt.current = now;
    tickInflight.current = true;
    const epoch = store.vehicleEpoch;
    try {
      const res = await tickDynamics(sessionId, dt, signal);
      const after = useCabinStore.getState();
      if (after.resetInFlight || after.vehicleEpoch !== epoch) return;
      applyState(res.state);
    } catch (e) {
      if (e instanceof DOMException && e.name === "AbortError") return;
      /* 静默：后端未重启时不刷屏 */
    } finally {
      tickInflight.current = false;
    }
  }, [applyState, sessionId]);

  return { run, tick, applyState, busy, pendingLabel };
}
