import { useLocation } from "react-router-dom";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { TopNav } from "@/components/layout/TopNav";
import { CabinAtmosphere } from "@/components/layout/CabinAtmosphere";
import { ConfirmGate } from "@/components/chat/ConfirmGate";
import { GlobalComposer } from "@/components/common/GlobalComposer";
import { UserGate } from "@/components/auth/UserGate";
import { SessionHistoryDrawer } from "@/components/session/SessionHistoryDrawer";
import { CabinRuntimeProvider, useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";
import { loginUser } from "@/lib/api";
import { DrivePage } from "@/pages/DrivePage";
import { AppsPage } from "@/pages/AppsPage";
import { AgentPage } from "@/pages/AgentPage";
import { SettingsPage } from "@/pages/SettingsPage";

function KeepAlivePages() {
  const { pathname } = useLocation();
  const path = pathname === "" ? "/" : pathname;
  const prev = useRef(path);
  const bumpMapEpoch = useCabinStore((s) => s.bumpMapEpoch);

  useEffect(() => {
    const nowDrive = path === "/";
    const wasDrive = prev.current === "/";
    prev.current = path;
    if (nowDrive && !wasDrive) {
      bumpMapEpoch();
      window.setTimeout(() => window.dispatchEvent(new Event("resize")), 40);
    }
  }, [bumpMapEpoch, path]);

  const slots: Array<{ id: string; match: boolean; node: ReactNode }> = [
    { id: "drive", match: path === "/", node: <DrivePage /> },
    { id: "apps", match: path === "/apps", node: <AppsPage /> },
    { id: "agent", match: path === "/agent", node: <AgentPage /> },
    { id: "settings", match: path === "/settings", node: <SettingsPage /> },
  ];

  return (
    <>
      {slots.map((slot) => (
        <div
          key={slot.id}
          className={`cabin-keep-alive${slot.match ? " is-active" : ""}`}
          aria-hidden={!slot.match}
          inert={!slot.match || undefined}
        >
          {slot.node}
        </div>
      ))}
    </>
  );
}

function ConfirmBridge() {
  return <ConfirmGate />;
}

function ComposerBridge() {
  const loc = useLocation();
  if (loc.pathname === "/" || loc.pathname === "") return null;
  return <GlobalComposer />;
}

function CabinShell() {
  const userNickname = useCabinStore((s) => s.userNickname);
  const sessionId = useCabinStore((s) => s.sessionId);
  const authSessionId = useCabinStore((s) => s.authSessionId);
  const setUser = useCabinStore((s) => s.setUser);
  const { refreshState, reloadMessages } = useCabinRuntime();
  const [ready, setReady] = useState(!!userNickname && !!sessionId);

  useEffect(() => {
    if (!userNickname) {
      setReady(false);
      return;
    }
    // 登录身份必须是 u_* 主会话；当前查看的可以是自己新建的 s* 会话
    if (!authSessionId || !authSessionId.startsWith("u_")) {
      void loginUser(userNickname)
        .then((r) => {
          setUser(r.nickname, r.session_id, r.is_admin);
          setReady(true);
        })
        .catch(() => setReady(false));
      return;
    }
    setReady(true);
  }, [userNickname, authSessionId, setUser]);

  if (!userNickname || !ready) {
    return (
      <UserGate
        onEntered={() => {
          setReady(true);
          void refreshState();
          void reloadMessages();
        }}
      />
    );
  }

  return (
    <div className="cabin-frame">
      <TopNav />
      <div className="cabin-stage-body">
        <KeepAlivePages />
      </div>
      <SessionHistoryDrawer />
      <ConfirmBridge />
      <ComposerBridge />
    </div>
  );
}

function CabinRoot() {
  const atmosphereEnabled = useCabinStore((s) => s.atmosphereEnabled);
  return (
    <div className={`cabin-root${atmosphereEnabled ? "" : " cabin-root--plain"}`}>
      {atmosphereEnabled ? <CabinAtmosphere /> : null}
      <CabinShell />
    </div>
  );
}

export function CabinFrame() {
  return (
    <CabinRuntimeProvider>
      <CabinRoot />
    </CabinRuntimeProvider>
  );
}
