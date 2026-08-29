# -*- coding: utf-8 -*-
"""上下文组装：按来源有序拼装座舱对话上下文。"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.agent.memory import MemoryStore
from app.agent.persona import SYSTEM_CORE
from app.agent.transcript import TranscriptStore
from app.agent.types import ContextBundle, MessageRole, TranscriptMessage


class ContextAssembler:
    def assemble(
        self,
        memory: MemoryStore,
        transcript: TranscriptStore,
        vehicle_state: Dict[str, Any],
        extra_user: str = "",
        recent_limit: int = 12,
        keep_turns: Optional[int] = None,
    ) -> ContextBundle:
        sources: List[str] = []
        persona_block = memory.format_persona_block()
        sources.append("persona")
        memories_block = memory.format_memories_block()
        sources.append("memories")
        prefs_block = memory.format_preferences_block()
        sources.append("preferences")

        slim = _slim_vehicle(vehicle_state)
        vehicle_txt = json.dumps(slim, ensure_ascii=False)
        sources.append("vehicle_state")

        turns = keep_turns if keep_turns is not None else max(1, (recent_limit + 1) // 2)
        window = transcript.load_for_context(keep_turns=turns)
        compact_bits = [m.content for m in window if m.role == MessageRole.COMPACTION]
        compact_txt = "\n---\n".join(compact_bits) if compact_bits else ""
        if compact_txt:
            sources.append("compaction")

        recent = [m for m in window if m.role != MessageRole.COMPACTION]
        dialog = _format_dialog(recent)
        sources.append("transcript_recent")

        user_context_parts = [
            "### 用户人设 (persona.md)",
            persona_block,
            "### 身份记忆 (memories.md)",
            memories_block,
            "### 行为偏好 (preferences.md)",
            prefs_block,
            "### 车辆状态快照",
            vehicle_txt,
        ]
        if compact_txt:
            user_context_parts += ["### 压缩摘要", compact_txt]
        if extra_user:
            user_context_parts += ["### 附加材料", extra_user]
            sources.append("extra")

        user_context = "\n\n".join(user_context_parts)
        system = memory.build_system_prompt()
        total = len(system) + len(user_context) + len(dialog)
        return ContextBundle(
            system=system,
            user_context=user_context,
            recent_dialog=dialog,
            total_chars=total,
            sources=sources,
        )

    def memory_hint(self, bundle: ContextBundle, transcript: TranscriptStore, limit: int = 8) -> str:
        """给 StructuredNLU：偏好默认值 + 简要身份记忆 + 近轮对话。"""
        base = transcript.hint(limit=limit)
        bits = []
        if "### 行为偏好" in bundle.user_context:
            bits.append(
                bundle.user_context.split("### 行为偏好")[-1].split("###")[0].strip()[:400]
            )
        if "### 身份记忆" in bundle.user_context:
            mem = bundle.user_context.split("### 身份记忆")[-1].split("###")[0].strip()
            if mem and "(暂无" not in mem:
                bits.append(mem[:350])
        if "压缩摘要" in bundle.user_context:
            bits.append(bundle.user_context.split("### 压缩摘要")[-1][:200])
        bits.append(base)
        return " || ".join(bits)[:900]

def _format_dialog(msgs: List[TranscriptMessage]) -> str:
    lines = []
    for m in msgs:
        lines.append(f"{m.role.value}: {m.content}")
    return "\n".join(lines)


def _slim_vehicle(st: Dict[str, Any]) -> Dict[str, Any]:
    """给 LLM 的车况快照：分区状态必须齐全，否则会把主驾温度误套到其他座位。"""
    seats = st.get("seats") or {}
    climate = st.get("climate") or {}
    cabin = st.get("cabin") or {}
    media = st.get("media") or {}
    music = media.get("music") or {}
    radio = media.get("radio") or {}
    return {
        "dynamics": st.get("dynamics"),
        "climate": {
            "power": climate.get("power"),
            "mode": climate.get("mode"),
            "direction": climate.get("direction"),
            "recirculation": climate.get("recirculation"),
            # 五区独立，缺一不可
            "zones": climate.get("zones") or {},
        },
        # 不注入曲库/电台全表，避免模型借题发挥「歌快放完了」
        "media": {
            "volume": media.get("volume"),
            "muted": media.get("muted"),
            "music": {
                "playing": music.get("playing"),
                "artist": music.get("artist"),
                "title": music.get("title"),
            },
            "radio": {
                "playing": radio.get("playing"),
                "station_name": radio.get("station_name"),
                "band": radio.get("band"),
                "frequency": radio.get("frequency"),
            },
        },
        "seats": {
            "heat": seats.get("heat") or {},
            "ventilation": seats.get("ventilation") or {},
            "massage": seats.get("massage") or {},
            "steering_wheel_heat": seats.get("steering_wheel_heat"),
        },
        "navigation": _slim_navigation(st.get("navigation") or {}),
        "cabin": {
            "windows": cabin.get("windows") or {},
            "doors": cabin.get("doors") or {},
            "lights": cabin.get("lights") or {},
            "trunk": cabin.get("trunk"),
            "frunk": cabin.get("frunk"),
            "charge_port": cabin.get("charge_port"),
            "displays": cabin.get("displays") or {},
        },
        "driving": st.get("driving"),
        "apps": {
            "active": (st.get("apps") or {}).get("active"),
            "running": (st.get("apps") or {}).get("running") or [],
        },
    }


def slim_vehicle_for_query(st: Dict[str, Any], query: str) -> Dict[str, Any]:
    """按用户本轮问题裁剪车况，减少无关子系统诱发硬接闲聊。"""
    import re

    slim = _slim_vehicle(st)
    q = (query or "").strip()
    about_media = bool(re.search(r"(音乐|歌|电台|音量|静音|播放|暂停|下一首|上一首|合唱|听)", q))
    about_climate = bool(re.search(r"(空调|温度|制冷|制热|风量|内循环|外循环)", q))
    about_seat = bool(re.search(r"(座椅|加热|通风|按摩|方向盘热)", q))
    about_nav = bool(
        re.search(
            r"(导航|在哪|哪里|位置|到哪|目的地|还要多久|还差|多久|几分钟|几公里|多远|剩余|到达|ETA|路况|还有多[久远]|几点到)",
            q,
            re.I,
        )
    )
    about_speed = bool(re.search(r"(车速|速度|多快|时速|巡航|ACC|挡位|挂挡)", q, re.I))
    about_cabin = bool(
        re.search(
            r"(车窗|门锁|后备箱|前备箱|充电口|灯光|氛围灯|阅读灯|顶灯|氛围|车灯|屏幕亮度|中控亮度|仪表亮度|HUD)",
            q,
            re.I,
        )
    )
    about_lights = bool(
        re.search(r"(灯光|氛围灯|阅读灯|顶灯|氛围|车灯)", q)
    )
    about_apps = bool(re.search(r"(应用|App|打开|关掉).{0,8}(音乐|地图|导航|视频)?", q, re.I))

    # 状态问答：未点名的子系统直接不喂给模型
    if not about_media:
        slim.pop("media", None)
    if not about_climate:
        slim.pop("climate", None)
    if not about_seat:
        slim.pop("seats", None)
    if not about_nav:
        # 仍保留极简定位名，避免「我们在哪」漏网；进度字段只在导航相关问句里给
        nav = slim.get("navigation") or {}
        slim["navigation"] = {
            "navigating": bool(nav.get("navigating")),
            "mode": nav.get("mode"),
            "position": nav.get("position"),
            "note": nav.get("note"),
        }
    else:
        # 问剩余时间/进度：必须带上实时 eta / remaining（由 tick 持续更新）
        nav = slim.get("navigation") or {}
        if isinstance(nav, dict):
            slim["navigation"] = {
                **nav,
                "eta_min": (st.get("navigation") or {}).get("eta_min"),
                "remaining_m": (st.get("navigation") or {}).get("remaining_m"),
                "destination": (st.get("navigation") or {}).get("destination"),
                "distance_m": (st.get("navigation") or {}).get("distance_m"),
                "traffic": (st.get("navigation") or {}).get("traffic"),
                "navigating": bool((st.get("navigation") or {}).get("navigating")),
                "mode": (st.get("navigation") or {}).get("mode"),
                "position": (st.get("navigation") or {}).get("position"),
            }
    if not about_cabin:
        slim.pop("cabin", None)
    elif about_lights and not re.search(r"(车窗|门锁|后备箱|前备箱|充电口|屏幕|中控|仪表|HUD)", q, re.I):
        # 只问灯：cabin 只留 lights，少喂无关字段
        cabin = slim.get("cabin") or {}
        slim["cabin"] = {"lights": cabin.get("lights") or {}}
    if not about_apps:
        slim.pop("apps", None)
    # 只问位置时不要喂车速/巡航，否则容易顺带念仪表
    if about_nav and not about_speed:
        slim.pop("dynamics", None)
        slim.pop("driving", None)
    elif not about_speed and not about_nav:
        # 其它窄问题也不默认带动力学，除非问了速度相关
        if not re.search(r"(电量|续航|电池|胎压|里程)", q):
            slim.pop("dynamics", None)
            slim.pop("driving", None)
    return slim


def strip_vehicle_snapshot_block(user_context: str) -> str:
    """去掉上下文里的完整 Vehicle State 段，避免与按问题裁剪的 JSON 重复且诱发加戏。"""
    marker = "### 车辆状态快照"
    if marker not in (user_context or ""):
        return user_context or ""
    head, rest = user_context.split(marker, 1)
    if "###" in rest:
        rest = "###" + rest.split("###", 1)[1]
    else:
        rest = ""
    return (head.rstrip() + ("\n\n" + rest.lstrip() if rest.strip() else "")).strip()


def _slim_navigation(nav: Dict[str, Any]) -> Dict[str, Any]:
    """未开导航时不要把巡航走廊的剩余里程/ETA 喂给模型，避免误说「导航还剩 xx 公里」。"""
    navigating = bool(nav.get("navigating"))
    pos = nav.get("position") or {}
    place = {
        "name": pos.get("name"),
        "lng": pos.get("lng"),
        "lat": pos.get("lat"),
    }
    if navigating:
        return {
            "navigating": True,
            "mode": "navigating",
            "destination": nav.get("destination"),
            "eta_min": nav.get("eta_min"),
            "remaining_m": nav.get("remaining_m"),
            "distance_m": nav.get("distance_m"),
            "traffic": nav.get("traffic"),
            "preference": nav.get("preference"),
            "position": place,
            "heading_deg": nav.get("heading_deg"),
            "arrived": nav.get("arrived"),
        }
    return {
        "navigating": False,
        "mode": nav.get("mode") or "cruising",
        "destination": None,
        "eta_min": None,
        "remaining_m": None,
        "distance_m": None,
        "corridor_dest": None,
        "traffic": None,
        "position": place,
        "heading_deg": nav.get("heading_deg"),
        "note": "未开启导航；仅有当前位置路名。禁止提及剩余公里/ETA/目的地进度；后台道路巡航不是导航。",
    }


def format_nav_status(st: Dict[str, Any]) -> str:
    """可读导航/定位一览，供 SEARCH/CHAT 引用（含实时剩余/ETA）。"""
    nav = st.get("navigation") or {}
    pos = nav.get("position") or {}
    place = str(pos.get("name") or "当前位置")
    if not nav.get("navigating"):
        return (
            f"导航：未开启\n"
            f"当前位置：{place}\n"
            "说明：当前没有导航行程，没有剩余时间/里程可报；"
            "不要说剩余里程、ETA、路况或「正往某某开」；"
            "只根据当前位置回答在哪里即可。"
        )
    remain = nav.get("remaining_m")
    if isinstance(remain, (int, float)):
        remain_s = f"{remain / 1000:.1f} 公里" if remain >= 1000 else f"{int(remain)} 米"
    else:
        remain_s = "未知"
    eta = nav.get("eta_min")
    eta_s = f"约 {int(eta)} 分钟" if isinstance(eta, (int, float)) else "未知"
    dest = nav.get("destination") or "目的地"
    traffic = nav.get("traffic") or "未知"
    return (
        f"导航：进行中 → {dest}\n"
        f"当前位置：{place}\n"
        f"剩余时间：{eta_s}\n"
        f"剩余里程：{remain_s}\n"
        f"路况：{traffic}\n"
        "说明：以上为实时导航状态，可直接回答「还差几分钟/还有多远」；"
        "不要说「算不出来/系统没算出」——字段是未知才说暂时没有，有数字就照报。"
    )


def format_climate_status(st: Dict[str, Any], active_seat: str = "front_left") -> str:
    """可读的分区空调一览，供 SEARCH 优先引用，避免模型漏读 JSON。"""
    from app.nlu.seat_context import SEAT_CN, normalize_active_seat

    climate = st.get("climate") or {}
    zones = climate.get("zones") or {}
    seat = normalize_active_seat(active_seat)
    power = "开" if climate.get("power") else "关"
    recirculation = "内循环" if climate.get("recirculation") else "外循环"
    lines = [
        f"空调总开关：{power}",
        f"模式：{climate.get('mode') or 'auto'} · {recirculation}",
        "各座位（相互独立，勿混用）：",
    ]
    order = ["front_left", "front_right", "rear_left", "rear_middle", "rear_right"]
    for z in order:
        node = zones.get(z) or {}
        cn = SEAT_CN.get(z, z)
        mark = " ←当前说话人" if z == seat else ""
        on = "分区开" if node.get("on") else "分区关"
        temp = node.get("temp")
        fan = node.get("fan")
        temp_s = f"{temp:.0f}°C" if isinstance(temp, (int, float)) else f"{temp}°C"
        lines.append(f"- {cn}: {on}, 设定温度 {temp_s}, 风量 {fan}{mark}")
    return "\n".join(lines)


def spoken_vehicle_status(
    st: Dict[str, Any],
    query: str,
    active_seat: str = "front_left",
) -> str:
    """LLM 不可用时，用车况快照直接出口语，不含报错原文。"""
    from app.nlu.seat_context import SEAT_CN, normalize_active_seat

    q = (query or "").strip()
    about_climate = any(k in q for k in ("空调", "温度", "制冷", "制热", "风量", "循环"))
    about_nav = any(
        k in q
        for k in (
            "导航",
            "在哪",
            "位置",
            "到哪",
            "目的地",
            "还要多久",
            "还差",
            "多久",
            "几分钟",
            "几公里",
            "多远",
            "剩余",
            "到达",
            "路况",
            "还有多",
        )
    )
    about_lights = any(k in q for k in ("氛围灯", "阅读灯", "顶灯", "灯光", "氛围", "车灯"))
    seat = normalize_active_seat(active_seat)

    if about_nav:
        nav = st.get("navigation") or {}
        pos = nav.get("position") or {}
        place = str(pos.get("name") or "").strip()
        if nav.get("navigating"):
            dest = str(nav.get("destination") or "目的地").strip() or "目的地"
            remain = nav.get("remaining_m")
            remain_s = ""
            if isinstance(remain, (int, float)):
                remain_s = (
                    f"，还剩约 {remain / 1000:.1f} 公里"
                    if remain >= 1000
                    else f"，还剩约 {int(remain)} 米"
                )
            if place:
                return f"【听】你现在在{place}，正往{dest}开{remain_s}。"
            return f"【听】导航已开，正往{dest}开{remain_s}。"
        if place:
            return f"【听】你现在在{place}，导航没开。"
        return "【听】定位我这边读到了，但路名暂时空着。"

    if about_climate:
        climate = st.get("climate") or {}
        zones = climate.get("zones") or {}
        node = zones.get(seat) or {}
        power = "开着" if climate.get("power") else "关着"
        seat_cn = SEAT_CN.get(seat, seat)
        temp = node.get("temp")
        if isinstance(temp, (int, float)):
            return f"【听】空调现在{power}，{seat_cn}这边大约 {temp:.0f} 度。"
        return f"【听】空调现在{power}。"

    if about_lights:
        lights = ((st.get("cabin") or {}).get("lights") or {})
        labels = {
            "ambient": "氛围灯",
            "dome": "顶灯",
            "reading_left": "左阅读灯",
            "reading_right": "右阅读灯",
        }
        on = [labels[k] for k in labels if (lights.get(k) or {}).get("enable")]
        if on:
            return f"【听】现在开着的是{'、'.join(on)}。"
        return "【听】车内这几盏灯现在都关着。"

    nav = st.get("navigation") or {}
    place = str(((nav.get("position") or {}).get("name") or "")).strip()
    if place:
        return f"【听】我刚从车上读到：当前位置是{place}。"
    return ""


def format_lights_status(st: Dict[str, Any]) -> str:
    """可读灯光一览，供 SEARCH 优先引用。"""
    lights = ((st.get("cabin") or {}).get("lights") or {})
    labels = {
        "ambient": "氛围灯",
        "dome": "顶灯",
        "reading_left": "左阅读灯",
        "reading_right": "右阅读灯",
    }

    def _one(key: str) -> str:
        node = lights.get(key) or {}
        name = labels.get(key, key)
        if not node.get("enable"):
            return f"{name}：关"
        bri = node.get("brightness")
        color = node.get("color")
        bits = [f"{name}：开"]
        if bri is not None:
            bits.append(f"亮度 {bri}%")
        if key == "ambient" and color:
            bits.append(f"颜色 {color}")
        return "，".join(bits)

    lines = ["车内灯光（以本表为准，可直接回答开/关）："]
    for k in ("ambient", "dome", "reading_left", "reading_right"):
        lines.append(f"- {_one(k)}")
    return "\n".join(lines)


def bundle_view_sections(bundle: ContextBundle) -> List[Dict[str, Any]]:
    """给执行轨迹页拆成可读块；车况 JSON 仅在展示时格式化。"""
    sections: List[Dict[str, Any]] = []
    system = (bundle.system or "").strip()
    if system:
        sections.append({"id": "system", "title": "系统人设", "chars": len(system), "text": system})

    raw = (bundle.user_context or "").strip()
    if raw:
        for block in re.split(r"\n(?=### )", raw):
            block = block.strip()
            if not block.startswith("### "):
                continue
            first, _, rest = block.partition("\n")
            heading = first[4:].strip()
            body = rest.strip()
            title = heading.split("(")[0].strip() or heading
            if title.startswith("车辆状态快照"):
                body = _pretty_json_block(body)
            if not body:
                continue
            sec_id = {
                "项目约定": "cabin",
                "用户记忆": "memory",
                "结构化偏好": "preferences",
                "车辆状态快照": "vehicle",
                "压缩摘要": "compaction",
                "附加材料": "extra",
            }.get(title, title)
            sections.append({"id": sec_id, "title": title, "chars": len(body), "text": body})

    dialog = (bundle.recent_dialog or "").strip()
    if dialog:
        sections.append(
            {"id": "recent_dialog", "title": "最近对话", "chars": len(dialog), "text": dialog}
        )
    return sections


def _pretty_json_block(text: str) -> str:
    try:
        return json.dumps(json.loads(text), ensure_ascii=False, indent=2)
    except Exception:
        return text

