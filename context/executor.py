# -*- coding: utf-8 -*-
"""
函数执行与结果格式化
"""
from typing import Dict, Any, List
from context.models import FunctionCall
from context.skills import get_skill_handler
from context.utils import format_params
from context.state import load_state


def execute_function(call: FunctionCall) -> Dict[str, Any]:
    """执行单个函数调用"""
    handler = get_skill_handler(call.skill)
    if not handler:
        return {"success": False, "message": f"未找到技能: {call.skill}", "data": None}
    
    try:
        result = handler(call.script, call.parameters)
        
        if result.get("success", False):
            current_state = load_state()
            if call.skill in current_state:
                print(f"[状态验证] {call.skill} 状态已更新")
        
        return result
    except Exception as e:
        import traceback
        return {"success": False, "message": f"执行失败: {str(e)}", "data": {"traceback": traceback.format_exc()}}


def execute_multiple_functions(calls: List[FunctionCall]) -> List[Dict[str, Any]]:
    """按顺序执行多个函数"""
    results = []
    for i, call in enumerate(calls, 1):
        print(f"[多任务执行] 任务 {i}/{len(calls)}: {call.skill}.{call.script}")
        result = execute_function(call)
        results.append({
            "index": i,
            "call": call,
            "result": result
        })
    return results


def format_multi_results(results: List[Dict[str, Any]]) -> str:
    """格式化多任务执行结果"""
    messages = []
    for item in results:
        call = item["call"]
        result = item["result"]
        call_info = f"{call.script}({format_params(call.parameters)})"
        
        if result["success"]:
            messages.append(f"{result['message']} ({call_info})")
        else:
            messages.append(f"操作失败: {result['message']} ({call_info})")
    
    return ";".join(messages)
