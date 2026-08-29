# -*- coding: utf-8 -*-
from __future__ import annotations

import json
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

    def prompt_catalog(self, domains: Optional[List[str]] = None) -> str:
        want = {d.strip().lower() for d in (domains or []) if d and str(d).strip()}
        lines = []
        for spec in self._tools.values():
            if want and (spec.domain or "general").lower() not in want:
                continue
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
        if want and not lines:
            return self.prompt_catalog(None)
        return "\n".join(lines)

    @staticmethod
    def _validation_hint(errors: List[Dict[str, Any]]) -> str:
        bits: List[str] = []
        for err in errors[:4]:
            loc = ".".join(str(x) for x in (err.get("loc") or ()) if x != "body")
            msg = str(err.get("msg") or "无效")
            bits.append(f"{loc or '参数'}: {msg}" if loc else msg)
        return "；".join(bits) if bits else "参数不符合工具约定"

    def execute(self, gateway: VehicleGateway, call: ToolCall) -> ToolResult:
        spec = self._tools.get(call.name)
        if not spec:
            return ToolResult(
                success=False,
                message=f"未知工具: {call.name}",
                tool=call.name,
                data={"retryable": False, "error_kind": "unknown_tool"},
            )
        try:
            args = spec.args_model(**(call.arguments or {}))
        except ValidationError as e:
            errs = e.errors()
            hint = self._validation_hint(errs)
            return ToolResult(
                success=False,
                message=f"参数校验失败: {hint}",
                tool=call.name,
                data={
                    "errors": errs,
                    "retryable": True,
                    "error_kind": "validation",
                    "correction_hint": (
                        f"请改用合法参数重试 {call.name}。"
                        f"问题：{hint}。原参数：{json.dumps(call.arguments or {}, ensure_ascii=False)[:240]}"
                    ),
                },
            )
        try:
            raw = spec.handler(gateway, args)
            data = dict(raw.get("data") or {})
            ok = bool(raw.get("success", False))
            if not ok and "retryable" not in data:
                # 业务失败默认可让规划层换策略；歧义澄清不算失败重试
                data.setdefault("retryable", True)
                data.setdefault("error_kind", "business")
            return ToolResult(
                success=ok,
                message=str(raw.get("message", "")),
                data=data,
                tool=call.name,
            )
        except Exception as e:
            return ToolResult(
                success=False,
                message="这步没做成，换个说法再试就行。",
                tool=call.name,
                data={
                    "retryable": True,
                    "error_kind": "exception",
                    "error": str(e)[:1200],
                },
            )


_REGISTRY: Optional[ToolRegistry] = None


def get_registry() -> ToolRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        from app.tools.catalog import build_registry

        _REGISTRY = build_registry()
    return _REGISTRY
