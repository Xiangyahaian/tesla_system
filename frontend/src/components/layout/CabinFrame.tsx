import { Outlet, useLocation } from "react-router-dom";
import { useEffect, useState } from "react";
import { TopNav } from "@/components/layout/TopNav";
import { ConfirmGate } from "@/components/chat/ConfirmGate";
import { GlobalComposer } from "@/components/common/GlobalComposer";
import { UserGate } from "@/components/auth/UserGate";
import { CabinRuntimeProvider, useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";
import { loginUser } from "@/lib/api";

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
  const setUser = useCabinStore((s) => s.setUser);
  const { refreshState, reloadMessages } = useCabinRuntime();
  const [ready, setReady] = useState(!!userNickname && !!sessionId);

  useEffect(() => {
    if (!userNickname) {
      setReady(false);
      return;
    }
    // 旧缓存可能仍是 default：按昵称重新绑定独立用户 session
    if (!sessionId || !sessionId.startsWith("u_")) {
      void loginUser(userNickname)
        .then((r) => {
          setUser(r.nickname, r.session_id);
          setReady(true);
        })
        .catch(() => setReady(false));
      return;
    }
    setReady(true);
  }, [userNickname, sessionId, setUser]);

  useEffect(() => {
    if (!ready || !sessionId) return;
    void refreshState();
    void reloadMessages();
  }, [ready, sessionId, refreshState, reloadMessages]);

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
        <Outlet />
      </div>
      <ConfirmBridge />
      <ComposerBridge />
    </div>
  );
}

export function CabinFrame() {
  return (
    <CabinRuntimeProvider>
      <CabinShell />
    </CabinRuntimeProvider>
  );
}
