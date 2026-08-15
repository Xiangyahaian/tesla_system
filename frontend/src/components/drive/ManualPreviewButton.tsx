/** 打开用户手册（新标签页） */
export function ManualPreviewButton({ className = "" }: { className?: string }) {
  return (
    <a
      className={`btn ghost compact manual-btn${className ? ` ${className}` : ""}`}
      href="/manual"
      target="_blank"
      rel="noreferrer"
    >
      用户手册
    </a>
  );
}
