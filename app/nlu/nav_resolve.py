# -*- coding: utf-8 -*-
"""导航澄清选择器（系统性门禁）。

有 nav_candidates 时：用户话只在「当前候选集合」里解释，
禁止再拿改写后的模糊地名去全市检索——那是二次歧义的根因。
口语简称/方位/错别字由 LLM 在候选内判定；仅序号、全称等走规则快路径。
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    from app.llm.client import LLMClient

_log = logging.getLogger(__name__)

NAV_SELECT_SYSTEM = """你是车载导航澄清助手。用户可能在多个地点候选中做口语选择，
也可能已经换题或不想选——此时必须 action=clear，禁止用 repeat 逼选。
只能依据给定候选列表判断，禁止编造地点或候选以外的地址。
只输出一个 JSON 对象，不要 markdown、不要解释。"""


@dataclass
class NavSelection:
    """resolve 结果。"""

    action: str  # navigate | narrow | repeat | clear | new_destination
    destination: str = ""
    location: str = ""
    candidates: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""
    used_llm: bool = False


def _extract_json(text: str) -> Dict[str, Any]:
    text = (text or "").strip()
    try:
        return json.loads(text)
    except Exception:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return {}
    return {}


def _norm_candidates(candidates: Optional[list]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i, c in enumerate(candidates or []):
        if not isinstance(c, dict):
            continue
        name = str(c.get("name") or "").strip()
        if not name:
            continue
        item = dict(c)
        item["name"] = name
        if item.get("index") is None:
            item["index"] = i + 1
        out.append(item)
    return out


def _strip_shell(text: str) -> str:
    t = (text or "").strip()
    t = re.sub(r"^(我?想)?(去|到|导航到|导航去|选|要|走)\s*", "", t).strip()
    t = re.sub(r"[吧啊呀哦呢嘛的地～~。.!！？?\s]+$", "", t).strip()
    return t or (text or "").strip()


def _is_cancel(text: str) -> bool:
    t = (text or "").strip()
    return bool(
        re.search(
            r"^(取消|算了|不用了|不导航|别导了|先别|不要了|我不选|不选了|先不选|"
            r"都不要选|不挑了|别让我选|不选)(导航|了|吧|啊|呀)?$|"
            r"取消导航|不走了|不去了|我不导航|先不导航",
            t,
        )
    )


def _is_reject_current_candidates(text: str) -> bool:
    """明确否定当前候选列表（不是选定其中某一个）。"""
    t = (text or "").strip()
    if not t:
        return False
    return bool(
        re.search(
            r"(都\s*(不想要|不要|不是|不对|别去|不要了)|"
            r"这些?\s*(都)?\s*(不要|不行|不对|别|不选)|"
            r"换\s*(一批|别的|其他|其它)|"
            r"我不\s*选|不\s*选\s*了|先\s*不\s*选|别\s*让\s*我\s*选|"
            r"不想\s*(从)?\s*(里面|里头|这些|列表)?\s*(挑|选)|"
            r"^(不行|不对|不是|都不是|都不要|我不选|不选)[啊呀吧呢噢哦了～~。.!！？?\s]*$)",
            t,
        )
    )


def _has_selection_cues(text: str) -> bool:
    """仍像在当前列表里挑点（序号 / 那家 / 这家）。"""
    t = (text or "").strip()
    if not t:
        return False
    return bool(
        re.search(
            r"(第\s*[一二三四五六七八九\d]+\s*(个|项|处|号|家)|"
            r"那家|这家|上面那|下面那|刚才那|第一个|第二个|第三个|第四个|"
            r"^[1-8]$)",
            t,
        )
    )


def _candidate_name_overlap(text: str, cands: List[Dict[str, Any]]) -> bool:
    """用户话与候选店名有实质重合（短虚词不算）。"""
    t = re.sub(r"[的了呢吗啊呀吧嘛哦噢？?。.!！\s]+", "", (text or "").strip())
    if len(t) < 2:
        return False
    for c in cands:
        name = str(c.get("name") or "")
        if not name:
            continue
        if name in text or (len(t) >= 4 and t in name):
            return True
        hans = [ch for ch in t if "\u4e00" <= ch <= "\u9fff"]
        if len(hans) >= 3:
            shared = sum(1 for ch in hans if ch in name)
            if shared >= max(3, len(hans) // 2):
                return True
    return False


def _is_explicit_new_destination(text: str, core: str, cands: List[Dict[str, Any]]) -> bool:
    """用户明确换目的地 / 开新导航，而不是在点候选。"""
    # 否定当前候选并带出新意向
    if _is_reject_current_candidates(text) and re.search(
        r"(我想去|带我去|导航到|导航去|去|到|想去).{1,}", text
    ):
        return True
    if re.search(r"(换个|换一|别的地方|其他地方|重新导航|不要这|不是这|换目的地|换地方)", text):
        return True
    # 「导航到/带我去 + 较长新地名」且与现有候选几乎无重合 → 新检索
    m = re.search(
        r"(?:帮我|给我|请)?(?:导航到|导航去|开导航到|开导航去|带我去|我想去)\s*(.+)$",
        text,
    )
    if not m:
        return False
    dest = _strip_shell(m.group(1))
    if len(dest) < 2:
        return False
    # 新地名若已能在候选里唯一命中，仍算选择，不算新开
    filtered = _filter_by_constraints(dest, cands)
    if len(filtered) == 1:
        return False
    if any(dest == str(c.get("name") or "") or dest in str(c.get("name") or "") for c in cands):
        return False
    # 与任一候选共享很少汉字 → 新意图
    for c in cands:
        name = str(c.get("name") or "")
        shared = sum(1 for ch in dest if "\u4e00" <= ch <= "\u9fff" and ch in name)
        if shared >= max(2, len([x for x in dest if "\u4e00" <= x <= "\u9fff"]) // 2):
            return False
    return len(dest) >= 2


def _constraint_tokens(core: str) -> List[str]:
    """把用户简称拆成必须命中的约束 token（通用，不绑死地铁站）。"""
    s = (core or "").strip()
    if not s:
        return []
    tokens: List[str] = []
    # 出入口：A口 / B南口 / 3号口
    for m in re.finditer(r"([A-Za-z])\s*(?:号)?\s*(南|北|东|西)?\s*口", s):
        letter = m.group(1).upper()
        side = m.group(2) or ""
        tokens.append(letter)  # 字母必须出现
        if side:
            tokens.append(side + "口")
        else:
            tokens.append("口")
        s = s[: m.start()] + " " + s[m.end() :]
    for m in re.finditer(r"([0-9一二三四五六七八九十]+)\s*号?\s*口", s):
        tokens.append(m.group(0).replace(" ", ""))
        s = s[: m.start()] + " " + s[m.end() :]
    for side in ("南口", "北口", "东口", "西口", "入口", "出口"):
        if side in s:
            tokens.append(side)
            s = s.replace(side, " ")
    # 拉丁/数字串
    for m in re.finditer(r"[A-Za-z0-9]+", s):
        tokens.append(m.group(0).upper())
        s = s[: m.start()] + " " + s[m.end() :]
    # 剩余汉字：整段作为子串约束（短词）；较长则拆成 2-gram 弱约束改用整段
    han = re.sub(r"\s+", "", s)
    han = re.sub(r"[的了呢吗啊呀吧]", "", han)
    if han:
        tokens.append(han)
    # 去重保序
    seen = set()
    out: List[str] = []
    for t in tokens:
        t = t.strip()
        if not t or t in seen:
            continue
        seen.add(t)
        out.append(t)
    return out


def _name_satisfies(name: str, token: str) -> bool:
    if not token:
        return True
    n = name or ""
    t = token
    if re.fullmatch(r"[A-Z0-9]+", t):
        return bool(re.search(re.escape(t), n, re.I))
    if t == "口":
        return "口" in n
    # 南口 等
    if t in n:
        return True
    # 用户说 B口 抽成 B+口：字母已单独校验；「口」过宽时若同时有字母约束，允许 南口/北口 等含口字样
    if t == "口" and re.search(r"[A-Za-z0-9].*口|口", n):
        return True
    return False


def _filter_by_constraints(core: str, cands: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    tokens = _constraint_tokens(core)
    if not tokens:
        return []
    hits: List[Dict[str, Any]] = []
    for c in cands:
        name = str(c.get("name") or "")
        if all(_name_satisfies(name, t) for t in tokens):
            hits.append(c)
    return hits


def _index_pick(text: str, cands: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """仅识别明确序号，禁止把「一下/一样」里的「一」当成第 1 个。"""
    t = (text or "").strip()
    if not t:
        return None
    if re.fullmatch(r"[1-4]", t):
        n = int(t)
        return cands[n - 1] if 1 <= n <= len(cands) else None
    # 第N个 / 选第N / 第N处 / N号（汉字或数字，且必须有序数语境）
    m = re.search(
        r"(?:选\s*)?(?:第\s*)([1-4一二两三四五六七八九])\s*(?:个|项|处|号|家)?|"
        r"(?:选\s*)([1-4])\s*(?:个|项|处|号|家)",
        t,
    )
    if not m:
        return None
    raw = m.group(1) or m.group(2) or ""
    idx_map = {
        "1": 1,
        "2": 2,
        "3": 3,
        "4": 4,
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
    }
    n = idx_map.get(str(raw), 0)
    if 1 <= n <= len(cands):
        return cands[n - 1]
    return None


def _score(core: str, name: str) -> float:
    if not core or not name:
        return 0.0
    if core == name:
        return 100.0
    if name in core:
        return 92.0
    if core in name:
        return 88.0 + min(8.0, len(core) * 0.4)
    tokens = _constraint_tokens(core)
    if tokens and all(_name_satisfies(name, t) for t in tokens):
        # 约束全满足：按 token 信息量给分
        return 70.0 + min(20.0, sum(len(t) for t in tokens) * 2.0)
    # 汉字重叠
    hans = [ch for ch in core if "\u4e00" <= ch <= "\u9fff"]
    if not hans:
        return 0.0
    shared = sum(1 for ch in hans if ch in name)
    ratio = shared / max(1, len(hans))
    if ratio >= 0.75 and shared >= 2:
        return 40.0 + 30.0 * ratio
    return 0.0


def _is_off_topic_from_nav(text: str, cands: Optional[List[Dict[str, Any]]] = None) -> bool:
    """明显换题 / 拒绝选点 / 问无关事 → 清掉导航候选，回正常意图识别。"""
    t = (text or "").strip()
    if not t:
        return False
    # 若仍在谈「第几个/那家店」则不算换题
    if _has_selection_cues(t):
        return False
    if re.search(
        r"(空调|温度|制热|制冷|座椅|车窗|天窗|氛围灯|阅读灯|放首歌|下一首|暂停|继续播放|"
        r"音量|打开微信|打开地图|锁车|解锁|后备箱|哨兵|玩具箱|用户手册|"
        r"怎么用|如何|为什么|讲个笑话|你好|谢谢|几点了|"
        r"网上\s*搜|搜一下|百度|谷歌|google|网页搜|搜索一下|"
        r"好玩|有什么好玩|推荐一下|介绍一下)",
        t,
        re.I,
    ):
        return True
    # 身份记忆 / 家 / 反问助手 —— 典型「不是在选列表」
    if re.search(
        r"((我的)?家\s*(在哪|在什么地方|在哪里|哪里)|"
        r"你知道我(的)?家|"
        r"我是说你|"
        r"你知道.{0,16}(吗|么)|"
        r"记得我|"
        r"我叫什么|"
        r"我的公司(在哪|叫什么)|"
        r"你记(得|住)我)",
        t,
    ):
        return True
    # 无选点线索、与候选几乎无重合，且是疑问/换话题陈述 → 视为离题
    if cands is not None and not _candidate_name_overlap(t, cands):
        if re.search(r"[吗呢？?]|我是说|我想问|换个话题|先别导|先不说导航", t):
            return True
    return False


def _force_clear_mistaken_repeat(query: str, cands: List[Dict[str, Any]]) -> bool:
    """LLM 误判 repeat 时的安全网：拒绝选点或离题必须放行。"""
    t = (query or "").strip()
    if not t:
        return False
    if _is_cancel(t) or _is_reject_current_candidates(t):
        return True
    if _is_off_topic_from_nav(t, cands):
        return True
    if _has_selection_cues(t) or _candidate_name_overlap(t, cands):
        return False
    # 短句否定选点 / 拒绝从列表挑
    if re.search(
        r"不选|不要选|别选|不挑|不想\s*(选|挑)|从\s*(里面|里头|列表|这些)\s*.{0,4}(挑|选)|"
        r"随便吧|都行吧|无所谓",
        t,
    ):
        return True
    return False


def _resolve_nav_selection_rules(query: str, cands: List[Dict[str, Any]]) -> Optional[NavSelection]:
    """仅保留极明确的规则快路径；口语简称一律交给 LLM。"""
    text = (query or "").strip()
    if not text or not cands:
        return NavSelection(action="clear", reason="无候选")

    if _is_cancel(text):
        return NavSelection(action="clear", reason="用户取消")

    if _is_off_topic_from_nav(text, cands):
        return NavSelection(action="clear", reason="用户换题，释放导航候选")

    core = _strip_shell(text)

    if _is_explicit_new_destination(text, core, cands):
        return NavSelection(action="new_destination", reason="用户换新目的地")

    if _is_reject_current_candidates(text):
        # 否定当前列表但未给出新地点 → 释放候选，让后续 NLU/闲聊接管
        return NavSelection(action="clear", reason="用户否定当前候选")

    picked = _index_pick(text, cands)
    if picked is not None:
        return NavSelection(
            action="navigate",
            destination=str(picked["name"]),
            location=str(picked.get("location") or ""),
            reason="序号选择",
        )

    for c in cands:
        name = str(c["name"])
        # 必须是全称点名，禁止短子串误伤
        if name and len(name) >= 4 and (name == core or name in text):
            return NavSelection(
                action="navigate",
                destination=name,
                location=str(c.get("location") or ""),
                reason="点名全称",
            )
    return None


def _llm_resolve_nav_selection(
    llm: "LLMClient",
    query: str,
    cands: List[Dict[str, Any]],
    *,
    query_label: str = "",
) -> Optional[NavSelection]:
    """LLM 在候选集合内解释用户口语（简称/方位/错别字）。"""
    lines: List[str] = []
    by_index: Dict[int, Dict[str, Any]] = {}
    for c in cands:
        idx = int(c.get("index") or (len(by_index) + 1))
        by_index[idx] = c
        name = str(c.get("name") or "").strip()
        addr = str(c.get("address") or "").strip()
        line = f"{idx}. {name}"
        if addr:
            line += f"（{addr}）"
        lines.append(line)

    user = (
        f"原搜索词：{query_label or '目的地'}\n"
        f"候选列表（只能从中选，禁止编造）：\n"
        + "\n".join(lines)
        + f"\n\n用户刚才说：「{query}」\n\n"
        "请判断用户意图，输出 JSON：\n"
        '{"action":"navigate|narrow|repeat|clear|new_destination","index":0,"indices":[],"reason":""}\n\n'
        "规则：\n"
        "- navigate：用户明确选定某一个候选时，index 为候选序号（从 1 开始）\n"
        "- narrow：仍含糊但可缩小范围，indices 为候选序号列表\n"
        "- repeat：仅当用户**仍在当前列表里选点**但说得不够清楚时才用；"
        "禁止用 repeat 逼用户必须选一个\n"
        "- clear：下列情况必须 clear（释放候选，让上层重新做意图识别），禁止 sticky 选点：\n"
        "  · 拒绝选点：「我不选」「不选了」「算了」「都不要」\n"
        "  · 换题/无关：「家在哪里」「你知道我的家吗」「打开空调」「放首歌」「手册怎么用」\n"
        "  · 上网搜索/攻略：「网上搜一下」「好玩的有吗你去搜」\n"
        "  · 用户话与候选几乎无关、明显不是在挑店名\n"
        "- new_destination：否定当前候选并给出新地点（如「都不想要，我想去故宫边上」）\n"
        "- 禁止把「一下/一样/一会儿」里的「一」当成第 1 个候选\n"
        "- 口语简称、错别字、方位词应结合原搜索词与常识匹配\n"
        "- index 为 0 表示不是 navigate；indices 为空表示不是 narrow"
    )
    try:
        raw = llm.chat(NAV_SELECT_SYSTEM, user, temperature=0.1, retries=1)
        obj = _extract_json(raw)
    except Exception as e:
        _log.warning("nav llm resolve failed: %s", e)
        return None

    action = str(obj.get("action") or "").strip().lower()
    reason = str(obj.get("reason") or "LLM判定").strip() or "LLM判定"

    if action == "clear":
        return NavSelection(action="clear", reason=f"LLM·{reason}", used_llm=True)
    if action == "new_destination":
        return NavSelection(action="new_destination", reason=f"LLM·{reason}", used_llm=True)

    if action == "navigate":
        idx = int(obj.get("index") or 0)
        picked = by_index.get(idx)
        if picked and str(picked.get("name") or "").strip():
            return NavSelection(
                action="navigate",
                destination=str(picked["name"]),
                location=str(picked.get("location") or ""),
                reason=f"LLM·{reason}",
                used_llm=True,
            )

    if action == "narrow":
        indices = obj.get("indices") or []
        narrowed: List[Dict[str, Any]] = []
        for raw_idx in indices:
            try:
                idx = int(raw_idx)
            except (TypeError, ValueError):
                continue
            c = by_index.get(idx)
            if c:
                narrowed.append(c)
        if narrowed and len(narrowed) < len(cands):
            return NavSelection(
                action="narrow",
                candidates=narrowed,
                reason=f"LLM·{reason}",
                used_llm=True,
            )

    if action == "repeat":
        return NavSelection(action="repeat", candidates=cands, reason=f"LLM·{reason}", used_llm=True)

    return None


def _resolve_nav_selection_fallback(query: str, cands: List[Dict[str, Any]]) -> NavSelection:
    """无 LLM 时的规则兜底（测试/离线）。"""
    core = _strip_shell((query or "").strip())

    filtered = _filter_by_constraints(core, cands)
    if len(filtered) == 1:
        c = filtered[0]
        return NavSelection(
            action="navigate",
            destination=str(c["name"]),
            location=str(c.get("location") or ""),
            reason="约束唯一命中",
        )
    if len(filtered) > 1 and len(filtered) < len(cands):
        return NavSelection(action="narrow", candidates=filtered, reason="约束收窄仍多选")

    scored = sorted(((_score(core, str(c["name"])), c) for c in cands), key=lambda x: -x[0])
    best_s, best_c = scored[0]
    second_s = scored[1][0] if len(scored) > 1 else 0.0
    if best_s >= 70 and best_s >= second_s + 12:
        return NavSelection(
            action="navigate",
            destination=str(best_c["name"]),
            location=str(best_c.get("location") or ""),
            reason="评分唯一领先",
        )
    close = [c for s, c in scored if s >= 70 and s >= best_s - 8]
    if len(close) >= 2:
        return NavSelection(action="narrow", candidates=close, reason="评分并列")

    return NavSelection(action="repeat", candidates=cands, reason="未匹配到候选")


def resolve_nav_selection(
    query: str,
    candidates: Optional[list],
    *,
    llm: Optional["LLMClient"] = None,
    query_label: str = "",
) -> NavSelection:
    """在已有候选上解释用户话；默认绝不触发新的全市检索。"""
    cands = _norm_candidates(candidates)
    ruled = _resolve_nav_selection_rules(query, cands)
    if ruled is not None:
        return ruled

    if llm is not None:
        llm_sel = _llm_resolve_nav_selection(llm, query, cands, query_label=query_label)
        if llm_sel is not None:
            # 安全网：LLM 把「我不选 / 问家在哪」误判成 repeat 时强制放行
            if llm_sel.action == "repeat" and _force_clear_mistaken_repeat(query, cands):
                return NavSelection(
                    action="clear",
                    reason=f"纠正误判repeat→clear·{llm_sel.reason}",
                    used_llm=True,
                )
            return llm_sel

    fb = _resolve_nav_selection_fallback(query, cands)
    if fb.action == "repeat" and _force_clear_mistaken_repeat(query, cands):
        return NavSelection(action="clear", reason="兜底换题，释放导航候选")
    return fb


def format_clarify_speech(query_label: str, candidates: List[Dict[str, Any]]) -> str:
    names = [str(c.get("name") or "").strip() for c in candidates if str(c.get("name") or "").strip()]
    names = names[:4]
    q = (query_label or "那里").strip() or "那里"
    if not names:
        return f"刚才那几个地点我没对上，你再说一下想去哪？"
    if len(names) == 1:
        return f"那就是{names[0]}吗？要我现在带你过去？"
    if len(names) == 2:
        return f"你是想去{names[0]}，还是{names[1]}？"
    mid = "、".join(names[:-1])
    return f"还是有点含糊：{mid}，还有{names[-1]}。你选一个？"
