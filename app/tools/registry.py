# -*- coding: utf-8 -*-
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Type

from pydantic import BaseModel, ValidationError

from app.gateway.base import VehicleGateway
from app.models import RiskLevel, ToolCall, ToolResult


Handler = Callable[[VehicleGateway, BaseModel], Dict[str, Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    args_model: Type[BaseModel]
    handler: Handler
    risk: RiskLevel = RiskLevel.LOW
    domain: str = "general"


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def list_tools(self) -> List[ToolSpec]:
        return list(self._tools.values())

    def openai_schemas(self) -> List[Dict[str, Any]]:
        schemas = []
        for spec in self._tools.values():
            schemas.append(
                {
                    "type": "function",
                    "function": {
                        "name": spec.name,
                        "description": f"[{spec.risk.value}] {spec.description}",
                        "parameters": spec.args_model.model_json_schema(),
                    },
                }
            )
        return schemas

    def prompt_catalog(self) -> str:
        lines = []
        for spec in self._tools.values():
            schema = spec.args_model.model_json_schema()
            props = schema.get("properties", {})
            required = schema.get("required", [])
            arg_bits = []
            for k, v in props.items():
                tip = v.get("description") or v.get("title") or ""
                req = "必填" if k in required else "可选"
                arg_bits.append(f"{k}({req}:{tip})")
            lines.append(
                f"- {spec.name} [{spec.risk.value}/{spec.domain}]: {spec.description}\n"
                f"  参数: {', '.join(arg_bits) if arg_bits else '无'}"
            )
        return "\n".join(lines)

    def execute(self, gateway: VehicleGateway, call: ToolCall) -> ToolResult:
        spec = self._tools.get(call.name)
        if not spec:
            return ToolResult(success=False, message=f"未知工具: {call.name}", tool=call.name)
        try:
            args = spec.args_model(**(call.arguments or {}))
        except ValidationError as e:
            return ToolResult(
                success=False,
                message=f"参数校验失败: {e.errors()[0].get('msg', str(e))}",
                tool=call.name,
                data={"errors": e.errors()},
            )
        try:
            raw = spec.handler(gateway, args)
            return ToolResult(
                success=bool(raw.get("success", False)),
                message=str(raw.get("message", "")),
                data=raw.get("data") or {},
                tool=call.name,
            )
        except Exception as e:
            return ToolResult(success=False, message=f"执行失败: {e}", tool=call.name)


_REGISTRY: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        from app.tools.catalog import build_registry

        _REGISTRY = build_registry()
    return _REGISTRY
