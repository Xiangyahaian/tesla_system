export const SEAT_IDS = [
  "front_left",
  "front_right",
  "rear_left",
  "rear_middle",
  "rear_right",
] as const;

export type SeatId = (typeof SEAT_IDS)[number];

export const SEAT_LABELS: Record<SeatId, string> = {
  front_left: "主驾",
  front_right: "副驾",
  rear_left: "左后",
  rear_middle: "中后",
  rear_right: "右后",
};

export const DEFAULT_SEAT: SeatId = "front_left";

export function isSeatId(v: unknown): v is SeatId {
  return typeof v === "string" && (SEAT_IDS as readonly string[]).includes(v);
}
