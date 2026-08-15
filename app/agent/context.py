# -*- coding: utf-8 -*-
"""上下文组装：有序 source 拼装（对齐 Claude Code context assembly）。"""
from __future__ import annotations

import json
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
    ) -> ContextBundle:
        sources: List[str] = []
        cabin = memory.load_cabin()
        sources.append("cabin_md")
        auto_mem = memory.load_auto_memory()
        sources.append("auto_memory")

        slim = _slim_vehicle(vehicle_state)
        vehicle_txt = json.dumps(slim, ensure_ascii=False)
        sources.append("vehicle_state")

        msgs = transcript.load()
        compact_bits = [m.content for m in msgs if m.role == MessageRole.COMPACTION]
        compact_txt = "\n---\n".join(compact_bits[-2:]) if compact_bits else ""
        if compact_txt:
            sources.append("compaction")

        recent = [m for m in msgs if m.role != MessageRole.COMPACTION][-recent_limit:]
        dialog = _format_dialog(recent)
        sources.append("transcript_recent")

        user_context_parts = [
            "### Persistent Instructions (CABIN.md)",
            cabin,
            "### Auto Memory (MEMORY.md)",
            auto_mem or "(空)",
            "### Structured Preferences (preferences.json)",
            memory.format_preferences_block(),
            "### Vehicle State Snapshot",
            vehicle_txt,
        ]
        sources.append("preferences")
        if compact_txt:
            user_context_parts += ["### Compaction Summary", compact_txt]
        if extra_user:
            user_context_parts += ["### Extra", extra_user]
            sources.append("extra")

        user_context = "\n\n".join(user_context_parts)
        total = len(SYSTEM_CORE) + len(user_context) + len(dialog)
        return ContextBundle(
            system=SYSTEM_CORE,
            user_context=user_context,
            recent_dialog=dialog,
            total_chars=total,
            sources=sources,
        )

    def memory_hint(self, bundle: ContextBundle, transcript: TranscriptStore, limit: int = 8) -> str:
        """给 StructuredNLU 用的短历史 + 结构化偏好。"""
        base = transcript.hint(limit=limit)
        pref = ""
        if "Structured Preferences" in bundle.user_context:
            pref = bundle.user_context.split("### Structured Preferences")[-1].split("###")[0].strip()
            pref = pref[:400]
        bits = []
        if pref:
            bits.append(pref)
        if "Compaction Summary" in bundle.user_context:
            bits.append(bundle.user_context.split("### Compaction Summary")[-1][:200])
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
        "apps": st.get("apps"),
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
    marker = "### Vehicle State Snapshot"
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

