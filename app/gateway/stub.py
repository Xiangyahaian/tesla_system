# -*- coding: utf-8 -*-
"""Stub Gateway：统一读写 canonical state，修复旧版 schema 漂移。"""
from __future__ import annotations

import json
import math
import threading
import time
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.gateway.apps_catalog import (
    ALLOWED_APP_NAMES,
    catalog_for_prompt,
    list_apps,
    normalize_app_name,
    resolve_or_suggest,
)
from app.gateway.base import VehicleGateway
from app.gateway.state_schema import initial_vehicle_state, touch
from app.models import ALL_ZONES, FRONT_ZONES, REAR_ZONES, WINDOW_POSITIONS

ZONE_NAMES = {
    "front_left": "主驾",
    "front_right": "副驾",
    "rear_left": "左后",
    "rear_right": "右后",
    "rear_middle": "后排中间",
    "sunroof": "天窗",
}

MUSIC_LIBRARY = [
    # duration_sec：演示曲库时长（真实时钟推进；约 1.5–2.5 分钟便于看到自动切歌）
    {"artist": "王菲", "title": "红豆", "album": "唱游", "duration_sec": 128},
    {"artist": "王菲", "title": "流年", "album": "王菲", "duration_sec": 142},
    {"artist": "王菲", "title": "执迷不悔", "album": "执迷不悔", "duration_sec": 116},
    {"artist": "王菲", "title": "矜持", "album": "天空", "duration_sec": 134},
    {"artist": "周杰伦", "title": "晴天", "album": "叶惠美", "duration_sec": 148},
    {"artist": "周杰伦", "title": "七里香", "album": "七里香", "duration_sec": 156},
    {"artist": "周杰伦", "title": "稻香", "album": "魔杰座", "duration_sec": 132},
    {"artist": "周杰伦", "title": "青花瓷", "album": "我很忙", "duration_sec": 140},
    {"artist": "陈奕迅", "title": "浮夸", "album": "U87", "duration_sec": 152},
    {"artist": "陈奕迅", "title": "十年", "album": "黑白灰", "duration_sec": 118},
    {"artist": "陈奕迅", "title": "富士山下", "album": "What's Going On...?", "duration_sec": 146},
    {"artist": "陈奕迅", "title": "K歌之王", "album": "打得火热", "duration_sec": 124},
    {"artist": "邓紫棋", "title": "泡沫", "album": "Xposed", "duration_sec": 136},
    {"artist": "邓紫棋", "title": "光年之外", "album": "光年之外", "duration_sec": 150},
    {"artist": "邓紫棋", "title": "句号", "album": "摩天动物园", "duration_sec": 130},
    {"artist": "邓紫棋", "title": "来自天堂的魔鬼", "album": "新的心跳", "duration_sec": 144},
    {"artist": "林俊杰", "title": "江南", "album": "第二天堂", "duration_sec": 138},
    {"artist": "林俊杰", "title": "可惜没如果", "album": "新地球", "duration_sec": 154},
    {"artist": "林俊杰", "title": "修炼爱情", "album": "因你而在", "duration_sec": 126},
    {"artist": "林俊杰", "title": "不为谁而作的歌", "album": "和自己对话", "duration_sec": 148},
]

RADIO_STATIONS = [
    {"band": "FM", "frequency": "91.5", "station_name": "中国之声", "category": "新闻"},
    {"band": "FM", "frequency": "106.1", "station_name": "音乐之声", "category": "音乐"},
    {"band": "FM", "frequency": "103.9", "station_name": "北京交通广播", "category": "交通"},
    {"band": "FM", "frequency": "87.6", "station_name": "北京音乐广播", "category": "音乐"},
    {"band": "FM", "frequency": "101.7", "station_name": "上海音乐广播", "category": "音乐"},
    {"band": "FM", "frequency": "105.7", "station_name": "上海交通广播", "category": "交通"},
    {"band": "FM", "frequency": "94.7", "station_name": "经典947", "category": "古典"},
    {"band": "FM", "frequency": "105.2", "station_name": "广东音乐之声", "category": "音乐"},
    {"band": "AM", "frequency": "639", "station_name": "中国之声AM", "category": "新闻"},
    {"band": "FM", "frequency": "102.6", "station_name": "重庆音乐广播", "category": "音乐"},
]

def _ok(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": True, "message": message, "data": data or {}}


def _fail(message: str, data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    return {"success": False, "message": message, "data": data or {}}


def _normalize_zones(zones: Optional[List[str]], default: Optional[List[str]] = None) -> List[str]:
    if not zones:
        return list(default or ["front_left"])
    out: List[str] = []
    for z in zones:
        z = str(z).strip()
        if z in ("all", "全车"):
            return list(ALL_ZONES)
        if z in ("front", "前排"):
            out.extend(FRONT_ZONES)
            continue
        if z in ("rear", "后排"):
            out.extend(REAR_ZONES)
            continue
        if z in ALL_ZONES:
            out.append(z)
    # 去重保序
    return list(dict.fromkeys(out)) or list(default or ["front_left"])


def _zone_label(zones: List[str]) -> str:
    if set(zones) == set(ALL_ZONES):
        return "全车"
    if set(zones) == set(FRONT_ZONES):
        return "前排"
    if set(zones) == set(REAR_ZONES):
        return "后排"
    return "、".join(ZONE_NAMES.get(z, z) for z in zones)


def _place_name_along_steps(steps: List[Dict[str, Any]], progress_m: float, fallback: str = "当前位置") -> str:
    """按已行驶距离从路径 steps 取当前路名/路段说明。"""
    if not steps:
        return fallback
    walked = 0.0
    cur = fallback
    for s in steps:
        road = (s.get("road") or "").strip()
        instr = (s.get("instruction") or "").strip()
        label = road or instr or cur
        dist = float(s.get("distance") or 0.0)
        if progress_m <= walked + max(dist, 1.0) + 8.0:
            return label[:28] or fallback
        walked += dist
        cur = label
    return (cur or fallback)[:28]


_SIM_MESSAGES = [
    {"app": "微信", "from": "项目群", "text": "评审材料已更新，请查收"},
    {"app": "短信", "from": "10086", "text": "【提醒】您的套餐流量剩余 3.2GB"},
    {"app": "微信", "from": "同事", "text": "晚点的会议可以线上参加"},
    {"app": "短信", "from": "京东快递", "text": "快件正在派送中，请保持电话畅通"},
]


def _tick_cabin_notifications(state: Dict[str, Any], dt: float) -> None:
    """低频维护连接信号；偶尔追加一条未读消息（不刷屏）。"""
    note = state.setdefault("notifications", {})
    conn = state.setdefault("connectivity", {})
    wifi = conn.setdefault("wifi", {"on": True, "ssid": "手机热点", "signal": 3})
    cell = conn.setdefault("cellular", {"on": True, "type": "5G", "carrier": "中国移动", "signal": 4})
    msgs = note.setdefault("messages", [])

    t = time.time()
    if wifi.get("on"):
        wifi["signal"] = 2 + int((math.sin(t * 0.04) + 1) * 1.5)
    if cell.get("on"):
        cell["signal"] = 3 + int((math.sin(t * 0.03 + 1) + 1))

    acc = float(note.get("_sim_acc") or 0.0) + dt
    note["_sim_acc"] = acc
    unread = sum(1 for m in msgs if isinstance(m, dict) and not m.get("read"))
    # 约 3 分钟才可能来一条，未读不超过 3
    if acc >= 180.0 and unread < 3:
        note["_sim_acc"] = 0.0
        idx = int(note.get("_sim_idx") or 0) + 1
        note["_sim_idx"] = idx
        base = _SIM_MESSAGES[idx % len(_SIM_MESSAGES)]
        msgs.append(
            {
                "id": f"m_{int(t)}_{idx}",
                "app": base["app"],
                "from": base["from"],
                "text": base["text"],
                "read": False,
                "ts": datetime.now().isoformat(timespec="seconds"),
            }
        )
        # 只保留最近 12 条
        if len(msgs) > 12:
            del msgs[:-12]

    if int(note.get("missed_calls") or 0) == 0:
        note["phone_status"] = note.get("phone_status") or "空闲"


def _notifications_summary(note: Dict[str, Any]) -> Dict[str, Any]:
    msgs = [m for m in (note.get("messages") or []) if isinstance(m, dict)]
    unread = [m for m in msgs if not m.get("read")]
    read = [m for m in msgs if m.get("read")]
    return {
        "message_access": bool(note.get("message_access")),
        "unread_count": len(unread),
        "read_count": len(read),
        "unread": [
            {"id": m.get("id"), "app": m.get("app"), "from": m.get("from"), "text": m.get("text")}
            for m in unread[-5:]
        ],
        "recent_read": [
            {"id": m.get("id"), "app": m.get("app"), "from": m.get("from"), "text": m.get("text")}
            for m in read[-3:]
        ],
        "missed_calls": int(note.get("missed_calls") or 0),
        "phone_status": note.get("phone_status") or "空闲",
        "phone_last": note.get("phone_last"),
    }


class StubVehicleGateway(VehicleGateway):
    def __init__(self, state_file: Optional[Path] = None):
        self._lock = threading.RLock()
        self.state_file = Path(state_file) if state_file else None
        self._state = initial_vehicle_state()
        if self.state_file and self.state_file.exists():
            try:
                loaded = json.loads(self.state_file.read_text(encoding="utf-8"))
                if isinstance(loaded, dict) and loaded.get("meta", {}).get("version") == "V2":
                    self._state = loaded
            except Exception:
                pass
        self._persist()

    def _persist(self, force: bool = True) -> None:
        now = time.time()
        if not force:
            last = getattr(self, "_last_persist_ts", 0.0)
            if now - last < 1.2:
                self._persist_dirty = True
                return
        self._persist_dirty = False
        self._last_persist_ts = now
        self._state = touch(self._state)
        if not self.state_file:
            return
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.state_file)

    def snapshot(self) -> Dict[str, Any]:
        with self._lock:
            data = deepcopy(self._state)
            # 曲库只读挂载，不进 vehicle.json，避免状态膨胀
            media = data.setdefault("media", {})
            media["library"] = [
                {
                    "index": i,
                    "artist": s["artist"],
                    "title": s["title"],
                    "album": s.get("album"),
                    "duration_sec": float(s.get("duration_sec") or 0),
                }
                for i, s in enumerate(MUSIC_LIBRARY)
            ]
            media["radio_stations"] = [
                {
                    "index": i,
                    "band": s["band"],
                    "frequency": s["frequency"],
                    "station_name": s["station_name"],
                    "category": s.get("category"),
                }
                for i, s in enumerate(RADIO_STATIONS)
            ]
            return data

    def replace(self, state: Dict[str, Any]) -> None:
        with self._lock:
            self._state = deepcopy(state)
            self._persist()

    def _ensure_cruise_corridor_locked(self, force: bool = False) -> None:
        """确保有一条真实道路折线：北理南门 → 中关村软件园（巡航用，非导航）。"""
        nav = self._state.setdefault("navigation", {})
        if nav.get("navigating") and not force:
            return
        poly = nav.get("polyline") or []
        if not force and len(poly) >= 2 and nav.get("mode") in {"cruising", "navigating"}:
            return
        try:
            from app.maps import plan_drive

            plan = plan_drive("中关村软件园")
            nav["mode"] = "cruising"
            nav["navigating"] = False
            nav["corridor_dest"] = "中关村软件园"
            nav["destination"] = None
            nav["preference"] = "fastest"
            nav["eta_min"] = None
            nav["traffic"] = plan.get("traffic") or "畅通"
            nav["provider"] = plan.get("provider") or "amap"
            nav["origin"] = plan["origin"]
            nav["origin_name"] = plan["origin"]["name"]
            nav["distance_m"] = plan["distance_m"]
            nav["remaining_m"] = plan["distance_m"]
            nav["progress_m"] = 0.0
            nav["duration_sec"] = plan["duration_sec"]
            nav["polyline"] = plan["polyline"]
            nav["steps"] = (plan.get("steps") or [])[:30]
            nav["heading_deg"] = 0.0
            nav["cruise_dir"] = 1
            nav["position"] = plan["position"]
            nav["arrived"] = False
        except Exception as e:
            # 规划失败时至少给南门→软件园示意折线，保证重置后仍能巡航，不静默空折线
            print(f"[cruise] plan_drive failed, using seed corridor: {e}")
            from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE, polyline_length_m

            o = BIT_ZHONGGUANCUN_SOUTH_GATE
            # 中关村软件园一带（GCJ-02 示意点，仅兜底运动，非 POI 推荐）
            seed = [
                [o["lng"], o["lat"]],
                [116.3105, 39.9650],
                [116.3000, 39.9850],
                [116.2900, 40.0200],
                [116.2840, 40.0480],
            ]
            dist = polyline_length_m(seed)
            nav["mode"] = "cruising"
            nav["navigating"] = False
            nav["corridor_dest"] = "中关村软件园"
            nav["destination"] = None
            nav["preference"] = "fastest"
            nav["eta_min"] = None
            nav["traffic"] = "畅通"
            nav["provider"] = "seed"
            nav["origin"] = {
                "name": o["name"],
                "location": o["location"],
                "lng": o["lng"],
                "lat": o["lat"],
            }
            nav["origin_name"] = o["name"]
            nav["distance_m"] = dist
            nav["remaining_m"] = dist
            nav["progress_m"] = 0.0
            nav["duration_sec"] = max(600.0, dist / 12.0)
            nav["polyline"] = seed
            nav["steps"] = []
            nav["heading_deg"] = 0.0
            nav["cruise_dir"] = 1
            nav["position"] = {"lng": o["lng"], "lat": o["lat"], "name": o["name"]}
            nav["arrived"] = False

    def reset(self) -> Dict[str, Any]:
        with self._lock:
            self._state = initial_vehicle_state()
            # 重置 = 北理南门、车速 0 起步，再沿走廊 ACC 加速前往（未开导航）
            dyn = self._state["dynamics"]
            adas = self._state.setdefault("driving", {}).setdefault("adas", {})
            dyn["gear"] = "D"
            dyn["parked"] = False
            dyn["speed_kmh"] = 0.0
            dyn["cruise_set_kmh"] = 65.0
            dyn["cruise_target_kmh"] = 58.0
            adas["acc"] = True
            adas["lane_keep"] = True
            adas["autopark"] = False
            adas["collision_warning"] = True
            self._ensure_cruise_corridor_locked(force=True)
            # 走廊规划后再次钉死：南门 + 进度 0 + 车速 0（防止任何残留）
            from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE

            gate = BIT_ZHONGGUANCUN_SOUTH_GATE
            nav = self._state["navigation"]
            nav["progress_m"] = 0.0
            nav["navigating"] = False
            nav["destination"] = None
            nav["eta_min"] = None
            nav["arrived"] = False
            nav["mode"] = "cruising"
            nav["position"] = {
                "lng": gate["lng"],
                "lat": gate["lat"],
                "name": gate["name"],
            }
            nav["origin_name"] = gate["name"]
            if isinstance(nav.get("remaining_m"), (int, float)) and nav.get("distance_m"):
                nav["remaining_m"] = float(nav["distance_m"])
            dyn["speed_kmh"] = 0.0
            # 重置后原地停 3 秒再 ACC 起步
            dyn["hold_until_ts"] = time.time() + 3.0
            meta = self._state.setdefault("meta", {})
            meta["updated_at"] = datetime.now().isoformat(timespec="seconds")
            meta["revision"] = int(meta.get("revision") or 0) + 1
            self._persist()
            return deepcopy(self._state)

    def hold_departure(self, seconds: float = 2.0) -> Dict[str, Any]:
        """新建会话等：车速钉 0，原地停 seconds 秒后再 ACC 起步。"""
        with self._lock:
            dyn = self._state.setdefault("dynamics", {})
            adas = self._state.setdefault("driving", {}).setdefault("adas", {})
            dyn["gear"] = "D"
            dyn["parked"] = False
            dyn["speed_kmh"] = 0.0
            if dyn.get("cruise_set_kmh") is None:
                dyn["cruise_set_kmh"] = 65.0
            dyn["cruise_target_kmh"] = float(dyn.get("cruise_set_kmh") or 58.0)
            adas.setdefault("acc", True)
            adas["acc"] = True
            adas["autopark"] = False
            self._ensure_cruise_corridor_locked()
            from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE

            gate = BIT_ZHONGGUANCUN_SOUTH_GATE
            nav = self._state.setdefault("navigation", {})
            if not nav.get("navigating"):
                nav["progress_m"] = 0.0
                nav["mode"] = "cruising"
                nav["position"] = {
                    "lng": gate["lng"],
                    "lat": gate["lat"],
                    "name": gate["name"],
                }
                nav["origin_name"] = gate["name"]
                if isinstance(nav.get("distance_m"), (int, float)):
                    nav["remaining_m"] = float(nav["distance_m"])
            dyn["hold_until_ts"] = time.time() + max(0.1, float(seconds))
            self._persist()
            return deepcopy(self._state)

    # -------- climate --------
    def climate_power(self, enable: bool, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            st = self._state
            if enable:
                targets = _normalize_zones(zones, default=ALL_ZONES if zones is None else None)
                if zones is None:
                    targets = list(ALL_ZONES)
                for z in targets:
                    st["climate"]["zones"][z]["on"] = True
                st["climate"]["power"] = True
                self._persist()
                return _ok(f"已打开{_zone_label(targets)}空调", {"zones": targets, "power": True})
            # 关闭
            if zones is None:
                for z in ALL_ZONES:
                    st["climate"]["zones"][z]["on"] = False
                st["climate"]["power"] = False
                self._persist()
                return _ok("已关闭全车空调", {"power": False})
            targets = _normalize_zones(zones)
            for z in targets:
                st["climate"]["zones"][z]["on"] = False
            st["climate"]["power"] = any(st["climate"]["zones"][z]["on"] for z in ALL_ZONES)
            self._persist()
            return _ok(f"已关闭{_zone_label(targets)}空调", {"zones": targets, "power": st["climate"]["power"]})

    def climate_set_temp(self, temperature: float, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            temp = max(16.0, min(30.0, float(temperature)))
            st = self._state
            if zones is None:
                on_zones = [z for z in ALL_ZONES if st["climate"]["zones"][z]["on"]]
                targets = on_zones or ["front_left"]
            else:
                targets = _normalize_zones(zones)
            auto_on = False
            if not st["climate"]["power"]:
                st["climate"]["power"] = True
                auto_on = True
            for z in targets:
                st["climate"]["zones"][z]["temp"] = temp
                st["climate"]["zones"][z]["on"] = True
            self._persist()
            prefix = "空调已自动开启，" if auto_on else ""
            return _ok(f"{prefix}{_zone_label(targets)}温度已设为{temp:.0f}°C", {"temperature": temp, "zones": targets})

    def climate_adjust_temp(self, delta: float, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            st = self._state
            if zones is None:
                on_zones = [z for z in ALL_ZONES if st["climate"]["zones"][z]["on"]]
                targets = on_zones or ["front_left"]
            else:
                targets = _normalize_zones(zones)
            # 用第一个区域当前温度做基准展示
            base = st["climate"]["zones"][targets[0]]["temp"]
            new_temp = max(16.0, min(30.0, float(base) + float(delta)))
        return self.climate_set_temp(new_temp, targets)

    def climate_set_fan(self, level: int, zones: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            level = max(0, min(5, int(level)))
            st = self._state
            if zones is None:
                on_zones = [z for z in ALL_ZONES if st["climate"]["zones"][z]["on"]]
                targets = on_zones or ["front_left"]
            else:
                targets = _normalize_zones(zones)
            if not st["climate"]["power"]:
                st["climate"]["power"] = True
            for z in targets:
                st["climate"]["zones"][z]["fan"] = level
                st["climate"]["zones"][z]["on"] = True if level > 0 else st["climate"]["zones"][z]["on"]
            self._persist()
            return _ok(f"{_zone_label(targets)}风量已调至{level}档", {"level": level, "zones": targets})

    def climate_set_mode(self, mode: str, recirculation: Optional[bool] = None) -> Dict[str, Any]:
        with self._lock:
            mode = str(mode).lower()
            allowed = {"auto", "eco", "comfort", "heat", "cool"}
            if mode not in allowed:
                return _fail(f"不支持的空调模式: {mode}")
            self._state["climate"]["mode"] = mode
            self._state["climate"]["power"] = True
            if recirculation is not None:
                self._state["climate"]["recirculation"] = bool(recirculation)
            self._persist()
            return _ok(f"空调模式已切换为{mode}", {"mode": mode})

    # -------- seats --------
    def seat_set(self, feature: str, enable: bool, level: int = 2, positions: Optional[List[str]] = None, mode: str = "normal") -> Dict[str, Any]:
        with self._lock:
            feature = feature.lower()
            if feature not in {"heat", "ventilation", "massage"}:
                return _fail(f"不支持的座椅功能: {feature}")
            positions = _normalize_zones(positions, default=["front_left"])
            level = 0 if not enable else max(1, min(3, int(level or 2)))
            names = {"heat": "加热", "ventilation": "通风", "massage": "按摩"}
            for p in positions:
                node = self._state["seats"][feature][p]
                node["enable"] = bool(enable)
                node["level"] = level
                if feature == "massage":
                    node["mode"] = mode or "normal"
            self._persist()
            action = "已开启" if enable else "已关闭"
            return _ok(f"{_zone_label(positions)}座椅{names[feature]}{action}", {"feature": feature, "positions": positions, "level": level, "enable": enable})

    def steering_wheel_heat(self, enable: bool, level: int = 2) -> Dict[str, Any]:
        with self._lock:
            level = 0 if not enable else max(1, min(3, int(level or 2)))
            self._state["seats"]["steering_wheel_heat"] = {"enable": bool(enable), "level": level}
            self._persist()
            return _ok("方向盘加热已开启" if enable else "方向盘加热已关闭", {"enable": enable, "level": level})

    # -------- cabin --------
    def set_windows(self, percent: int, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            percent = max(0, min(100, int(percent)))
            if not positions:
                positions = ["front_left"]
            cleaned = []
            for p in positions:
                if p in ("all", "全车"):
                    cleaned = list(WINDOW_POSITIONS)
                    break
                if p == "sunroof" or p in WINDOW_POSITIONS:
                    cleaned.append(p)
            cleaned = list(dict.fromkeys(cleaned)) or ["front_left"]
            for p in cleaned:
                self._state["cabin"]["windows"].setdefault(p, {"percent": 0})["percent"] = percent
            self._persist()
            label = "全车车窗" if set(cleaned) == set(WINDOW_POSITIONS) else "、".join(ZONE_NAMES.get(p, p) for p in cleaned)
            if percent == 0:
                msg = f"{label}已关闭"
            elif percent >= 95:
                msg = f"{label}已完全打开"
            else:
                msg = f"{label}已调节至{percent}%"
            return _ok(msg, {"positions": cleaned, "percent": percent})

    def adjust_windows(self, delta: int, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            if not positions:
                positions = ["front_left"]
            cur = self._state["cabin"]["windows"].get(positions[0], {"percent": 0}).get("percent", 0)
            return self.set_windows(int(cur) + int(delta), positions)

    def set_door_locks(self, locked: bool, positions: Optional[List[str]] = None) -> Dict[str, Any]:
        with self._lock:
            if not positions:
                positions = ["front_left"]
            cleaned = []
            for p in positions:
                if p in ("all", "全车"):
                    cleaned = ["front_left", "front_right", "rear_left", "rear_right"]
                    break
                if p in {"front_left", "front_right", "rear_left", "rear_right"}:
                    cleaned.append(p)
            cleaned = list(dict.fromkeys(cleaned)) or ["front_left"]
            for p in cleaned:
                self._state["cabin"]["doors"][p] = {"locked": bool(locked)}
            self._persist()
            label = "全车车门" if len(cleaned) == 4 else "、".join(ZONE_NAMES.get(p, p) for p in cleaned)
            return _ok(f"{label}已{'上锁' if locked else '解锁'}", {"positions": cleaned, "locked": locked})

    def set_trunk(self, open_: bool) -> Dict[str, Any]:
        with self._lock:
            self._state["cabin"]["trunk"]["open"] = bool(open_)
            self._persist()
            return _ok("后备箱已打开" if open_ else "后备箱已关闭", {"open": open_})

    def set_frunk(self, open_: bool) -> Dict[str, Any]:
        with self._lock:
            self._state["cabin"]["frunk"]["open"] = bool(open_)
            self._persist()
            return _ok("前备箱已打开" if open_ else "前备箱已关闭", {"open": open_})

    def set_charge_port(self, open_: bool) -> Dict[str, Any]:
        with self._lock:
            self._state["cabin"]["charge_port"]["open"] = bool(open_)
            self._persist()
            return _ok("充电口已打开" if open_ else "充电口已关闭", {"open": open_})

    def set_child_lock(self, enable: bool) -> Dict[str, Any]:
        with self._lock:
            self._state["dynamics"]["child_lock"] = bool(enable)
            self._persist()
            return _ok("儿童锁已开启" if enable else "儿童锁已关闭", {"enable": enable})

    def set_light(self, target: str, enable: Optional[bool] = None, brightness: Optional[int] = None, color: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            lights = self._state["cabin"]["lights"]
            if target not in lights:
                return _fail(f"未知灯光目标: {target}")
            node = lights[target]
            if enable is not None:
                node["enable"] = bool(enable)
                if enable and node.get("brightness", 0) == 0:
                    node["brightness"] = 50
                if not enable:
                    node["brightness"] = 0
            if brightness is not None:
                node["brightness"] = max(0, min(100, int(brightness)))
                node["enable"] = node["brightness"] > 0
            if color and target == "ambient":
                node["color"] = color
            self._persist()
            return _ok(f"{target}灯光已更新", {"target": target, **node})

    def set_display_brightness(self, target: str, brightness: int) -> Dict[str, Any]:
        with self._lock:
            displays = self._state["cabin"]["displays"]
            if target not in displays:
                return _fail(f"未知屏幕: {target}")
            brightness = max(0, min(100, int(brightness)))
            displays[target] = {"brightness": brightness}
            self._persist()
            return _ok(f"{target}亮度已设为{brightness}%", {"target": target, "brightness": brightness})

    # -------- media --------
    def _find_song(self, artist: Optional[str], title: Optional[str]):
        artist = (artist or "").strip()
        title = (title or "").strip()
        for i, song in enumerate(MUSIC_LIBRARY):
            if artist and title:
                if song["artist"] == artist and song["title"] == title:
                    return i, song
            elif artist and song["artist"] == artist:
                return i, song
            elif title and song["title"] == title:
                return i, song
        return -1, None

    def _song_payload(self, idx: int, *, playing: bool = True, position_sec: float = 0.0) -> Dict[str, Any]:
        song = MUSIC_LIBRARY[idx]
        dur = float(song.get("duration_sec") or 180)
        pos = max(0.0, min(dur, float(position_sec)))
        return {
            "playing": bool(playing),
            "artist": song["artist"],
            "title": song["title"],
            "album": song["album"],
            "index": idx,
            "position_sec": round(pos, 2),
            "duration_sec": round(dur, 2),
        }

    def _format_clock(self, sec: float) -> str:
        sec = max(0, int(sec))
        return f"{sec // 60}:{sec % 60:02d}"

    def _tick_music_locked(self, dt: float) -> Optional[Dict[str, Any]]:
        """推进播放进度；播完自动下一首。调用方须已持锁。"""
        music = self._state.setdefault("media", {}).setdefault("music", {})
        if not music.get("playing"):
            return None

        idx = int(music.get("index", -1))
        if idx < 0 or idx >= len(MUSIC_LIBRARY):
            return None

        dur = float(music.get("duration_sec") or 0)
        if dur <= 0:
            dur = float(MUSIC_LIBRARY[idx].get("duration_sec") or 180)
            music["duration_sec"] = dur

        pos = float(music.get("position_sec") or 0.0) + float(dt)
        if pos >= dur - 1e-6:
            nxt = (idx + 1) % len(MUSIC_LIBRARY)
            self._state["media"]["music"] = self._song_payload(nxt, playing=True, position_sec=0.0)
            return {"auto_next": True, "music": deepcopy(self._state["media"]["music"])}

        music["position_sec"] = round(pos, 2)
        music["duration_sec"] = round(dur, 2)
        # 补齐可能缺失的元数据
        if not music.get("title"):
            song = MUSIC_LIBRARY[idx]
            music["artist"] = song["artist"]
            music["title"] = song["title"]
            music["album"] = song["album"]
        return {"auto_next": False, "music": deepcopy(music)}

    def play_music(self, artist: Optional[str] = None, title: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            idx, song = self._find_song(artist, title)
            if not song:
                return _fail("音乐库里没有这首歌，请换一首试试")
            self._state["media"]["radio"]["playing"] = False
            self._state["media"]["music"] = self._song_payload(idx, playing=True, position_sec=0.0)
            self._persist()
            m = self._state["media"]["music"]
            return _ok(
                f"正在播放 {m['artist']} - {m['title']}",
                {**song, "position_sec": m["position_sec"], "duration_sec": m["duration_sec"]},
            )

    def control_music(self, action: str) -> Dict[str, Any]:
        with self._lock:
            action = action.lower()
            music = self._state["media"]["music"]
            if action == "play":
                if music.get("index", -1) < 0:
                    return self.play_music("周杰伦", "晴天")
                music["playing"] = True
                if not music.get("duration_sec"):
                    idx = int(music.get("index", 0))
                    music["duration_sec"] = float(MUSIC_LIBRARY[idx].get("duration_sec") or 180)
                self._persist()
                return _ok(f"继续播放 {music.get('artist')} - {music.get('title')}", deepcopy(music))
            if action == "pause":
                music["playing"] = False
                self._persist()
                return _ok("音乐已暂停", deepcopy(music))
            if action == "stop":
                music["playing"] = False
                music["position_sec"] = 0.0
                self._persist()
                return _ok("音乐已停止", deepcopy(music))
            return _fail(f"不支持的音乐操作: {action}")

    def switch_music(self, direction: str) -> Dict[str, Any]:
        with self._lock:
            direction = direction.lower()
            cur = self._state["media"]["music"].get("index", -1)
            if cur < 0:
                cur = 0
            if direction in {"next", "下一首"}:
                cur = (cur + 1) % len(MUSIC_LIBRARY)
            else:
                cur = (cur - 1) % len(MUSIC_LIBRARY)
            self._state["media"]["radio"]["playing"] = False
            self._state["media"]["music"] = self._song_payload(cur, playing=True, position_sec=0.0)
            self._persist()
            m = self._state["media"]["music"]
            return _ok(f"已切换到 {m['artist']} - {m['title']}", deepcopy(m))

    def seek_music(
        self,
        position_sec: Optional[float] = None,
        delta_sec: Optional[float] = None,
        percent: Optional[float] = None,
    ) -> Dict[str, Any]:
        """跳转进度：绝对秒 / 相对秒 / 百分比（0-100）。"""
        with self._lock:
            music = self._state["media"]["music"]
            idx = int(music.get("index", -1))
            if idx < 0 or idx >= len(MUSIC_LIBRARY):
                # 尚未选歌时先起播默认曲
                boot = self.play_music("周杰伦", "晴天")
                if not boot.get("success"):
                    return boot
                music = self._state["media"]["music"]
                idx = int(music.get("index", 0))

            dur = float(music.get("duration_sec") or MUSIC_LIBRARY[idx].get("duration_sec") or 180)
            music["duration_sec"] = dur
            cur = float(music.get("position_sec") or 0.0)

            if position_sec is not None:
                target = float(position_sec)
            elif percent is not None:
                target = dur * (max(0.0, min(100.0, float(percent))) / 100.0)
            elif delta_sec is not None:
                target = cur + float(delta_sec)
            else:
                return _fail("请指定进度：position_sec / delta_sec / percent")

            target = max(0.0, min(dur, target))
            # 拖到结尾视为切下一首
            if target >= dur - 0.05:
                nxt = (idx + 1) % len(MUSIC_LIBRARY)
                self._state["media"]["radio"]["playing"] = False
                self._state["media"]["music"] = self._song_payload(nxt, playing=True, position_sec=0.0)
                self._persist()
                m = self._state["media"]["music"]
                return _ok(f"已到曲末，切换到 {m['artist']} - {m['title']}", deepcopy(m))

            music["position_sec"] = round(target, 2)
            music["playing"] = True
            self._state["media"]["radio"]["playing"] = False
            self._persist()
            m = deepcopy(music)
            return _ok(
                f"进度已调到 {self._format_clock(m['position_sec'])} / {self._format_clock(dur)}",
                m,
            )

    def play_radio(self, station_name: Optional[str] = None, category: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            station = None
            idx = -1
            for i, s in enumerate(RADIO_STATIONS):
                if station_name and s["station_name"] == station_name:
                    station, idx = s, i
                    break
                if category and s["category"] == category and station is None:
                    station, idx = s, i
            if station is None:
                station, idx = RADIO_STATIONS[0], 0
            self._state["media"]["music"]["playing"] = False
            self._state["media"]["radio"] = {
                "playing": True,
                "band": station["band"],
                "frequency": station["frequency"],
                "station_name": station["station_name"],
                "index": idx,
            }
            self._persist()
            return _ok(f"正在收听 {station['station_name']} {station['band']}{station['frequency']}", station)

    def control_radio(self, action: str) -> Dict[str, Any]:
        with self._lock:
            action = action.lower()
            radio = self._state["media"]["radio"]
            if action == "stop":
                radio["playing"] = False
                self._persist()
                return _ok("电台已停止", radio)
            if action == "play":
                if radio.get("index", -1) < 0:
                    return self.play_radio()
                radio["playing"] = True
                self._state["media"]["music"]["playing"] = False
                self._persist()
                return _ok(f"继续收听 {radio.get('station_name')}", radio)
            return _fail(f"不支持的电台操作: {action}")

    def switch_radio(self, direction: str) -> Dict[str, Any]:
        with self._lock:
            radio = self._state["media"]["radio"]
            cur = int(radio.get("index", -1))
            if cur < 0 or cur >= len(RADIO_STATIONS):
                cur = 0
            elif str(direction).lower() in ("next", "下一个", "下"):
                cur = (cur + 1) % len(RADIO_STATIONS)
            else:
                cur = (cur - 1) % len(RADIO_STATIONS)
            station = RADIO_STATIONS[cur]
            self._state["media"]["music"]["playing"] = False
            self._state["media"]["radio"] = {
                "playing": True,
                "band": station["band"],
                "frequency": station["frequency"],
                "station_name": station["station_name"],
                "index": cur,
            }
            self._persist()
            return _ok(
                f"已切换到 {station['station_name']} {station['band']}{station['frequency']}",
                deepcopy(self._state["media"]["radio"]),
            )

    def set_volume(self, volume: Optional[int] = None, delta: Optional[int] = None, muted: Optional[bool] = None) -> Dict[str, Any]:
        with self._lock:
            media = self._state["media"]
            if muted is not None:
                media["muted"] = bool(muted)
            if volume is not None:
                media["volume"] = max(0, min(100, int(volume)))
            elif delta is not None:
                media["volume"] = max(0, min(100, int(media.get("volume", 50)) + int(delta)))
            self._persist()
            if media["muted"]:
                return _ok("已静音", media)
            return _ok(f"音量已设为{media['volume']}", {"volume": media["volume"], "muted": media["muted"]})

    # -------- nav / driving / apps --------
    def navigate_to(
        self,
        destination: str,
        preference: str = "fastest",
        origin: Optional[str] = None,
        destination_location: Optional[str] = None,
    ) -> Dict[str, Any]:
        destination = (destination or "").strip()
        if not destination:
            return _fail("请告诉我目的地")
        from app.nlu.destination_guard import (
            is_relative_or_category_destination,
            relative_destination_block_message,
            strip_compound_tail_from_destination,
        )

        destination = strip_compound_tail_from_destination(destination)
        if not destination:
            return _fail("请告诉我目的地")
        try:
            from app.maps.amap_mcp import _normalize_place_query

            destination = _normalize_place_query(destination)
        except Exception:
            pass

        if is_relative_or_category_destination(destination):
            return _fail(
                relative_destination_block_message(destination),
                {"blocked_relative_destination": True, "destination": destination},
            )
        origin_name = (origin or "").strip() or None
        dest_loc = (destination_location or "").strip()

        with self._lock:
            cur = deepcopy((self._state.get("navigation") or {}).get("position") or {})
            cur_speed = float((self._state.get("dynamics") or {}).get("speed_kmh") or 0.0)

        try:
            from app.maps import (
                SOUTH_GATE_ALIASES,
                PlaceAmbiguousError,
                plan_drive,
                plan_drive_from_coords,
            )
            from app.maps.amap_mcp import maps_direction_driving, polyline_length_m

            # 候选澄清后已带坐标：直接规划，禁止再全文检索歧义
            if dest_loc and "," in dest_loc:
                if origin_name and origin_name in SOUTH_GATE_ALIASES:
                    from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE

                    o = BIT_ZHONGGUANCUN_SOUTH_GATE
                    origin_loc = o["location"]
                    oname = o["name"]
                elif cur.get("lng") is not None and cur.get("lat") is not None:
                    origin_loc = f"{float(cur['lng']):.6f},{float(cur['lat']):.6f}"
                    oname = str(cur.get("name") or origin_name or "当前位置")
                else:
                    from app.maps import BIT_ZHONGGUANCUN_SOUTH_GATE

                    o = BIT_ZHONGGUANCUN_SOUTH_GATE
                    origin_loc = o["location"]
                    oname = o["name"]
                route = maps_direction_driving(origin_loc, dest_loc)
                path0 = ((route.get("route") or {}).get("paths") or [{}])[0]
                distance = float(path0.get("distance") or 0)
                duration = float(path0.get("duration") or 0)
                polyline = path0.get("polyline") or []
                if not polyline:
                    olng, olat = [float(x) for x in origin_loc.split(",")]
                    dlng, dlat = [float(x) for x in dest_loc.split(",")]
                    polyline = [[olng, olat], [dlng, dlat]]
                    if distance <= 0:
                        distance = polyline_length_m(polyline)
                    if duration <= 0:
                        duration = max(60.0, distance / 10.0)
                olng, olat = [float(x) for x in origin_loc.split(",")]
                dlng, dlat = [float(x) for x in dest_loc.split(",")]
                plan = {
                    "origin": {"name": oname, "location": origin_loc, "lng": olng, "lat": olat},
                    "destination": {
                        "name": destination,
                        "location": dest_loc,
                        "lng": dlng,
                        "lat": dlat,
                    },
                    "distance_m": distance,
                    "duration_sec": duration,
                    "eta_min": max(1, int(round(duration / 60.0))),
                    "steps": path0.get("steps") or [],
                    "polyline": polyline,
                    "progress_m": 0.0,
                    "remaining_m": distance,
                    "position": {"lng": olng, "lat": olat, "name": oname},
                    "traffic": "畅通",
                    "provider": "amap",
                }
            # 优先：用户指定起点 → 否则从当前定位接续规划（巡航切导航不断档）
            elif origin_name and origin_name in SOUTH_GATE_ALIASES:
                plan = plan_drive(destination, origin_name=origin_name)
            elif origin_name:
                plan = plan_drive(destination, origin_name=origin_name)
            elif cur.get("lng") is not None and cur.get("lat") is not None:
                loc = f"{float(cur['lng']):.6f},{float(cur['lat']):.6f}"
                label = str(cur.get("name") or "当前位置")
                plan = plan_drive_from_coords(loc, destination, origin_name=label)
            else:
                plan = plan_drive(destination, origin_name=None)
        except PlaceAmbiguousError as e:
            cands = []
            for i, p in enumerate(e.candidates[:4], 1):
                addr = (p.get("address") or "").strip()
                cands.append(
                    {
                        "index": i,
                        "name": p.get("name"),
                        "address": addr,
                        "location": p.get("location"),
                    }
                )
            # 工具摘要只给内部/依据用，禁止写进用户口语的开发者指令
            names = "、".join(str(c.get("name") or "") for c in cands if c.get("name"))
            return _ok(
                f"目的地「{e.query}」有多处（{names}），需用户选定后再导航。",
                {
                    "need_clarify": True,
                    "query": e.query,
                    "candidates": cands,
                    "navigating": False,
                },
            )
        except Exception as e:
            err = str(e)
            if "找不到地点" in err or "地理编码" in err or "ENGINE_RESPONSE" in err:
                return _fail(
                    f"没找到「{destination}」对应的地点。请反问用户换个更具体的名字再试。"
                )
            return _fail(
                "导航暂时没规划成功。换个更具体的地名再试。",
                {"error": str(e)[:800]},
            )

        with self._lock:
            dyn = self._state["dynamics"]
            adas = self._state.setdefault("driving", {}).setdefault("adas", {})
            dyn["gear"] = "D"
            dyn["parked"] = False
            # 保持当前车速连续，不瞬间清零
            dyn["speed_kmh"] = cur_speed
            dist = float(plan.get("distance_m") or 0)
            cruise = 55.0 if dist < 5000 else 65.0 if dist < 15000 else 75.0
            dyn["cruise_set_kmh"] = cruise
            dyn["cruise_target_kmh"] = max(35.0, cruise * 0.9)
            adas["acc"] = True
            adas["autopark"] = False
            if not adas.get("lane_keep"):
                adas["lane_keep"] = True

            self._state["navigation"] = {
                "navigating": True,
                "mode": "navigating",
                "destination": plan["destination"]["name"],
                "corridor_dest": "中关村软件园",
                "preference": preference or "fastest",
                "eta_min": plan["eta_min"],
                "traffic": plan.get("traffic") or "畅通",
                "provider": plan.get("provider") or "amap",
                "origin": plan["origin"],
                "origin_name": plan["origin"]["name"],
                "distance_m": plan["distance_m"],
                "remaining_m": plan["remaining_m"],
                "progress_m": 0.0,
                "duration_sec": plan["duration_sec"],
                "polyline": plan["polyline"],
                "steps": plan["steps"][:40],
                "heading_deg": float((self._state.get("navigation") or {}).get("heading_deg") or 0.0),
                "cruise_dir": 1,
                "position": plan["position"],
                "arrived": False,
            }
            self._persist()
            return _ok(
                f"已切换导航，前往{plan['destination']['name']}，约 {plan['eta_min']} 分钟 · {plan['distance_m']/1000:.1f} 公里",
                self._state["navigation"],
            )

    def stop_navigation(self) -> Dict[str, Any]:
        with self._lock:
            nav = self._state.setdefault("navigation", {})
            pos = nav.get("position") or {
                "lng": 116.316356,
                "lat": 39.957053,
                "name": "北京理工大学中关村校区南门",
            }
            heading = float(nav.get("heading_deg") or 90.0)
            dyn = self._state["dynamics"]
            adas = self._state.setdefault("driving", {}).setdefault("adas", {})
            # 结束导航 → 切回路廊道路巡航（继续沿真实道路开，不是乱逛）
            if not (dyn.get("parked") or str(dyn.get("gear") or "P").upper() == "P"):
                dyn["gear"] = "D"
                dyn["parked"] = False
                if dyn.get("cruise_set_kmh") is None:
                    dyn["cruise_set_kmh"] = 65.0
                if dyn.get("cruise_target_kmh") is None and adas.get("acc"):
                    dyn["cruise_target_kmh"] = 58.0
                nav_mode = "cruising"
            else:
                nav_mode = "parked"

            self._state["navigation"] = {
                "navigating": False,
                "mode": nav_mode,
                "destination": None,
                "corridor_dest": "中关村软件园",
                "preference": "fastest",
                "eta_min": None,
                "traffic": nav.get("traffic") or "畅通",
                "provider": nav.get("provider"),
                "origin": nav.get("origin"),
                "origin_name": str(pos.get("name") or "当前位置"),
                "distance_m": nav.get("distance_m"),
                "remaining_m": nav.get("remaining_m"),
                "progress_m": float(nav.get("progress_m") or 0.0),
                "duration_sec": nav.get("duration_sec"),
                "polyline": nav.get("polyline") or [],
                "steps": nav.get("steps") or [],
                "heading_deg": heading,
                "cruise_dir": int(nav.get("cruise_dir") or 1),
                "position": pos,
                "arrived": False,
            }
            if nav_mode == "cruising" and len(self._state["navigation"].get("polyline") or []) < 2:
                self._ensure_cruise_corridor_locked(force=True)
                # 尽量接续当前位置：把 progress 钳到走廊上
                self._state["navigation"]["position"] = pos
            self._persist()
            return _ok("已结束导航，继续道路巡航", self._state["navigation"])

    def search_nearby(
        self,
        keywords: str,
        radius: int = 3000,
        types: str = "",
    ) -> Dict[str, Any]:
        keywords = (keywords or "").strip()
        if not keywords:
            return _fail("请告诉我要找什么，比如美食、充电站")
        with self._lock:
            nav = self._state.get("navigation") or {}
            pos = nav.get("position") or {}
            lng = pos.get("lng")
            lat = pos.get("lat")
            mode = nav.get("mode") or ("navigating" if nav.get("navigating") else "cruising")
        if lng is None or lat is None:
            return _fail("当前没有定位，没法搜附近。定位出来后再说一声就行。")
        try:
            from app.maps import maps_around_search

            data = maps_around_search(
                f"{float(lng):.6f},{float(lat):.6f}",
                keywords,
                radius=max(500, min(10000, int(radius or 3000))),
                types=types or "",
                offset=8,
            )
        except Exception as e:
            return _fail(
                f"地图服务连不上，没法查附近「{keywords}」。",
                {"error": str(e)[:800]},
            )

        pois = data.get("pois") or []
        if not pois:
            return _ok(
                f"附近暂时没有与「{keywords}」相关的地点。",
                {**data, "mode": mode, "center": {"lng": lng, "lat": lat}},
            )
        # 完整 POI 只进依据面板；工具 message 不进对话框
        recommend_n = 3
        top = pois[:recommend_n]
        names = [str(p.get("name") or "").strip() for p in top if p.get("name")]
        return _ok(
            f"附近「{keywords}」检索完成，候选 {len(names)} 家（详见依据面板）。",
            {
                **data,
                "mode": mode,
                "center": {"lng": lng, "lat": lat},
                "recommend_n": recommend_n,
                "recommend_pois": top,
            },
        )

    def set_adas(self, feature: str, enable: bool) -> Dict[str, Any]:
        with self._lock:
            mapping = {
                "autohold": "auto_hold",
                "auto_hold": "auto_hold",
                "cruise": "acc",
                "acc": "acc",
                "autopark": "autopark",
                "auto_park": "autopark",
                "lane_keep": "lane_keep",
                "collision_warning": "collision_warning",
            }
            key = mapping.get(feature.lower())
            if not key:
                return _fail(f"未知ADAS功能: {feature}")

            adas = self._state["driving"]["adas"]
            dyn = self._state["dynamics"]
            speed = float(dyn.get("speed_kmh") or 0.0)
            gear = str(dyn.get("gear") or "P").upper()
            parked = bool(dyn.get("parked"))
            notes: list[str] = []

            names = {
                "auto_hold": "自动驻车",
                "acc": "自适应巡航",
                "autopark": "自动泊车",
                "lane_keep": "车道保持",
                "collision_warning": "碰撞预警",
            }

            # —— 真实互斥与前置条件 ——
            nav = self._state.setdefault("navigation", {})
            if key == "acc" and enable:
                if adas.get("autopark"):
                    return _fail("自动泊车进行中，无法开启自适应巡航。请先退出自动泊车。")
                if parked or gear == "P":
                    dyn["gear"] = "D"
                    dyn["parked"] = False
                    notes.append("已挂入 D 挡")
                adas["autopark"] = False
                if dyn.get("cruise_set_kmh") is None:
                    dyn["cruise_set_kmh"] = 65.0
                if dyn.get("cruise_target_kmh") is None:
                    dyn["cruise_target_kmh"] = float(dyn["cruise_set_kmh"]) * 0.9
                if not nav.get("navigating"):
                    nav["mode"] = "cruising"
                    self._ensure_cruise_corridor_locked()

            elif key == "lane_keep" and enable:
                if adas.get("autopark"):
                    return _fail("自动泊车进行中，无法开启车道保持。")
                if parked or gear == "P":
                    return _fail("驻车状态下无法开启车道保持，请先挂入 D 挡起步。")

            elif key == "autopark" and enable:
                if speed > 8.0:
                    return _fail(
                        f"车速过高（当前 {speed:.0f} km/h），请先减速至约 5 km/h 以内再启动自动泊车。"
                    )
                if adas.get("acc") or dyn.get("cruise_target_kmh") is not None:
                    adas["acc"] = False
                    dyn["cruise_target_kmh"] = None
                    notes.append("已退出自适应巡航")
                if adas.get("lane_keep"):
                    adas["lane_keep"] = False
                    notes.append("已退出车道保持")
                # 泊车接管：低速入库，不进入巡航
                dyn["parked"] = False
                if gear == "P":
                    dyn["gear"] = "R"
                    notes.append("已挂入 R 挡准备入库")
                nav["mode"] = "parked" if speed < 0.5 else nav.get("mode") or "cruising"

            elif key == "auto_hold" and enable:
                # Auto Hold：红灯刹停时保持制动，绝不是切 P 挡
                if adas.get("autopark"):
                    return _fail("自动泊车进行中，无需同时开启自动驻车。")
                if parked or gear == "P":
                    return _fail("已在 P 挡驻车，自动驻车无需开启。")

            elif key == "acc" and not enable:
                dyn["cruise_target_kmh"] = None

            elif key == "autopark" and not enable:
                # 退出自动泊车：若已接近静止则收尾为 P
                if speed < 1.0:
                    dyn["parked"] = True
                    dyn["gear"] = "P"
                    dyn["speed_kmh"] = 0.0
                    nav["mode"] = "parked"
                elif not nav.get("navigating"):
                    nav["mode"] = "cruising"

            adas[key] = bool(enable)
            self._persist()
            extra = ""
            if key == "acc" and enable:
                extra = f"，设定 {float(dyn.get('cruise_set_kmh') or dyn.get('cruise_target_kmh') or 65):.0f} km/h（跟车会随路况起伏）"
            if notes:
                extra += "（" + "；".join(notes) + "）"
            return _ok(
                f"{names[key]}已{'开启' if enable else '关闭'}{extra}",
                {
                    "feature": key,
                    "enable": enable,
                    "cruise_target_kmh": dyn.get("cruise_target_kmh"),
                    "adas": dict(adas),
                    "notes": notes,
                },
            )

    def set_speed(
        self,
        speed_kmh: float,
        gear: Optional[str] = None,
        parked: Optional[bool] = None,
    ) -> Dict[str, Any]:
        with self._lock:
            dyn = self._state["dynamics"]
            adas = self._state.setdefault("driving", {}).setdefault("adas", {})
            speed = max(0.0, min(180.0, float(speed_kmh)))
            notes: list[str] = []

            if gear is not None:
                g = str(gear).upper()
                if g not in {"P", "R", "N", "D"}:
                    return _fail(f"无效挡位: {gear}")
                dyn["gear"] = g
                if g == "P":
                    dyn["parked"] = True
                    dyn["cruise_target_kmh"] = None
                    dyn["speed_kmh"] = 0.0
                    adas["acc"] = False
                    adas["lane_keep"] = False
                    self._state.setdefault("navigation", {})["mode"] = "parked"
                    self._state["navigation"]["navigating"] = False
                    self._persist()
                    return _ok(
                        "已进入驻车，车速为 0",
                        {"speed_kmh": 0.0, "gear": "P", "parked": True},
                    )

            if parked is True:
                dyn["parked"] = True
                dyn["gear"] = "P"
                dyn["cruise_target_kmh"] = None
                dyn["speed_kmh"] = 0.0
                adas["acc"] = False
                adas["lane_keep"] = False
                adas["autopark"] = False
                self._state.setdefault("navigation", {})["mode"] = "parked"
                self._state["navigation"]["navigating"] = False
                self._persist()
                return _ok(
                    "已进入驻车，车速为 0",
                    {"speed_kmh": 0.0, "gear": "P", "parked": True},
                )

            # 非零目标车速：退出驻车 + 开启巡航，仪表才会持续显示并爬升到目标
            if speed > 0:
                nav = self._state.setdefault("navigation", {})
                if adas.get("autopark"):
                    adas["autopark"] = False
                    notes.append("已退出自动泊车")
                was_parked = bool(dyn.get("parked")) or str(dyn.get("gear") or "P").upper() == "P"
                if was_parked:
                    dyn["gear"] = "D"
                    dyn["parked"] = False
                    notes.append("已挂入 D 挡")
                elif parked is False:
                    dyn["parked"] = False
                adas["acc"] = True
                dyn["cruise_set_kmh"] = round(speed, 2)
                dyn["cruise_target_kmh"] = round(max(12.0, speed * 0.85), 2)
                # 从静止起步不瞬移到目标，交给 tick 爬升
                if was_parked or float(dyn.get("speed_kmh") or 0.0) < 0.3:
                    dyn["speed_kmh"] = 0.0
                if not nav.get("navigating"):
                    nav["mode"] = "cruising"
                    self._ensure_cruise_corridor_locked()
                notes.append(f"ACC 设定 {speed:.0f} km/h")
                self._persist()
                msg = f"已设定目标车速 {speed:.0f} km/h"
                if notes:
                    msg += "（" + "，".join(notes) + "）"
                return _ok(
                    msg,
                    {
                        "speed_kmh": dyn.get("speed_kmh"),
                        "cruise_target_kmh": dyn.get("cruise_target_kmh"),
                        "gear": dyn.get("gear"),
                        "parked": dyn.get("parked"),
                        "acc": True,
                    },
                )

            # speed == 0：减速/退出巡航；中控“退出驻车”会带 gear=D, parked=false
            dyn["speed_kmh"] = 0.0
            dyn["cruise_target_kmh"] = None
            adas["acc"] = False
            if parked is False:
                dyn["parked"] = False
                if gear is not None:
                    dyn["gear"] = str(gear).upper()
                elif str(dyn.get("gear") or "P").upper() == "P":
                    dyn["gear"] = "D"
                nav = self._state.setdefault("navigation", {})
                if not nav.get("navigating"):
                    nav["mode"] = "cruising"
            self._persist()
            return _ok(
                "车速已更新为 0 km/h",
                {"speed_kmh": 0.0, "gear": dyn.get("gear"), "parked": dyn.get("parked")},
            )

    def tick_dynamics(self, dt: float = 0.25) -> Dict[str, Any]:
        """道路巡航 / 导航 / 驻车：车速与地图位移一体。"""
        with self._lock:
            dt = max(0.05, min(1.0, float(dt)))
            dyn = self._state.setdefault("dynamics", {})
            adas = self._state.setdefault("driving", {}).setdefault("adas", {})
            nav = self._state.setdefault("navigation", {})
            speed = float(dyn.get("speed_kmh") or 0.0)
            parked = bool(dyn.get("parked"))
            gear = str(dyn.get("gear") or "P").upper()
            autopark = bool(adas.get("autopark"))

            # 重置后原地保持：车速钉 0、不挪位置
            hold_until = dyn.get("hold_until_ts")
            if isinstance(hold_until, (int, float)) and time.time() < float(hold_until):
                dyn["speed_kmh"] = 0.0
                dyn["cruise_target_kmh"] = float(dyn.get("cruise_set_kmh") or dyn.get("cruise_target_kmh") or 58.0)
                if not nav.get("navigating"):
                    nav["mode"] = "cruising"
                music_tick = self._tick_music_locked(dt)
                self._persist(force=False)
                return _ok(
                    "hold",
                    {
                        "speed_kmh": 0.0,
                        "gear": gear,
                        "parked": parked,
                        "holding": True,
                        "hold_remain_s": max(0.0, float(hold_until) - time.time()),
                        "navigation": {
                            "navigating": bool(nav.get("navigating")),
                            "mode": nav.get("mode"),
                            "position": nav.get("position"),
                            "progress_m": nav.get("progress_m"),
                            "remaining_m": nav.get("remaining_m"),
                        },
                        "music": music_tick.get("music") if music_tick else self._state["media"].get("music"),
                    },
                )
            if hold_until is not None:
                dyn.pop("hold_until_ts", None)

            # ACC：设定车速 + 路况起伏跟驰（不是匀速钉死）
            if dyn.get("cruise_set_kmh") is None and dyn.get("cruise_target_kmh") is not None:
                dyn["cruise_set_kmh"] = float(dyn["cruise_target_kmh"])
            cruise_set = dyn.get("cruise_set_kmh")
            acc_on = bool(adas.get("acc")) and cruise_set is not None and not autopark

            if autopark and (cruise_set is not None or dyn.get("cruise_target_kmh") is not None):
                dyn["cruise_target_kmh"] = None
                dyn["cruise_set_kmh"] = None
                adas["acc"] = False
                cruise_set = None
                acc_on = False

            if parked or gear == "P":
                target = 0.0
                rate = 22.0
            elif autopark:
                target = 0.0
                rate = 14.0
            elif acc_on:
                set_spd = max(40.0, float(cruise_set))
                t = time.time()
                # 跟车起伏：设定附近波动，均速约 0.9×设定（65→约 58–68）
                wave = 0.82 + 0.16 * (0.5 + 0.5 * math.sin(t * 0.22)) + 0.08 * math.sin(t * 0.55)
                dip = 1.0 - 0.22 * (max(0.0, math.sin(t * 0.09)) ** 5)
                live = max(35.0, min(set_spd + 4.0, set_spd * wave * dip))
                dyn["cruise_target_kmh"] = round(live, 1)
                target = live
                rate = 12.0 if speed < target else 14.0
            else:
                target = max(0.0, speed - 1.2 * dt)
                rate = 4.0

            diff = target - speed
            step = max(-rate * dt, min(rate * dt, diff))
            speed = speed + step
            # 轻微噪声，避免像仪表被钉死
            if acc_on and speed > 5:
                speed += math.sin(time.time() * 1.7) * 0.35

            speed = max(0.0, min(180.0, speed))
            dyn["speed_kmh"] = round(speed, 2)
            if speed < 0.3 and (parked or gear == "P" or autopark):
                dyn["speed_kmh"] = 0.0
                speed = 0.0
                if autopark:
                    dyn["parked"] = True
                    dyn["gear"] = "P"
                    parked = True
                    gear = "P"

            # 未开导航时，确保在「北理→软件园」真实道路上巡航
            if not nav.get("navigating") and not (parked or gear == "P") and not autopark:
                self._ensure_cruise_corridor_locked()

            if parked or gear == "P":
                nav["mode"] = "parked"
            elif autopark:
                pass
            elif nav.get("navigating") and nav.get("polyline"):
                nav["mode"] = "navigating"
            elif speed >= 0.3:
                nav["mode"] = "cruising"
            else:
                if not nav.get("navigating"):
                    nav["mode"] = "cruising"

            if not autopark and not (parked or gear == "P") and speed >= 0.15:
                try:
                    from app.maps import advance_along_polyline_with_heading

                    poly = nav.get("polyline") or []
                    if len(poly) >= 2:
                        move = max(0.0, speed) / 3.6 * dt
                        direction = int(nav.get("cruise_dir") or 1)
                        if direction >= 0:
                            direction = 1
                        else:
                            direction = -1

                        if nav.get("navigating"):
                            progress = float(nav.get("progress_m") or 0.0) + move
                            pos, walked, remain, heading = advance_along_polyline_with_heading(poly, progress)
                            nav["progress_m"] = round(walked, 2)
                            nav["remaining_m"] = round(remain, 2)
                            nav["heading_deg"] = round(heading, 1)
                            nav["position"] = {
                                "lng": pos[0],
                                "lat": pos[1],
                                "name": nav.get("destination") or (nav.get("position") or {}).get("name"),
                            }
                            if remain <= 8.0:
                                # 导航到达 → 原地驻车，等下次导航指令再起步
                                dest_name = str(
                                    nav.get("destination")
                                    or (nav.get("position") or {}).get("name")
                                    or "目的地"
                                )
                                nav["arrived"] = True
                                nav["navigating"] = False
                                nav["mode"] = "parked"
                                nav["eta_min"] = 0
                                nav["remaining_m"] = 0.0
                                nav["position"] = {
                                    "lng": pos[0],
                                    "lat": pos[1],
                                    "name": dest_name,
                                }
                                dyn["gear"] = "P"
                                dyn["parked"] = True
                                dyn["speed_kmh"] = 0.0
                                dyn["cruise_target_kmh"] = None
                                adas["acc"] = False
                                speed = 0.0
                                parked = True
                                gear = "P"
                            else:
                                nav["arrived"] = False
                                # ETA：优先按「规划总时长 × 剩余比例」衰减，避免跟瞬时车速一起乱跳
                                # （演示车速有跟车起伏，用 v 瞬时反推会上下跳动很大）
                                total_m = float(nav.get("distance_m") or 0.0) or 1.0
                                plan_dur = float(nav.get("duration_sec") or 0.0)
                                if plan_dur > 0:
                                    raw_min = (remain / total_m) * (plan_dur / 60.0)
                                else:
                                    ref_spd = float(
                                        dyn.get("cruise_set_kmh")
                                        or dyn.get("cruise_target_kmh")
                                        or max(35.0, speed)
                                    )
                                    ref_spd = max(25.0, ref_spd)
                                    raw_min = (remain / (ref_spd / 3.6)) / 60.0
                                prev = nav.get("eta_min")
                                if isinstance(prev, (int, float)) and prev > 0:
                                    # 轻平滑，且限制上跳（真实导航 ETA 也不会因瞬时速突然大幅变长）
                                    blended = 0.82 * float(prev) + 0.18 * raw_min
                                    if blended > float(prev) + 0.8:
                                        blended = float(prev) + 0.25
                                    nav["eta_min"] = max(1, int(round(blended)))
                                else:
                                    nav["eta_min"] = max(1, int(round(raw_min)))
                                place = _place_name_along_steps(
                                    nav.get("steps") or [],
                                    walked,
                                    fallback=str(nav.get("destination") or "导航中"),
                                )
                                nav["position"]["name"] = place
                        else:
                            # 道路走廊：仅约束轨迹，不是导航
                            total = float(nav.get("distance_m") or 0.0)
                            if total <= 1:
                                from app.maps import polyline_length_m

                                total = polyline_length_m(poly)
                                nav["distance_m"] = total
                            progress = float(nav.get("progress_m") or 0.0) + move * direction
                            if progress >= total:
                                progress = total
                                direction = -1
                            elif progress <= 0:
                                progress = 0.0
                                direction = 1
                            nav["cruise_dir"] = direction
                            pos, walked, remain, heading = advance_along_polyline_with_heading(poly, progress)
                            if direction < 0:
                                heading = (heading + 180.0) % 360.0
                            nav["progress_m"] = round(walked, 2)
                            nav["remaining_m"] = round(max(0.0, total - walked), 2)
                            nav["heading_deg"] = round(heading, 1)
                            nav["mode"] = "cruising"
                            place = _place_name_along_steps(
                                nav.get("steps") or [],
                                walked,
                                fallback="当前位置",
                            )
                            nav["position"] = {
                                "lng": pos[0],
                                "lat": pos[1],
                                "name": place,
                            }
                            nav["arrived"] = False
                except Exception:
                    pass

            _tick_cabin_notifications(self._state, dt)

            music_tick = self._tick_music_locked(dt)
            self._persist(force=False)
            return _ok(
                "dynamics tick",
                {
                    "speed_kmh": speed,
                    "gear": gear,
                    "parked": parked,
                    "cruise_set_kmh": dyn.get("cruise_set_kmh"),
                    "cruise_target_kmh": dyn.get("cruise_target_kmh"),
                    "acc": acc_on,
                    "autopark": autopark,
                    "navigation": {
                        "navigating": bool(nav.get("navigating")),
                        "mode": nav.get("mode"),
                        "position": nav.get("position"),
                        "heading_deg": nav.get("heading_deg"),
                        "progress_m": nav.get("progress_m"),
                        "remaining_m": nav.get("remaining_m"),
                        "eta_min": nav.get("eta_min"),
                        "arrived": bool(nav.get("arrived")),
                        "corridor_dest": nav.get("corridor_dest"),
                    }
                    if isinstance(nav, dict)
                    else None,
                    "music": music_tick.get("music") if music_tick else self._state["media"].get("music"),
                    "music_auto_next": bool(music_tick and music_tick.get("auto_next")),
                },
            )

    def set_drive_mode(self, mode: str) -> Dict[str, Any]:
        with self._lock:
            mode = mode.lower()
            if mode not in {"comfort", "sport", "eco", "standard"}:
                return _fail(f"不支持的驾驶模式: {mode}")
            self._state["driving"]["mode"] = mode
            self._persist()
            return _ok(f"驾驶模式已切换为{mode}", {"mode": mode})

    def launch_app(self, app_name: str, enable: bool = True) -> Dict[str, Any]:
        with self._lock:
            resolved = resolve_or_suggest(app_name)
            if not resolved.get("ok"):
                return _fail(resolved["message"], {"available": resolved.get("available")})
            app_name = resolved["app_name"]
            running = self._state["apps"].setdefault("running", [])
            installed = self._state["apps"].setdefault("installed", sorted(ALLOWED_APP_NAMES))
            if not installed:
                self._state["apps"]["installed"] = sorted(ALLOWED_APP_NAMES)
            if enable:
                if app_name not in running:
                    running.append(app_name)
                self._state["apps"]["active"] = app_name
                self._persist()
                return _ok(f"已打开{app_name}", {"active": app_name, "app_name": app_name})
            if app_name in running:
                running.remove(app_name)
            if self._state["apps"].get("active") == app_name:
                self._state["apps"]["active"] = running[-1] if running else None
            self._persist()
            return _ok(f"已关闭{app_name}", {"active": self._state["apps"]["active"], "app_name": app_name})

    def set_assistant(self, persona: Optional[str] = None, speech_rate: Optional[str] = None, scene: Optional[str] = None) -> Dict[str, Any]:
        with self._lock:
            a = self._state["assistant"]
            if persona:
                a["persona"] = persona
            if speech_rate:
                a["speech_rate"] = speech_rate
            if scene is not None:
                a["scene"] = scene
            self._persist()
            return _ok("助手设置已更新", a)

    def set_wifi(self, enable: bool) -> Dict[str, Any]:
        with self._lock:
            wifi = self._state.setdefault("connectivity", {}).setdefault(
                "wifi", {"on": True, "ssid": "手机热点", "signal": 3}
            )
            wifi["on"] = bool(enable)
            if wifi["on"] and not wifi.get("ssid"):
                wifi["ssid"] = "手机热点"
            self._persist()
            label = f"已连接 · {wifi.get('ssid') or '热点'}" if wifi["on"] else "未连接"
            return _ok(f"Wi‑Fi {label}", {"wifi": wifi})

    def authorize_messages(self, enable: bool = True) -> Dict[str, Any]:
        """兼容旧「授权」话术：车机消息无需授权；仪表盘可直接看，语音朗读走确认门控。"""
        with self._lock:
            note = self._state.setdefault("notifications", {})
            # 保留字段兼容前端快照，但不再作为读正文门禁
            note["message_access"] = True
            self._persist()
            return _ok(
                "消息无需授权。仪表盘可直接点开查看；"
                "若要我朗读，请说「读一下消息」，确认后再播报。",
                _notifications_summary(note),
            )

    def list_messages(self, unread_only: bool = False, mark_read: bool = True) -> Dict[str, Any]:
        with self._lock:
            note = self._state.setdefault("notifications", {})
            msgs = [m for m in (note.get("messages") or []) if isinstance(m, dict)]
            selected = [m for m in msgs if (not unread_only) or (not m.get("read"))]
            # 先按「读取前」状态导出，再按需标已读（方便摘要区分未读）
            payload_msgs = []
            for m in selected:
                was_unread = not bool(m.get("read"))
                payload_msgs.append(
                    {
                        "id": m.get("id"),
                        "app": m.get("app"),
                        "from": m.get("from"),
                        "text": m.get("text"),
                        "read": not was_unread,
                        "unread": was_unread,
                        "ts": m.get("ts"),
                    }
                )
            if mark_read:
                for m in selected:
                    if not m.get("read"):
                        m["read"] = True
            self._persist()
            unread_n = sum(1 for m in payload_msgs if m.get("unread"))
            payload = {
                "messages": payload_msgs,
                "unread_count": unread_n,
                "total": len(payload_msgs),
                **_notifications_summary(note),
            }
            if not selected:
                return _ok("当前没有消息" if not unread_only else "没有未读消息", payload)
            return _ok(
                f"已读取 {len(payload_msgs)} 条消息（未读 {unread_n}）。完整正文见依据面板。",
                payload,
            )

    def mark_messages_read(self, ids: Optional[List[str]] = None, all_unread: bool = False) -> Dict[str, Any]:
        with self._lock:
            note = self._state.setdefault("notifications", {})
            msgs = [m for m in (note.get("messages") or []) if isinstance(m, dict)]
            id_set = {str(x) for x in (ids or []) if x}
            n = 0
            for m in msgs:
                if all_unread or (m.get("id") and str(m.get("id")) in id_set):
                    if not m.get("read"):
                        m["read"] = True
                        n += 1
            self._persist()
            return _ok(f"已标记 {n} 条消息为已读", _notifications_summary(note))
