/** 随机无意义两字中文昵称 */

const POOL = Array.from(
  new Set(
    (
      "覃昱琛祁褚靳缪嵇裴翟佟佘闵邬岑聂甘卜蔺裘珩琨琰琬柘柚枳枸柰栖澜澈溯玄曜凌巽攸芮芃弋珞砚湫渚浔澹桓璟翊昊垚" +
      "淇泠砚珞弋芃芮攸巽凌曜玄溯澈澜栖柰枸枳柚柘琬琰琨珩裘蔺卜甘聂岑邬闵佘佟翟裴嵇缪靳褚祁琛昱覃昭予"
    ).split(""),
  ),
).filter((c) => c.trim());

function pickChar(): string {
  return POOL[Math.floor(Math.random() * POOL.length)]!;
}

/** 生成无意义两字名，如「泠砚」「柘弋」 */
export function randomNickname(): string {
  let a = pickChar();
  let b = pickChar();
  let guard = 0;
  while (b === a && guard++ < 8) b = pickChar();
  return `${a}${b}`;
}
