const DEMOS = [
  { label: "空调 + 音乐", query: "打开空调并播放周杰伦的晴天" },
  { label: "音量指代", query: "现在音量多少" },
  { label: "再小一点", query: "小一点" },
  { label: "安全确认", query: "打开后备箱" },
  { label: "手册问答", query: "自动泊车怎么用" },
  { label: "打开飞书", query: "打开飞书" },
];

export function QuickChips({
  onPick,
  disabled,
}: {
  onPick: (q: string) => void;
  disabled?: boolean;
}) {
  return (
    <div className="quick-chips" aria-label="演示指令">
      {DEMOS.map((d) => (
        <button
          key={d.query}
          type="button"
          className="chip"
          disabled={disabled}
          onClick={() => onPick(d.query)}
        >
          {d.label}
        </button>
      ))}
    </div>
  );
}
