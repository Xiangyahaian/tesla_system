# -*- coding: utf-8 -*-
"""
Seat Skill Handler V4 - 五座位独立控制 + 多区域同步版本

V4 变更：
- 支持五个独立座位位置: front_left, front_right, rear_left, rear_right, rear_middle
- 每个位置有独立的 level 和 enable 状态
- 仅支持 positions 数组参数，多区域同步操作
- 默认操作 front_left (驾驶位)
"""

import json
import os
from typing import Dict, Any, List

# 常量定义
ZONE_NAMES = {
    "front_left": "前排左座",
    "front_right": "前排右座",
    "rear_left": "后排左座",
    "rear_right": "后排右座",
    "rear_middle": "后排中间座"
}

LEVEL_NAMES = {0: "关闭", 1: "低档", 2: "中档", 3: "高档"}

MASSAGE_MODES = {
    "normal": "标准",
    "wave": "波浪",
    "pulse": "脉冲",
    "knead": "揉捏"
}

VALID_POSITIONS = ["front_left", "front_right", "rear_left", "rear_right", "rear_middle"]


def _load_state(state_file: str) -> Dict[str, Any]:
    """加载 state.json"""
    if not os.path.exists(state_file):
        return {}
    with open(state_file, 'r', encoding='utf-8') as f:
        return json.load(f)


def _save_state(state_file: str, state: Dict[str, Any]) -> None:
    """保存 state.json"""
    with open(state_file, 'w', encoding='utf-8') as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _get_position_name(position: str) -> str:
    """获取位置中文名"""
    return ZONE_NAMES.get(position, position)


def _validate_position(position: str) -> str:
    """验证并标准化单个位置参数"""
    position_map = {
        "driver": "front_left",
        "驾驶位": "front_left",
        "主驾": "front_left",
        "passenger": "front_right",
        "副驾": "front_right",
        "副驾驶": "front_right",
        "rear_left": "rear_left",
        "左后座": "rear_left",
        "后排左侧": "rear_left",
        "rear_right": "rear_right",
        "右后座": "rear_right",
        "后排右侧": "rear_right",
        "rear_middle": "rear_middle",
        "中后座": "rear_middle",
        "后排中间": "rear_middle"
    }
    return position_map.get(position, position if position in VALID_POSITIONS else "front_left")


def _get_target_positions(positions: List[str] = None) -> List[str]:
    """
    获取目标位置列表
    1. positions 数组（多区域同步）
    2. 默认 front_left
    """
    # 优先使用 positions 数组
    if positions and isinstance(positions, list) and len(positions) > 0:
        validated = []
        for pos in positions:
            vpos = _validate_position(pos)
            if vpos in VALID_POSITIONS and vpos not in validated:
                validated.append(vpos)
        if validated:
            return validated
    
    # 默认驾驶位
    return ["front_left"]


def _format_positions_name(positions: List[str]) -> str:
    """格式化位置列表为可读字符串"""
    if set(positions) == set(VALID_POSITIONS):
        return "全车座椅"
    elif set(positions) == {"front_left", "front_right"}:
        return "前排座椅"
    elif set(positions) == {"rear_left", "rear_middle", "rear_right"}:
        return "后排座椅"
    elif set(positions) == {"front_left", "rear_left"}:
        return "左侧座椅"
    elif set(positions) == {"front_right", "rear_right"}:
        return "右侧座椅"
    elif len(positions) == 1:
        return _get_position_name(positions[0])
    else:
        names = [_get_position_name(p) for p in positions]
        return "、".join(names)


def seat_heat(state_file: str, positions: List[str] = None, 
              level: int = 0, enable: bool = False, **kwargs) -> Dict[str, Any]:
    """
    控制指定位置座椅加热，支持多区域同步
    
    Args:
        state_file: state.json 文件路径
        positions: 座位位置列表（多区域同步）
        level: 加热档位 0-3 (0=关闭, 1=低档, 2=中档, 3=高档)
        enable: 开关状态 (true=开, false=关)
    """
    # 获取目标位置列表
    target_positions = _get_target_positions(positions)
    print(f"[seat_heat] 目标位置: {target_positions}, level={level}, enable={enable}")
    
    # 验证参数
    if not isinstance(level, int) or level < 0 or level > 3:
        return {"success": False, "message": f"档位必须在0-3之间，当前: {level}", "data": None}
    
    # 确保 enable 与 level 一致
    if level > 0 and not enable:
        enable = True
    if level == 0 and enable:
        enable = False
    
    # 加载状态
    state = _load_state(state_file)
    if "seat" not in state:
        state["seat"] = {}
    if "seat_heat" not in state["seat"]:
        state["seat"]["seat_heat"] = {}
    
    # 初始化所有位置（如果不存在）
    for pos in VALID_POSITIONS:
        if pos not in state["seat"]["seat_heat"]:
            state["seat"]["seat_heat"][pos] = {"level": 0, "enable": False}
    
    # 更新所有目标位置的状态
    updated = []
    for pos in target_positions:
        old_level = state["seat"]["seat_heat"][pos]["level"]
        old_enable = state["seat"]["seat_heat"][pos]["enable"]
        
        state["seat"]["seat_heat"][pos]["level"] = level
        state["seat"]["seat_heat"][pos]["enable"] = enable
        
        updated.append({
            "position": pos,
            "level": level,
            "enable": enable,
            "previous_level": old_level,
            "previous_enable": old_enable
        })
    
    # 保存状态
    _save_state(state_file, state)
    
    # 构建返回消息
    positions_name = _format_positions_name(target_positions)
    if level == 0:
        message = f"{positions_name}加热已关闭"
    else:
        message = f"{positions_name}加热已开启，档位: {LEVEL_NAMES.get(level, level)}"
    
    print(f"[seat_heat] 成功: {message}")
    
    data = {
        "positions": target_positions,
        "level": level,
        "enable": enable,
        "updated": updated
    }
    
    return {
        "success": True,
        "message": message,
        "data": data
    }


def seat_ventilation(state_file: str, positions: List[str] = None,
                     level: int = 0, enable: bool = False, **kwargs) -> Dict[str, Any]:
    """
    控制指定位置座椅通风，支持多区域同步
    
    Args:
        state_file: state.json 文件路径
        positions: 座位位置列表（多区域同步）
        level: 通风档位 0-3 (0=关闭, 1=弱风, 2=中风, 3=强风)
        enable: 开关状态
    """
    target_positions = _get_target_positions(positions)
    print(f"[seat_ventilation] 目标位置: {target_positions}, level={level}, enable={enable}")
    
    if not isinstance(level, int) or level < 0 or level > 3:
        return {"success": False, "message": f"档位必须在0-3之间，当前: {level}", "data": None}
    
    if level > 0 and not enable:
        enable = True
    if level == 0 and enable:
        enable = False
    
    state = _load_state(state_file)
    if "seat" not in state:
        state["seat"] = {}
    if "seat_ventilation" not in state["seat"]:
        state["seat"]["seat_ventilation"] = {}
    
    for pos in VALID_POSITIONS:
        if pos not in state["seat"]["seat_ventilation"]:
            state["seat"]["seat_ventilation"][pos] = {"level": 0, "enable": False}
    
    updated = []
    for pos in target_positions:
        old_level = state["seat"]["seat_ventilation"][pos]["level"]
        old_enable = state["seat"]["seat_ventilation"][pos]["enable"]
        
        state["seat"]["seat_ventilation"][pos]["level"] = level
        state["seat"]["seat_ventilation"][pos]["enable"] = enable
        
        updated.append({
            "position": pos,
            "level": level,
            "enable": enable,
            "previous_level": old_level,
            "previous_enable": old_enable
        })
    
    _save_state(state_file, state)
    
    positions_name = _format_positions_name(target_positions)
    if level == 0:
        message = f"{positions_name}通风已关闭"
    else:
        message = f"{positions_name}通风已开启，档位: {LEVEL_NAMES.get(level, level)}"
    
    print(f"[seat_ventilation] 成功: {message}")
    
    data = {
        "positions": target_positions,
        "level": level,
        "enable": enable,
        "updated": updated
    }
    
    return {
        "success": True,
        "message": message,
        "data": data
    }


def seat_massage(state_file: str, positions: List[str] = None,
                 level: int = 0, mode: str = "normal", enable: bool = False, **kwargs) -> Dict[str, Any]:
    """
    控制指定位置座椅按摩，支持多区域同步
    
    Args:
        state_file: state.json 文件路径
        positions: 座位位置列表（多区域同步）
        level: 按摩强度 0-3 (0=关闭, 1=轻柔, 2=标准, 3=强劲)
        mode: 按摩模式 (normal/wave/pulse/knead)
        enable: 开关状态
    """
    target_positions = _get_target_positions(positions)
    print(f"[seat_massage] 目标位置: {target_positions}, level={level}, mode={mode}, enable={enable}")
    
    if not isinstance(level, int) or level < 0 or level > 3:
        return {"success": False, "message": f"档位必须在0-3之间，当前: {level}", "data": None}
    
    valid_modes = ["normal", "wave", "pulse", "knead"]
    if mode not in valid_modes:
        mode = "normal"
    
    if level > 0 and not enable:
        enable = True
    if level == 0 and enable:
        enable = False
    
    state = _load_state(state_file)
    if "seat" not in state:
        state["seat"] = {}
    if "seat_massage" not in state["seat"]:
        state["seat"]["seat_massage"] = {}
    
    for pos in VALID_POSITIONS:
        if pos not in state["seat"]["seat_massage"]:
            state["seat"]["seat_massage"][pos] = {"level": 0, "mode": "normal", "enable": False}
    
    updated = []
    for pos in target_positions:
        old_level = state["seat"]["seat_massage"][pos]["level"]
        old_enable = state["seat"]["seat_massage"][pos]["enable"]
        old_mode = state["seat"]["seat_massage"][pos].get("mode", "normal")
        
        state["seat"]["seat_massage"][pos]["level"] = level
        state["seat"]["seat_massage"][pos]["mode"] = mode
        state["seat"]["seat_massage"][pos]["enable"] = enable
        
        updated.append({
            "position": pos,
            "level": level,
            "mode": mode,
            "enable": enable,
            "previous_level": old_level,
            "previous_enable": old_enable,
            "previous_mode": old_mode
        })
    
    _save_state(state_file, state)
    
    positions_name = _format_positions_name(target_positions)
    mode_name = MASSAGE_MODES.get(mode, mode)
    
    if level == 0:
        message = f"{positions_name}按摩已关闭"
    else:
        message = f"{positions_name}按摩已开启，强度: {LEVEL_NAMES.get(level, level)}，模式: {mode_name}"
    
    print(f"[seat_massage] 成功: {message}")
    
    data = {
        "positions": target_positions,
        "level": level,
        "mode": mode,
        "enable": enable,
        "updated": updated
    }
    
    return {
        "success": True,
        "message": message,
        "data": data
    }


def steering_wheel_heat(state_file: str, level: int = 0, enable: bool = False, **kwargs) -> Dict[str, Any]:
    """
    控制方向盘加热（无位置参数）
    """
    print(f"[steering_wheel_heat] level={level}, enable={enable}")
    
    if not isinstance(level, int) or level < 0 or level > 3:
        return {"success": False, "message": f"档位必须在0-3之间，当前: {level}", "data": None}
    
    if level > 0 and not enable:
        enable = True
    if level == 0 and enable:
        enable = False
    
    state = _load_state(state_file)
    if "seat" not in state:
        state["seat"] = {}
    
    old_level = state["seat"].get("steering_wheel_heat", {}).get("level", 0)
    old_enable = state["seat"].get("steering_wheel_heat", {}).get("enable", False)
    
    state["seat"]["steering_wheel_heat"] = {"level": level, "enable": enable}
    
    _save_state(state_file, state)
    
    if level == 0:
        message = "方向盘加热已关闭"
    else:
        message = f"方向盘加热已开启，档位: {LEVEL_NAMES.get(level, level)}"
    
    print(f"[steering_wheel_heat] 成功: {message}")
    
    return {
        "success": True,
        "message": message,
        "data": {
            "level": level,
            "enable": enable,
            "previous_level": old_level,
            "previous_enable": old_enable
        }
    }


# ================= 统一执行入口 =================
def execute(script: str, params: Dict[str, Any], state_file: str) -> Dict[str, Any]:
    """
    统一执行入口 V4 - 支持多区域同步
    """
    print(f"[Seat.execute] script={script}, state_file={state_file}, params={params}")
    
    # 移除无关参数
    params = {k: v for k, v in params.items() if k not in ["action", "position"]}
    params_with_state = {"state_file": state_file, **params}
    
    scripts = {
        "seat_heat": seat_heat,
        "seat_ventilation": seat_ventilation,
        "seat_massage": seat_massage,
        "steering_wheel_heat": steering_wheel_heat,
    }
    
    handler = scripts.get(script)
    if not handler:
        return {"success": False, "message": f"Seat Skill 不支持 script: {script}", "data": None}
    
    try:
        result = handler(**params_with_state)
        return result
    except Exception as e:
        import traceback
        error_msg = f"执行失败: {str(e)}"
        print(f"[Seat.execute] 错误: {error_msg}")
        return {"success": False, "message": error_msg, "data": {"traceback": traceback.format_exc()}}