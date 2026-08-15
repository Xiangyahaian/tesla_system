# -*- coding: utf-8 -*-
"""唯一车况真理来源（Canonical Vehicle State）。"""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any, Dict


def _zone_climate(temp: float = 22.0, fan: int = 2, on: bool = False) -> Dict[str, Any]:
    return {"on": on, "temp": float(temp), "fan": int(fan)}


def _seat(level: int = 0, enable: bool = False, mode: str = "normal") -> Dict[str, Any]:
    return {"level": level, "enable": enable, "mode": mode}


def initial_vehicle_state() -> Dict[str, Any]:
    from app.gateway.apps_catalog import ALLOWED_APP_NAMES

    zones = ["front_left", "front_right", "rear_left", "rear_middle", "rear_right"]
    windows = ["front_left", "front_right", "rear_left", "rear_right", "sunroof"]
    doors = ["front_left", "front_right", "rear_left", "rear_right"]

    return {
        "meta": {
            "version": "V2",
            "revision": 0,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "description": "Canonical vehicle state for Cabin Runtime",
        },
        "dynamics": {
            "speed_kmh": 0.0,
            "gear": "D",  # 默认道路巡航：已挂 D
            "child_lock": False,
            "parked": False,
            "cruise_set_kmh": 65.0,  # ACC 设定车速（城市跟驰约 60 均速）
            "cruise_target_kmh": 58.0,  # 当前跟驰目标（路况起伏）
        },
        "climate": {
            "power": False,
            "mode": "auto",  # auto/eco/comfort/heat/cool
            "direction": "auto",
            "recirculation": False,
            "zones": {z: _zone_climate() for z in zones},
        },
        "seats": {
            "heat": {z: {"level": 0, "enable": False} for z in zones},
            "ventilation": {z: {"level": 0, "enable": False} for z in zones},
            "massage": {z: _seat() for z in zones},
            "steering_wheel_heat": {"level": 0, "enable": False},
        },
        "cabin": {
            "windows": {p: {"percent": 0} for p in windows},
            "doors": {p: {"locked": True} for p in doors},
            "lights": {
                "dome": {"brightness": 0, "enable": False},
                "ambient": {"brightness": 0, "enable": False, "color": "white"},
                "reading_left": {"brightness": 0, "enable": False},
                "reading_right": {"brightness": 0, "enable": False},
            },
            "displays": {
                "center_screen": {"brightness": 50},
                "instrument": {"brightness": 50},
                "hud": {"brightness": 50},
            },
            "trunk": {"open": False},
            "frunk": {"open": False},
            "charge_port": {"open": False},
        },
        "media": {
            "music": {
                "playing": False,
                "artist": None,
                "title": None,
                "album": None,
                "index": -1,
                "position_sec": 0.0,
                "duration_sec": 0.0,
            },
            "radio": {
                "playing": False,
                "band": None,
                "frequency": None,
                "station_name": None,
                "index": -1,
            },
            "volume": 50,
            "muted": False,
        },
        "navigation": {
            "navigating": False,
            "mode": "cruising",  # parked | cruising | navigating
            "destination": None,
            "corridor_dest": "中关村软件园",  # 默认道路巡航走廊终点
            "preference": "fastest",
            "eta_min": None,
            "traffic": "畅通",
            "provider": None,
            "origin": None,
            "origin_name": "北京理工大学中关村校区南门",
            "distance_m": None,
            "remaining_m": None,
            "progress_m": 0.0,
            "duration_sec": None,
            "polyline": [],
            "steps": [],
            "heading_deg": 0.0,
            "cruise_dir": 1,  # 走廊往返：1 去程 / -1 返程
            "position": {
                "lng": 116.316356,
                "lat": 39.957053,
                "name": "北京理工大学中关村校区南门",
            },
            "arrived": False,
        },
        "driving": {
            "mode": "comfort",
            "battery_percent": 78,
            "range_km": 350,
            "adas": {
                "auto_hold": False,
                "acc": True,
                "autopark": False,
                "lane_keep": True,
                "collision_warning": True,
            },
        },
        "apps": {
            "active": None,
            "running": [],
            "installed": sorted(ALLOWED_APP_NAMES),
        },
        "connectivity": {
            # 行车时更常见：蜂窝为主；Wi‑Fi 多为手机热点/车载热点
            "wifi": {"on": True, "ssid": "手机热点", "signal": 3},
            "bluetooth": True,
            "cellular": {"on": True, "type": "5G", "carrier": "中国移动", "signal": 4},
        },
        "notifications": {
            "message_access": True,  # 兼容字段；读正文不再门禁，Agent 朗读走确认门控
            "messages": [
                {
                    "id": "m_init_1",
                    "app": "微信",
                    "from": "王工",
                    "text": "会议改到今天下午 15:00",
                    "read": False,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                },
                {
                    "id": "m_init_2",
                    "app": "短信",
                    "from": "顺丰速运",
                    "text": "您的包裹已到达菜鸟驿站，请凭取件码领取",
                    "read": True,
                    "ts": datetime.now().isoformat(timespec="seconds"),
                },
            ],
            "missed_calls": 0,
            "phone_status": "空闲",
            "phone_last": None,
        },
        "assistant": {
            "persona": "default",
            "speech_rate": "normal",
            "speech_mode": "normal",
            "scene": None,
        },
    }


def touch(state: Dict[str, Any]) -> Dict[str, Any]:
    state = deepcopy(state)
    state.setdefault("meta", {})
    state["meta"]["updated_at"] = datetime.now().isoformat(timespec="seconds")
    return state
