# -*- coding: utf-8 -*-
"""安全策略：风险分级 + 行驶约束 + 确认门控。"""
from __future__ import annotations

from typing import List

from app.models import PolicyDecision, RiskLevel, ToolCall
from app.tools.registry import ToolRegistry, get_registry


HIGH_RISK_TOOLS = {
    "cabin.set_door_locks",
    "cabin.set_trunk",
    "driving.set_adas",
}

MEDIUM_RISK_TOOLS = {
    "cabin.set_windows",
    "cabin.adjust_windows",
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
                    risk = RiskLevel.HIGH
                    messages.append("车速较快，大幅度开窗需要确认")

            if call.name == "driving.set_adas" and call.arguments.get("enable") is True:
                confirm = True
                risk = RiskLevel.HIGH

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

        summary = "；".join(messages) if messages else "该操作涉及车辆安全，请确认后执行"
        return PolicyDecision(
            allowed=True,
            require_confirm=confirm,
            risk=worst,
            message=summary if confirm else "",
        )
