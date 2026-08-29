# -*- coding: utf-8 -*-
"""轮末画像：整篇加载 Markdown，按语义改写或追加，不走固定字段。"""
from __future__ import annotations

import re
from typing import Dict, List, Optional, TYPE_CHECKING

from app.agent.user_profile import (
    ProfileExtractReport,
    UserProfileStore,
    clamp_markdown,
    is_placeholder,
    looks_unchanged,
)

if TYPE_CHECKING:
    from app.models import ProfileUpdatePlan

REVISE_SYSTEM = """你在维护车载助手「小特」的三份用户笔记（Markdown）。
这不是填表，也不是写作文。

三份笔记的分工（按语义，同一事实只写一份）：
- persona.md：小特以后该怎么说话（语气、长短、禁忌）。不含「叫我什么」。
- memories.md：关于这个人的长期事实（家人、住址、工作、经历）。不含单纯称呼偏好。
- preferences.md：默认怎么对待用户、车上默认怎么做。**「以后叫我X / 称呼我为X」只写这里。**

硬性规则（必须遵守）：
1. 只写用户**本轮明确说出**的信息；禁止猜测、脑补、举一反三。
2. 严禁出现「用户可能」「可能希望」「或许」「大概会」等推测句。
3. 默认尽量输出 UNCHANGED；有改动时优先改一行或末尾加 1 条，不要整篇重写灌水。
4. **同一信息禁止抄进多份**：例如「叫我赵照」→ 只改 preferences.md，另外两份必须 UNCHANGED。
5. 行数上限是上限不是配额：人设≤8 条、记忆≤12 条、偏好≤10 条；能少则少。
6. 禁止同义反复（同一意思拆成很多「不要叫X」）。
7. 一次性控车/查状态/寒暄 → 三份都 UNCHANGED。
8. 「现在打开空调」不是偏好；「以后默认偏凉」才是偏好。
9. 用户要求忘掉某类内容时，对应文档写回简短空白说明（「目前没有条目」），不要写一长串「已清除」。

格式：
- Markdown；标题一个 #；条目用 - 短句。
- 三块都要有；无改动写 UNCHANGED。

输出格式：
---persona.md---
UNCHANGED
---memories.md---
UNCHANGED
---preferences.md---
UNCHANGED
"""

_SPECULATIVE_RE = re.compile(
    r"(用户可能|可能希望|或许希望|大概希望|也许希望|似乎希望|潜在希望|可能不喜欢|可能有多重)"
)
_NAME_FACT_RE = re.compile(
    r"(?:称呼|叫我|姓名|名叫|名字|昵称)[：:\s]*([^\s，。；,（(]{1,12})"
)
_MAX_BULLETS = {"persona": 8, "memories": 12, "preferences": 10}
_MAX_NEW_BULLETS = 3


def _chat(llm, system: str, user: str) -> str:
    try:
        return llm.chat(system, user, temperature=0.0, max_tokens=480, retries=1) or ""
    except Exception:
        return ""


def _parse_sections(raw: str) -> Dict[str, str]:
    text = (raw or "").strip()
    text = re.sub(r"^```(?:markdown|md|text)?\s*", "", text, flags=re.I)
    text = re.sub(r"\s*```$", "", text)
    parts = {"persona": "", "memories": "", "preferences": ""}
    current = None
    buf: list[str] = []

    def flush():
        if current:
            parts[current] = "\n".join(buf).strip()

    for ln in text.splitlines():
        m = re.match(r"^---\s*(persona|memories|preferences)\.md\s*---\s*$", ln.strip(), re.I)
        if m:
            flush()
            current = m.group(1).lower()
            buf = []
            continue
        if current:
            buf.append(ln)
    flush()
    if not any(parts.values()) and text and not looks_unchanged(text):
        parts["memories"] = text
    return parts


def _bullets(text: str) -> List[str]:
    out: List[str] = []
    for ln in (text or "").splitlines():
        s = ln.strip()
        if s.startswith(("- ", "* ", "• ")):
            out.append(s[2:].strip())
    return out


def _norm_bullet(s: str) -> str:
    return re.sub(r"\s+", "", (s or "").lower())


def _is_speculative(bullet: str) -> bool:
    return bool(_SPECULATIVE_RE.search(bullet or ""))


def _title_for(kind: str) -> str:
    return {"persona": "# 人设", "memories": "# 身份记忆", "preferences": "# 偏好"}[kind]


def _name_fact_key(bullet: str) -> Optional[str]:
    m = _NAME_FACT_RE.search(bullet or "")
    if not m:
        # 「用户姓名：赵照」已由上面覆盖；兜底「我叫X」类
        m2 = re.search(r"(?:用户)?(?:叫|是)\s*([^\s，。；,]{1,12})", bullet or "")
        if m2 and re.search(r"(称呼|姓名|名字|叫我)", bullet or ""):
            return "name:" + _norm_bullet(m2.group(1))
        return None
    return "name:" + _norm_bullet(m.group(1))


def _home_kind_for_bullet(bullet: str, fallback: str) -> str:
    """同一事实归到唯一篮子：称呼→偏好；语气→人设；其余保持原篮子。"""
    if _name_fact_key(bullet):
        return "preferences"
    if re.search(r"(语气|说话|简洁|温柔|专业|书面|幽默|客套|口头禅)", bullet or ""):
        return "persona"
    return fallback


def _md_from_bullets(kind: str, bullets: List[str]) -> str:
    if not bullets:
        return "UNCHANGED"
    lines = [_title_for(kind), ""] + [f"- {b}" for b in bullets]
    return "\n".join(lines) + "\n"


def _rehome_sections(sections: Dict[str, str]) -> Dict[str, str]:
    """跨文档去重：称呼/姓名只进 preferences，禁止三份各写一遍。"""
    buckets: Dict[str, List[str]] = {"persona": [], "memories": [], "preferences": []}
    seen_fact: Dict[str, str] = {}  # fact_key -> kind kept
    seen_norm: set = set()

    for kind in ("preferences", "persona", "memories"):
        body = sections.get(kind) or ""
        if looks_unchanged(body) or not body.strip():
            continue
        for b in _bullets(body):
            if _is_speculative(b):
                continue
            home = _home_kind_for_bullet(b, kind)
            fact = _name_fact_key(b)
            if fact:
                if fact in seen_fact:
                    continue
                # 统一成「称呼：名字」
                name = fact.split(":", 1)[1]
                # 还原较可读写法
                raw_name = re.sub(
                    r"^(?:称呼|叫我|姓名|名叫|名字|昵称|用户姓名)[：:\s]*",
                    "",
                    b,
                ).strip() or name
                b = f"称呼：{raw_name}"
                home = "preferences"
                seen_fact[fact] = home
            key = _norm_bullet(b)
            if not key or key in seen_norm:
                continue
            seen_norm.add(key)
            buckets[home].append(b)

    out = dict(sections)
    for kind in ("persona", "memories", "preferences"):
        orig = sections.get(kind) or ""
        if looks_unchanged(orig) and not buckets[kind]:
            out[kind] = "UNCHANGED"
        elif buckets[kind]:
            out[kind] = _md_from_bullets(kind, buckets[kind])
        elif not looks_unchanged(orig) and _bullets(orig):
            # 原文有条目但全部被迁走 → UNCHANGED（不要用空文档覆盖旧内容）
            out[kind] = "UNCHANGED"
        else:
            out[kind] = orig if orig else "UNCHANGED"
    return out


def _sanitize_revised(kind: str, old: str, new: str) -> Optional[str]:
    """清洗灌水/推测条目；若无有效改写则返回 None（视为 UNCHANGED）。"""
    if looks_unchanged(new) or not (new or "").strip():
        return None
    if (new or "").strip().startswith("{"):
        return None

    old_bs = _bullets(old)
    new_bs = _bullets(new)
    if not new_bs:
        # 允许清空为占位说明
        body = re.sub(r"^#.*$", "", new or "", flags=re.M).strip()
        if body.startswith("目前没有") or is_placeholder(new):
            if is_placeholder(old):
                return None
            return clamp_markdown(new, kind)
        return None

    cleaned: List[str] = []
    seen = set()
    for b in new_bs:
        if _is_speculative(b):
            continue
        # 偏好：跳过纯否定灌水（「称呼：不要使用××」连发）
        if kind == "preferences" and re.match(r"称呼[：:].*不要", b):
            if any(re.match(r"称呼[：:].*不要", x) for x in cleaned):
                continue
        # 人设/记忆里不应再残留纯称呼条目（rehome 后兜底）
        if kind in ("persona", "memories") and _name_fact_key(b):
            continue
        key = _norm_bullet(b)
        if not key or key in seen:
            continue
        if len(b) < 2:
            continue
        seen.add(key)
        cleaned.append(b)

    if not cleaned:
        return None

    old_set = {_norm_bullet(b) for b in old_bs}
    added = [b for b in cleaned if _norm_bullet(b) not in old_set]
    kept_old = [b for b in cleaned if _norm_bullet(b) in old_set]

    cap = _MAX_BULLETS[kind]
    if len(old_bs) == 0:
        final = cleaned[: min(cap, _MAX_NEW_BULLETS)]
    else:
        final = kept_old + added[:_MAX_NEW_BULLETS]
        if len(final) > cap:
            final = (added[:_MAX_NEW_BULLETS] + kept_old)[:cap]

    if {_norm_bullet(b) for b in final} == old_set and len(final) == len(old_bs):
        return None

    lines = [_title_for(kind), ""] + [f"- {b}" for b in final]
    return clamp_markdown("\n".join(lines) + "\n", kind)


def extract_after_turn(
    llm,
    store: UserProfileStore,
    user_query: str,
    assistant_text: str = "",
    profile_plan: Optional["ProfileUpdatePlan"] = None,
) -> ProfileExtractReport:
    """主干结束后：按语义决定是否改写三份 md。"""
    from app.models import ProfileUpdatePlan

    report = ProfileExtractReport()
    if llm is None or not (user_query or "").strip():
        return report

    plan = profile_plan if profile_plan is not None else ProfileUpdatePlan(
        persona=True, memory=True, preferences=True
    )
    triage = plan.to_triage_dict()
    report.intent_decision = dict(triage)
    report.triage = triage

    # 显式空计划 = NLU 认为本轮没有长期信息
    if profile_plan is not None and not plan.needs_work():
        report.notes.append("首轮语义判断：无需更新笔记")
        return report

    clear = triage.get("clear") if isinstance(triage.get("clear"), dict) else {}
    cleared_any = False
    if clear.get("persona"):
        store.clear_persona()
        report.persona_updated = True
        report.notes.append("已清空人设")
        cleared_any = True
    if clear.get("memory"):
        store.clear_memories()
        report.memories_updated = True
        report.notes.append("已清空身份记忆")
        cleared_any = True
    if clear.get("preferences"):
        store.clear_preferences()
        report.preferences_updated = True
        report.notes.append("已清空偏好")
        cleared_any = True
    if cleared_any:
        report.update_steps.append(
            {"kind": "clear", "clear": clear, "user_input": user_query.strip(), "applied": True}
        )

    # 仅清空、无需改写时，不要再调模型（避免写出「已清除」灌水）
    want_revise = bool(triage.get("persona") or triage.get("memory") or triage.get("preferences"))
    if not want_revise:
        if not cleared_any:
            report.notes.append("首轮语义判断：无需更新笔记")
        return report

    snap = store.snapshot_for_extract()
    hint = []
    if triage.get("persona"):
        hint.append("人设")
    if triage.get("memory"):
        hint.append("身份记忆")
    if triage.get("preferences"):
        hint.append("偏好")
    hint_txt = "、".join(hint) if hint else "不限定，完全按语义"

    user = (
        f"首轮粗判（仅供参考；仍须遵守硬性规则，禁止脑补）：{hint_txt}\n\n"
        f"用户原话：{(user_query or '').strip()}\n"
        f"助手本轮回复：{(assistant_text or '').strip()[:400] or '（无）'}\n\n"
        f"---persona.md 当前---\n{snap['persona']}\n"
        f"---memories.md 当前---\n{snap['memories']}\n"
        f"---preferences.md 当前---\n{snap['preferences']}\n"
    )
    raw = _chat(llm, REVISE_SYSTEM, user)
    report.llm_calls += 1
    sections = _rehome_sections(_parse_sections(raw))
    step = {
        "kind": "markdown_revise",
        "hint": hint,
        "user_input": user_query.strip(),
        "llm_raw": raw[:1200],
        "applied": {},
        "sanitized": {},
    }
    for kind, key in (("persona", "persona"), ("memories", "memories"), ("preferences", "preferences")):
        body = sections.get(kind) or ""
        old = store.read_md(kind)
        cleaned = _sanitize_revised(kind, old, body)
        if cleaned is None:
            step["applied"][kind] = False
            step["sanitized"][kind] = "skipped"
            continue
        if is_placeholder(cleaned) and not is_placeholder(old):
            # 允许明确清空；否则跳过
            if "目前没有" not in cleaned:
                step["applied"][kind] = False
                continue
        if store.write_md(kind, cleaned):
            if kind == "persona":
                report.persona_updated = True
            elif kind == "memories":
                report.memories_updated = True
            else:
                report.preferences_updated = True
            report.notes.append(f"{key}.md 已更新")
            step["applied"][kind] = True
            step["sanitized"][kind] = "ok"
        else:
            step["applied"][kind] = False
            step["sanitized"][kind] = "unchanged_on_disk"
    report.update_steps.append(step)
    if not any(step["applied"].values()) and not (
        report.persona_updated or report.memories_updated or report.preferences_updated
    ):
        report.notes.append("模型判断笔记无需改写")
    return report


def profile_step_title(
    persona_updated: bool = False,
    memories_updated: bool = False,
    preferences_updated: bool = False,
    *,
    failed: bool = False,
    skipped: bool = False,
) -> str:
    """执行轨迹步骤名。"""
    if failed:
        return "更新记忆/人设/偏好失败"
    parts: List[str] = []
    if memories_updated:
        parts.append("记忆")
    if persona_updated:
        parts.append("人设")
    if preferences_updated:
        parts.append("偏好")
    if parts:
        base = "更新" + "/".join(parts)
    else:
        base = "更新记忆/人设/偏好"
    if skipped:
        return f"{base}（未落盘）"
    return base
