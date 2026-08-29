export const ADMIN_NICKNAME = "象牙海岸";

export function isAdminNickname(nickname?: string | null): boolean {
  return (nickname || "").trim() === ADMIN_NICKNAME;
}
