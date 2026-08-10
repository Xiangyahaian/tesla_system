import { Outlet } from "react-router-dom";
import { SideRail } from "@/components/layout/SideRail";
import { StatusStrip } from "@/components/layout/StatusStrip";
import { ConfirmGate } from "@/components/chat/ConfirmGate";
import { CabinRuntimeProvider, useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";

function ConfirmBridge() {
  const { runQuery } = useCabinRuntime();
  const setConfirm = useCabinStore((s) => s.setConfirm);
  return (
    <ConfirmGate
      onConfirm={() => void runQuery("确认", true)}
      onCancel={() => {
        setConfirm(null);
        void runQuery("取消", false);
      }}
    />
  );
}

export function CabinFrame() {
  return (
    <CabinRuntimeProvider>
      <div className="cabin-frame">
        <div className="cabin-grain" aria-hidden />
        <SideRail />
        <div className="cabin-stage">
          <StatusStrip />
          <div className="cabin-stage-body">
            <Outlet />
          </div>
        </div>
        <ConfirmBridge />
      </div>
    </CabinRuntimeProvider>
  );
}
