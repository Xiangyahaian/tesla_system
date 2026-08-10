import { TopBar } from "@/components/layout/TopBar";
import { VoiceOrb } from "@/components/voice/VoiceOrb";
import { ChatStream } from "@/components/chat/ChatStream";
import { VehicleHud } from "@/components/hud/VehicleHud";
import { QuickChips } from "@/components/drive/QuickChips";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";

export function DrivePage() {
  const { draft, setDraft, onSubmit, onHoldStart, onHoldEnd, runQuery } = useCabinRuntime();
  const busy = useCabinStore((s) => s.busy);

  return (
    <div className="page-drive">
      <TopBar title="CABIN" subtitle="Intelligent Cockpit · Drive" />
      <div className="cabin-main">
        <section className="cabin-center">
          <VoiceOrb onHoldStart={onHoldStart} onHoldEnd={onHoldEnd} />
          <QuickChips onPick={(q) => void runQuery(q)} disabled={busy} />
          <ChatStream />
          <form className="composer" onSubmit={onSubmit}>
            <textarea
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              placeholder="输入指令，或按住声纹球说话…"
              rows={2}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  onSubmit(e);
                }
              }}
            />
            <button type="submit" className="btn primary" disabled={busy || !draft.trim()}>
              发送
            </button>
          </form>
        </section>
        <VehicleHud />
      </div>
    </div>
  );
}
