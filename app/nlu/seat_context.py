# -*- coding: utf-8 -*-
"""当前说话人座位：用于默认 zones/positions。"""
from __future__ import annotations

from typing import List, Optional

from app.models import ToolCall

VALID_SEATS = frozenset(
    {"front_left", "front_right", "rear_left", "rear_middle", "rear_right"}
)

SEAT_CN = {
    "front_left": "主驾",
    "front_right": "副驾",
    "rear_left": "左后",
    "rear_middle": "中后",
    "rear_right": "右后",
}

# 车窗/车门没有后排中间位
_WINDOW_DOOR_FALLBACK = {
    "rear_middle": "rear_left",
}


def normalize_active_seat(seat: Optional[str], fallback: str = "front_left") -> str:
    s = (seat or "").strip()
    return s if s in VALID_SEATS else fallback


def apply_active_seat_defaults(calls: List[ToolCall], active_seat: str) -> List[ToolCall]:
    """用户未指定位置时，把 zones/positions 补成当前座位。"""
    seat = normalize_active_seat(active_seat)
    out: List[ToolCall] = []
    for call in calls:
        args = dict(call.arguments or {})
        name = call.name or ""
        if name.startswith("climate.") and name != "climate.set_mode":
            if not args.get("zones"):
                args["zones"] = [seat]
        elif name == "seat.set":
            if not args.get("positions"):
                args["positions"] = [seat]
        elif name in {
            "cabin.set_windows",
            "cabin.adjust_windows",
            "cabin.set_door_locks",
        }:
            if not args.get("positions"):
                pos = _WINDOW_DOOR_FALLBACK.get(seat, seat)
                args["positions"] = [pos]
            else:
                # 已指定天窗时不要被座位默认覆盖
                positions = args.get("positions") or []
                if "sunroof" in positions or "天窗" in positions:
                    args["positions"] = ["sunroof"]
        out.append(ToolCall(name=call.name, arguments=args, reason=call.reason))
    return out


def apply_memory_climate_defaults(
    calls: List[ToolCall],
    active_seat: str,
    preferred_temp: Optional[float],
) -> List[ToolCall]:
    """打开空调但未给温度时，套用记忆偏好温度。"""
    if preferred_temp is None:
        return calls
    seat = normalize_active_seat(active_seat)
    out: List[ToolCall] = []
    need_temp = False
    has_temp = False
    for call in calls:
        name = call.name or ""
        args = dict(call.arguments or {})
        if name == "climate.set_power" and args.get("enable") is True:
            zones = args.get("zones") or [seat]
            if seat in zones or not args.get("zones"):
                need_temp = True
        if name == "climate.set_temperature":
            has_temp = True
        out.append(call)
    if need_temp and not has_temp:
        out.append(
            ToolCall(
                name="climate.set_temperature",
                arguments={"temperature": float(preferred_temp), "zones": [seat]},
                reason=f"记忆偏好温度 {preferred_temp:.0f}°C",
            )
        )
    return out
