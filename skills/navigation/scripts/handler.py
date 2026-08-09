# -*- coding: utf-8 -*-
"""
Navigation Skill Handler V4 - 导航与出行路线域

V4 规范：
- navigate_to: position(目的地)
- query_traffic: destination, keyword(默认"ahead", 可选ahead/destination/alternative)
"""

import json
import os
from typing import Dict, Any


# ================= 状态读写工具 =================
def load_state(state_file: str) -> Dict[str, Any]:
    """从 state.json 加载状态"""
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Navigation] 加载状态失败: {e}")
    return {}


def save_state(state_file: str, state: Dict[str, Any]) -> bool:
    """保存状态到 state.json"""
    try:
        if "meta" in state:
            from datetime import datetime
            state["meta"]["last_updated"] = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        return True
    except Exception as e:
        print(f"[Navigation] 保存状态失败: {e}")
        return False


def get_nav_state(full_state: Dict) -> Dict[str, Any]:
    """获取 navigation 部分的当前状态"""
    return full_state.get("navigation", {
        "navigate_to": {"position": None},
        "query_traffic": {"destination": None, "keyword": None}
    })


# ================= 核心函数 =================
def navigate_to(
    state_file: str,
    position: str = ""
) -> Dict[str, Any]:
    """开始导航到指定位置
    
    Args:
        state_file: 状态文件路径
        position: 目的地名称或地址
    """
    
    # 更新状态
    full_state = load_state(state_file)
    nav_state = get_nav_state(full_state)
    
    nav_state["navigate_to"] = {
        "position": position
    }
    
    full_state["navigation"] = nav_state
    save_state(state_file, full_state)
    
    if position:
        msg = f"开始导航到「{position}」"
    else:
        msg = "请提供导航目的地"
    
    return {
        "success": True if position else False,
        "message": msg,
        "data": {
            "position": position
        }
    }


def query_traffic(
    state_file: str,
    destination: str = "",
    keyword: str = "ahead"
) -> Dict[str, Any]:
    """路况查询
    
    Args:
        state_file: 状态文件路径
        destination: 目的地名称或地址
        keyword: 查询类型，默认"ahead"(前方)，可选"ahead"/"destination"/"alternative"
    """
    
    # 更新状态
    full_state = load_state(state_file)
    nav_state = get_nav_state(full_state)
    
    nav_state["query_traffic"] = {
        "destination": destination,
        "keyword": keyword
    }
    
    full_state["navigation"] = nav_state
    save_state(state_file, full_state)
    
    # 构建消息
    if keyword == "ahead":
        msg = "查询前方路况"
    elif keyword == "destination":
        if destination:
            msg = f"查询到「{destination}」的路况"
        else:
            msg = "查询到目的地的路况"
    elif keyword == "alternative":
        msg = "查询备选路线"
    else:
        msg = "查询路况"
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "destination": destination,
            "keyword": keyword
        }
    }


# ================= 统一执行入口 V4 =================
def execute(script: str, params: Dict[str, Any], state_file: str) -> Dict[str, Any]:
    """
    统一执行入口 V4
    
    Args:
        script: 要执行的函数名称
        params: LLM 提供的参数
        state_file: state.json 的文件路径
    """
    params = {k: v for k, v in params.items() if k != "action"}
    params_with_state = {"state_file": state_file, **params}
    
    scripts = {
        "navigate_to": navigate_to,
        "query_traffic": query_traffic,
    }
    
    handler = scripts.get(script)
    if not handler:
        return {
            "success": False,
            "message": f"Navigation Skill 不支持 script: {script}",
            "data": None
        }
    
    try:
        return handler(**params_with_state)
    except Exception as e:
        import traceback
        return {
            "success": False,
            "message": f"执行失败: {str(e)}",
            "data": {"traceback": traceback.format_exc()}
        }


# ================= 测试 =================
if __name__ == "__main__":
    import tempfile
    
    test_state = {
        "meta": {"version": "2.0", "last_updated": "2026-03-18T22:00:00"},
        "navigation": {
            "navigate_to": {"position": None},
            "query_traffic": {"destination": None, "keyword": None}
        }
    }
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(test_state, f, ensure_ascii=False, indent=2)
        test_file = f.name
    
    print("=" * 60)
    print("Navigation Handler V4 Test (Simplified)")
    print("=" * 60)
    
    tests = [
        {"script": "navigate_to", "params": {"position": "北京西站"}, "desc": "导航到北京西站"},
        {"script": "query_traffic", "params": {"keyword": "destination"}, "desc": "查询到目的地路况"},
    ]
    
    for case in tests:
        print(f"\n[测试] {case['desc']}")
        result = execute(case["script"], case["params"], test_file)
        print(f"  [{'OK' if result['success'] else 'ERR'}] {result['message']}")
    
    os.unlink(test_file)
    print("\n测试完成!")
