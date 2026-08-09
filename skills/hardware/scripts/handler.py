# -*- coding: utf-8 -*-
"""
Hardware Skill Handler V3 - 车辆硬控与声光电视觉域
【已清理】删除所有 position 参数，仅保留 positions 列表格式
"""

import json
import os
import re
from typing import Dict, Any, Union, List


# ================= 状态读写工具 =================
def load_state(state_file: str) -> Dict[str, Any]:
    """从 state.json 加载状态"""
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Hardware] 加载状态失败: {e}")
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
        print(f"[Hardware] 保存状态失败: {e}")
    return False


def get_hardware_state(full_state: Dict) -> Dict[str, Any]:
    """获取 hardware 部分的当前状态（冷启动默认值）"""
    return full_state.get("hardware", {
        "control_window": {
            "front_left": 0,
            "front_right": 0,
            "rear_left": 0,
            "rear_right": 0
        },
        "control_lighting": {
            "ambient": 0,
            "lighting": 0
        },
        "control_display": {
            "center_screen": 50,
            "instrument": 50,
            "hud": 50
        },
        "trunk_control": {
            "open": False
        },
        "door_lock": {
            "front_left": "lock",
            "front_right": "lock",
            "rear_left": "lock",
            "rear_right": "lock"
        }
    })


# ================= 核心函数 =================
def control_window(
    state_file: str,
    positions: List[str] = None,
    percent: Union[int, str, List[int]] = 50,
) -> Dict[str, Any]:
    """车窗控制 - 仅支持 positions 列表（已删除 position）"""
    
    position_map = {
        "driver": "front_left",
        "主驾": "front_left",
        "左前": "front_left",
        "front_left": "front_left",
        "passenger": "front_right",
        "副驾": "front_right",
        "右前": "front_right",
        "front_right": "front_right",
        "rear_left": "rear_left",
        "左后": "rear_left",
        "rear_right": "rear_right",
        "右后": "rear_right",
        "all": "all",
        "全部": "all"
    }

    pos_names = {
        "front_left": "左前窗",
        "front_right": "右前窗",
        "rear_left": "左后窗",
        "rear_right": "右后窗",
        "all": "全部车窗"
    }

    # 仅处理 positions
    if positions and isinstance(positions, list) and len(positions) > 0:
        if len(positions) == 1 and positions[0] in ["all", "全部"]:
            target_positions = ["front_left", "front_right", "rear_left", "rear_right"]
        else:
            target_positions = [position_map.get(p, p) for p in positions]
            if "all" in target_positions:
                target_positions = ["front_left", "front_right", "rear_left", "rear_right"]
    else:
        target_positions = ["front_left"]  # 默认主驾

    full_state = load_state(state_file)
    hw_state = get_hardware_state(full_state)
    window_state = hw_state.get("control_window", {})

    def parse_percent(p, current_val):
        if isinstance(p, str):
            percent_str = p.lower()
            if any(word in percent_str for word in ["高", "升", "上", "开", "大一点"]):
                return min(100, current_val + 20)
            elif any(word in percent_str for word in ["低", "降", "下", "关", "小一点"]):
                return max(0, current_val - 20)
            else:
                nums = re.findall(r'\d+', percent_str)
                if nums:
                    return int(nums[0])
                return 50
        return int(p)

    target_percents = {}
    for i, pos in enumerate(target_positions):
        current = window_state.get(pos, 0)
        if isinstance(percent, list) and i < len(percent):
            target_percents[pos] = max(0, min(100, parse_percent(percent[i], current)))
        else:
            target_percents[pos] = max(0, min(100, parse_percent(percent, current)))

    for pos in target_positions:
        window_state[pos] = target_percents[pos]

    hw_state["control_window"] = window_state
    full_state["hardware"] = hw_state
    save_state(state_file, full_state)

    if len(target_positions) == 1:
        pos_display = pos_names.get(target_positions[0], target_positions[0])
        p = target_percents[target_positions[0]]
        state_msg = "已关闭" if p == 0 else "已完全打开" if p == 100 else f"已打开{p}%"
        msg = f"{pos_display}{state_msg}"
    else:
        if all(p == 0 for p in target_percents.values()):
            msg = "全部车窗已关闭"
        elif all(p == 100 for p in target_percents.values()):
            msg = "全部车窗已完全打开"
        else:
            percent_strs = [f"{pos_names.get(p, p)}:{target_percents[p]}%" for p in target_positions]
            msg = f"车窗已设置: {', '.join(percent_strs)}"

    return {
        "success": True,
        "message": msg,
        "data": {
            "positions": target_positions,
            "percent": list(target_percents.values()) if len(target_positions) > 1 else target_percents[target_positions[0]]
        }
    }


def control_lighting(
    state_file: str,
    target: str = "lighting",
    brightness: Union[int, float] = 50,
) -> Dict[str, Any]:
    target_map = {
        "ambient": "ambient",
        "氛围灯": "ambient",
        "lighting": "lighting",
        "illumination": "lighting",
        "照明灯": "lighting",
        "灯": "lighting"
    }
    target_key = target_map.get(target, target)
    if target_key not in ["ambient", "lighting"]:
        target_key = "lighting"

    target_names = {"ambient": "氛围灯", "lighting": "照明灯"}
    target_display = target_names.get(target_key, target_key)
    brightness = max(0, min(100, int(round(brightness))))

    full_state = load_state(state_file)
    hw_state = get_hardware_state(full_state)
    lighting_state = hw_state.get("control_lighting", {})
    lighting_state[target_key] = brightness
    hw_state["control_lighting"] = lighting_state
    full_state["hardware"] = hw_state
    save_state(state_file, full_state)

    msg = f"{target_display}已关闭" if brightness == 0 else f"{target_display}亮度调整为{brightness}%"
    return {"success": True, "message": msg, "data": {"target": target_key, "brightness": brightness}}


def control_display(
    state_file: str,
    target: str = "center_screen",
    brightness: Union[int, float] = 50,
) -> Dict[str, Any]:
    target_map = {
        "center_screen": "center_screen",
        "中控屏": "center_screen",
        "screen": "center_screen",
        "instrument": "instrument",
        "仪表盘": "instrument",
        "hud": "hud",
        "all": "all",
        "全部": "all"
    }
    target_key = target_map.get(target, target)
    if target_key not in ["center_screen", "instrument", "hud", "all"]:
        target_key = "center_screen"

    target_names = {"center_screen": "中控屏", "instrument": "仪表盘", "hud": "HUD", "all": "全部屏幕"}
    target_display = target_names.get(target_key, target_key)
    brightness = max(0, min(100, int(round(brightness))))

    full_state = load_state(state_file)
    hw_state = get_hardware_state(full_state)
    display_state = hw_state.get("control_display", {})

    if target_key == "all":
        for t in ["center_screen", "instrument", "hud"]:
            display_state[t] = brightness
    else:
        display_state[target_key] = brightness

    hw_state["control_display"] = display_state
    full_state["hardware"] = hw_state
    save_state(state_file, full_state)

    msg = f"{target_display}已关闭" if brightness == 0 else f"{target_display}亮度调整为{brightness}%"
    return {"success": True, "message": msg, "data": {"target": target_key, "brightness": brightness}}


def trunk_control(
    state_file: str,
    action: str = "open"
) -> Dict[str, Any]:
    action_map = {"open": "已打开", "close": "已关闭"}
    state_msg = action_map.get(action, f"已{action}")
    is_open = action == "open"

    full_state = load_state(state_file)
    hw_state = get_hardware_state(full_state)
    hw_state["trunk_control"] = {"open": is_open}
    full_state["hardware"] = hw_state
    save_state(state_file, full_state)

    return {"success": True, "message": f"后备箱{state_msg}", "data": {"action": action, "open": is_open}}


def door_lock(
    state_file: str,
    positions: List[str] = None,
    action: str = "lock"
) -> Dict[str, Any]:
    """车门锁控制 - 仅支持 positions 列表（已删除 position）"""
    
    position_map = {
        "driver": "front_left",
        "主驾": "front_left",
        "左前": "front_left",
        "front_left": "front_left",
        "passenger": "front_right",
        "副驾": "front_right",
        "右前": "front_right",
        "front_right": "front_right",
        "rear_left": "rear_left",
        "左后": "rear_left",
        "rear_right": "rear_right",
        "右后": "rear_right",
        "all": "all",
        "全部": "all"
    }

    pos_names = {
        "front_left": "左前门",
        "front_right": "右前门",
        "rear_left": "左后门",
        "rear_right": "右后门",
        "all": "全车"
    }

    # 仅处理 positions
    if positions and isinstance(positions, list) and len(positions) > 0:
        if len(positions) == 1 and positions[0] in ["all", "全部"]:
            target_positions = ["front_left", "front_right", "rear_left", "rear_right"]
        else:
            target_positions = [position_map.get(p, p) for p in positions]
            if "all" in target_positions:
                target_positions = ["front_left", "front_right", "rear_left", "rear_right"]
    else:
        target_positions = ["front_left"]  # 默认主驾

    action_map = {"lock": "已上锁", "unlock": "已解锁"}
    state_msg = action_map.get(action, f"已{action}")

    full_state = load_state(state_file)
    hw_state = get_hardware_state(full_state)
    lock_state = hw_state.get("door_lock", {})

    for pos in target_positions:
        lock_state[pos] = action

    hw_state["door_lock"] = lock_state
    full_state["hardware"] = hw_state
    save_state(state_file, full_state)

    if len(target_positions) == 1:
        pos_display = pos_names.get(target_positions[0], target_positions[0])
        msg = f"{pos_display}{state_msg}"
    else:
        msg = f"全车{state_msg}"

    return {
        "success": True,
        "message": msg,
        "data": {"positions": target_positions, "action": action}
    }


# ================= 统一执行入口 =================
def execute(script: str, params: Dict[str, Any], state_file: str) -> Dict[str, Any]:
    clean_params = {}
    for k, v in params.items():
        if k == "position":
            continue
        clean_params[k] = v

    params_with_state = {"state_file": state_file, **clean_params}
    scripts = {
        "control_window": control_window,
        "control_lighting": control_lighting,
        "control_display": control_display,
        "trunk_control": trunk_control,
        "door_lock": door_lock,
    }

    handler = scripts.get(script)
    if not handler:
        return {"success": False, "message": f"不支持 script: {script}", "data": None}

    try:
        return handler(**params_with_state)
    except Exception as e:
        import traceback
        return {"success": False, "message": f"执行失败: {str(e)}", "data": {"traceback": traceback.format_exc()}}


# ================= 测试 =================
if __name__ == "__main__":
    import tempfile
    test_state = {"meta": {"version": "2.0"}, "hardware": {}}
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False, encoding='utf-8') as f:
        json.dump(test_state, f, ensure_ascii=False, indent=2)
        test_file = f.name

    print("=== 测试（仅 positions）===")
    tests = [
        {"script": "control_window", "params": {"positions": ["front_left"], "percent": 50}},
        {"script": "control_window", "params": {"positions": ["all"], "percent": 0}},
        {"script": "door_lock", "params": {"positions": ["front_left"], "action": "unlock"}},
        {"script": "door_lock", "params": {"positions": ["all"], "action": "lock"}},
    ]

    for case in tests:
        res = execute(case["script"], case["params"], test_file)
        print(f"{case['script']} → {res['message']}")

    os.unlink(test_file)