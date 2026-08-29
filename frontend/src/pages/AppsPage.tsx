import { useEffect, useMemo, useState } from "react";
import { motion } from "framer-motion";
import { fetchApps } from "@/lib/api";
import { useCabinRuntime } from "@/hooks/useCabinRuntime";
import { useCabinStore } from "@/store/cabinStore";
import { TopBar } from "@/components/layout/TopBar";

const CAT_LABEL: Record<string, string> = {
  system: "系统",
  office: "办公",
  social: "社交",
  travel: "出行",
  life: "生活",
  finance: "金融",
  shopping: "购物",
  media: "影音",
  other: "其他",
};

export function AppsPage() {
  const [apps, setApps] = useState<{ name: string; category: string; aliases?: string[] }[]>([]);
  const [categories, setCategories] = useState<string[]>([]);
  const [filter, setFilter] = useState<string>("all");
  const [err, setErr] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const { runQuery } = useCabinRuntime();
  const busy = useCabinStore((s) => s.busy);
  const active = useCabinStore((s) => s.vehicle?.apps?.active);

  useEffect(() => {
    void (async () => {
      try {
        const data = await fetchApps();
        setApps(data.apps);
        setCategories(data.categories);
      } catch (e) {
        setErr(e instanceof Error ? e.message : "加载失败");
      } finally {
        setLoading(false);
      }
    })();
  }, []);

  const visible = useMemo(
    () => (filter === "all" ? apps : apps.filter((a) => a.category === filter)),
    [apps, filter],
  );

  return (
    <div className="page-apps">
      <TopBar title="车机应用" subtitle="点击应用将通过语音助手打开或关闭" />
      <div className="apps-body">
        <div className="apps-toolbar">
          <button
            type="button"
            className={`filter-pill${filter === "all" ? " active" : ""}`}
            onClick={() => setFilter("all")}
          >
            全部 {apps.length}
          </button>
          {categories.map((c) => (
            <button
              key={c}
              type="button"
              className={`filter-pill${filter === c ? " active" : ""}`}
              onClick={() => setFilter(c)}
            >
              {CAT_LABEL[c] || c}
            </button>
          ))}
        </div>
        {err ? <p className="page-error">{err}</p> : null}
        {loading ? <p className="empty-hint">正在加载应用…</p> : null}
        {busy ? <p className="empty-hint">助手正在执行驾驶页指令，应用可浏览，完成前暂不能点开。</p> : null}
        <div className="apps-grid">
          {visible.map((app, i) => {
            const isActive = active === app.name;
            return (
              <motion.button
                key={app.name}
                type="button"
                className={`app-tile${isActive ? " active" : ""}`}
                disabled={busy}
                initial={{ opacity: 0, y: 10 }}
                animate={{ opacity: 1, y: 0 }}
                transition={{ delay: Math.min(i * 0.02, 0.4), duration: 0.28 }}
                onClick={() => void runQuery(isActive ? `关闭${app.name}` : `打开${app.name}`)}
              >
                <span className="app-glyph">{app.name.slice(0, 1)}</span>
                <span className="app-name">{app.name}</span>
                <span className="app-cat">{CAT_LABEL[app.category] || app.category}</span>
                {isActive ? <span className="app-live">前台</span> : null}
              </motion.button>
            );
          })}
        </div>
        <p className="apps-note">点击应用会交给助手执行打开/关闭，驾驶页右侧中控会同步前台应用。</p>
      </div>
    </div>
  );
}
