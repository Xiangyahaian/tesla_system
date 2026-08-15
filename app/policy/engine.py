# -*- coding: utf-8 -*-
"""安全策略：风险分级 + 行驶约束 + 确认门控。"""
from __future__ import annotations

from typing import List

from app.models import PolicyDecision, RiskLevel, ToolCall
from app.tools.registry import ToolRegistry, get_registry


HIGH_RISK_TOOLS = {
    "cabin.set_door_locks",
    "cabin.set_trunk",
    "cabin.set_frunk",
    "driving.set_adas",
    "driving.set_speed",
}

MEDIUM_RISK_TOOLS = {
    "cabin.set_windows",
    "cabin.adjust_windows",
    "cabin.set_charge_port",
    "driving.set_child_lock",
}


class PolicyEngine:
    def __init__(self, registry: ToolRegistry | None = None):
        self.registry = registry or get_registry()

    def _tool_risk(self, name: str) -> RiskLevel:
        if name in HIGH_RISK_TOOLS:
            return RiskLevel.HIGH
        if name in MEDIUM_RISK_TOOLS:
            return RiskLevel.MEDIUM
        spec = self.registry.get(name)
        return spec.risk if spec else RiskLevel.LOW

    def evaluate(self, calls: List[ToolCall], vehicle_state: dict) -> PolicyDecision:
        if not calls:
            return PolicyDecision(allowed=True, require_confirm=False, risk=RiskLevel.LOW)

        dynamics = vehicle_state.get("dynamics", {})
        speed = float(dynamics.get("speed_kmh", 0) or 0)
        gear = str(dynamics.get("gear", "P") or "P").upper()
        child_lock = bool(dynamics.get("child_lock", False))

        worst = RiskLevel.LOW
        confirm = False
        had_privacy_confirm = False
        had_safety_confirm = False
        messages = []

        for call in calls:
            risk = self._tool_risk(call.name)
            # 解锁在行驶中禁止
            if call.name == "cabin.set_door_locks":
                locked = call.arguments.get("locked")
                if locked is False and speed > 0:
                    return PolicyDecision(
                        allowed=False,
                        require_confirm=False,
                        risk=RiskLevel.HIGH,
                        blocked_reason="行驶中禁止解锁车门",
                        message="当前车辆在行驶，为安全起见不能解锁车门。",
                    )
                if locked is False:
                    confirm = True
                    had_safety_confirm = True
                    risk = RiskLevel.HIGH

            if call.name == "cabin.set_trunk" and call.arguments.get("open") is True:
                if speed > 0 or gear in {"D", "R"}:
                    return PolicyDecision(
                        allowed=False,
                        require_confirm=False,
                        risk=RiskLevel.HIGH,
                        blocked_reason="非驻车状态禁止打开后备箱",
                        message="请先停车再打开后备箱。",
                    )
                confirm = True
                had_safety_confirm = True
                risk = RiskLevel.HIGH

            if call.name in {"cabin.set_windows", "cabin.adjust_windows"}:
                percent = call.arguments.get("percent")
                delta = call.arguments.get("delta", 0)
                # 高速大开窗需确认
                if speed >= 60 and (
                    (percent is not None and int(percent) >= 50)
                    or (delta is not None and int(delta) >= 30)
                ):
                    confirm = True
                    had_safety_confirm = True
                    risk = RiskLevel.HIGH
                    messages.append("车速较快，大幅度开窗需要确认")

            if call.name == "driving.set_speed":
                target = call.arguments.get("speed_kmh")
                to_park = call.arguments.get("parked") is True or str(
                    call.arguments.get("gear") or ""
                ).upper() == "P"
                try:
                    target_f = float(target) if target is not None else 0.0
                except (TypeError, ValueError):
                    target_f = 0.0
                confirm = True
                had_safety_confirm = True
                risk = RiskLevel.HIGH
                if to_park or target_f <= 0:
                    messages.append("将进入驻车或停车，请确认周围安全")
                else:
                    messages.append(
                        f"将把目标车速设为 {target_f:.0f} km/h 并驶向该速度，请确认路况安全"
                    )

            if call.name == "driving.set_adas" and call.arguments.get("enable") is True:
                feat = str(call.arguments.get("feature") or "").lower()
                if feat in {"autopark", "auto_park"}:
                    confirm = True
                    had_safety_confirm = True
                    risk = RiskLevel.HIGH
                    messages.append("自动泊车将接管转向与制动，请确认周围安全、车速足够低")
                    if speed > 8:
                        return PolicyDecision(
                            allowed=False,
                            require_confirm=False,
                            risk=RiskLevel.HIGH,
                            blocked_reason="车速过高无法自动泊车",
                            message=f"当前车速 {speed:.0f} km/h，请先减速至约 5 km/h 以内再启动自动泊车。",
                        )
                elif feat in {"acc", "cruise"}:
                    confirm = True
                    had_safety_confirm = True
                    risk = RiskLevel.HIGH
                    messages.append("自适应巡航开启后车辆将按目标车速行驶，请确认路况安全")
                    if (vehicle_state.get("driving") or {}).get("adas", {}).get("autopark"):
                        return PolicyDecision(
                            allowed=False,
                            require_confirm=False,
                            risk=RiskLevel.HIGH,
                            blocked_reason="自动泊车互斥",
                            message="自动泊车进行中，无法同时开启自适应巡航。",
                        )
                elif feat in {"lane_keep"}:
                    risk = RiskLevel.MEDIUM
                    if (vehicle_state.get("driving") or {}).get("adas", {}).get("autopark"):
                        return PolicyDecision(
                            allowed=False,
                            require_confirm=False,
                            risk=RiskLevel.MEDIUM,
                            blocked_reason="自动泊车互斥",
                            message="自动泊车进行中，无法开启车道保持。",
                        )
                elif feat in {"auto_hold", "autohold"}:
                    confirm = True
                    had_safety_confirm = True
                    risk = RiskLevel.HIGH
                    messages.append("自动驻车涉及制动，请确认后再开关")
                elif feat in {"collision_warning"}:
                    risk = RiskLevel.LOW
                else:
                    confirm = True
                    had_safety_confirm = True
                    risk = RiskLevel.HIGH

            if call.name == "notifications.list_messages":
                # 隐私确认：不是车辆高风险；口语确认文案由 runtime 生成
                confirm = True
                had_privacy_confirm = True
                risk = RiskLevel.MEDIUM
                messages.append("读消息")

            if child_lock and call.name == "cabin.set_door_locks" and call.arguments.get("locked") is False:
                positions = call.arguments.get("positions") or []
                if any(p.startswith("rear") for p in positions) or not positions:
                    return PolicyDecision(
                        allowed=False,
                        require_confirm=False,
                        risk=RiskLevel.HIGH,
                        blocked_reason="儿童锁开启",
                        message="后排儿童锁已开启，无法从车内解锁后排车门。",
                    )

            order = {RiskLevel.LOW: 0, RiskLevel.MEDIUM: 1, RiskLevel.HIGH: 2}
            if order[risk] > order[worst]:
                worst = risk
            if risk == RiskLevel.HIGH:
                confirm = True
                had_safety_confirm = True

        confirm_kind = "privacy" if had_privacy_confirm and not had_safety_confirm else "safety"
        if confirm_kind == "privacy":
            summary = "；".join(messages) if messages else "读取消息前需要你确认一下"
        else:
            summary = "；".join(messages) if messages else "该操作涉及车辆安全，请确认后执行"
        return PolicyDecision(
            allowed=True,
            require_confirm=confirm,
            risk=worst,
            message=summary if confirm else "",
            confirm_kind=confirm_kind,
        )
