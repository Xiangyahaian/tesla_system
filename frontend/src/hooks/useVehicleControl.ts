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

  const run = useCallback(
    async (
      tool: string,
      args: Record<string, unknown> = {},
      opts?: { confirmHigh?: boolean; label?: string },
    ): Promise<ControlResult | null> => {
      if (busyRef.current) return null;
      if (!sessionId) {
        setError("请先登录昵称");
        return null;
      }
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
    [applyState, sessionId, setError],
  );

  const tick = useCallback(async () => {
    if (!sessionId) return;
    const store = useCabinStore.getState();
    if (store.resetInFlight) return;
    const epoch = store.vehicleEpoch;
    try {
      const res = await tickDynamics(sessionId, 0.25);
      const now = useCabinStore.getState();
      if (now.resetInFlight || now.vehicleEpoch !== epoch) return;
      applyState(res.state);
    } catch {
      /* 静默：后端未重启时不刷屏 */
    }
  }, [applyState, sessionId]);

  return { run, tick, applyState, busy, pendingLabel };
}
