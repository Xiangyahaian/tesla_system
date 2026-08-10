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
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "description": "Canonical vehicle state for Cabin Runtime",
        },
        "dynamics": {
            "speed_kmh": 0.0,
            "gear": "P",  # P/R/N/D
            "child_lock": False,
            "parked": True,
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
            "destination": None,
            "preference": "fastest",
            "eta_min": None,
            "traffic": None,
        },
        "driving": {
            "mode": "comfort",
            "battery_percent": 78,
            "range_km": 350,
            "adas": {
                "auto_hold": False,
                "acc": False,
                "autopark": False,
                "lane_keep": False,
                "collision_warning": True,
            },
        },
        "apps": {
            "active": None,
            "running": [],
            "installed": sorted(ALLOWED_APP_NAMES),
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
