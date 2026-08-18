import { motion } from "framer-motion";

/** Compact climate indicator — solid tones, no gradient chrome */
export function ClimateRing({
  power,
  temp,
  fan,
}: {
  power?: boolean;
  temp?: number;
  fan?: number;
}) {
  const t = temp ?? 24;
  const f = fan ?? 0;
  return (
    <div className="climate-ring" aria-hidden={!power}>
      <motion.div
        className={`climate-disc${power ? " on" : ""}`}
        animate={{ scale: power ? 1 : 0.96 }}
        transition={{ duration: 0.35, ease: [0.22, 1, 0.36, 1] }}
      >
        <div className="climate-temp">{power ? `${t}°` : "OFF"}</div>
        <div className="climate-fan">{power ? `FAN ${f}` : "CLIMATE"}</div>
      </motion.div>
    </div>
  );
}
