# -*- coding: utf-8 -*-
"""
Air Conditioner Skill Handler V4 - 五区域独立控制版本

V4 变更：
- 支持五个独立空调区域：front_left, front_right, rear_left, rear_right, rear_middle
- 每个区域有独立的 temperature 和 fan_level 状态
- 默认操作 front_left（驾驶位）
【已清理】仅保留 temperature + zones，删除 value/temp/zone
"""

import json
import os
from typing import Dict, Any, Optional

# ================= 常量定义 =================
ZONE_NAMES = {
    "front_left": "前排左区",
    "front_right": "前排右区",
    "rear_left": "后排左区",
    "rear_right": "后排右区",
    "rear_middle": "后排中区",
    "driver": "前排左区",
    "passenger": "前排右区",
    "rear": "后排",
    "all": "全车"
}

MODE_NAMES = {
    "cool": "制冷",
    "heat": "制热",
    "fan_only": "通风",
    "defrost": "前挡除霜",
    "defrost_feet": "除霜+脚部",
    "auto": "自动"
}

DIRECTION_NAMES = {
    "face": "面部",
    "foot": "脚部",
    "defrost": "前挡玻璃",
    "face_foot": "面部+脚部",
    "auto": "自动"
}

VALID_ZONES = ["front_left", "front_right", "rear_left", "rear_right", "rear_middle"]


# ================= 状态读写工具 =================
def load_state(state_file: str) -> Dict[str, Any]:
    """从 state.json 加载状态"""
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[AirConditioner] 加载状态失败: {e}")
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
        print(f"[AirConditioner] 保存状态失败: {e}")
    return False


def get_air_conditioner_state(full_state: Dict) -> Dict[str, Any]:
    """获取 air_conditioner 部分的当前状态（V4 结构）"""
    default_state = {
        "power_control": {"enable": False, "auto_mode": "comfort"},
        "set_temperature": {
            "front_left": {"value": 22.0, "unit": "celsius"},
            "front_right": {"value": 22.0, "unit": "celsius"},
            "rear_left": {"value": 22.0, "unit": "celsius"},
            "rear_right": {"value": 22.0, "unit": "celsius"},
            "rear_middle": {"value": 22.0, "unit": "celsius"}
        },
        "adjust_fan": {
            "front_left": {"level": 2},
            "front_right": {"level": 2},
            "rear_left": {"level": 2},
            "rear_right": {"level": 2},
            "rear_middle": {"level": 2}
        },
        "set_mode": {
            "mode": "auto",
            "direction": "auto",
            "intensity": "normal",
            "recirculation": False
        },
        "zone_control": {
            "front_left": True,
            "front_right": True,
            "rear_left": True,
            "rear_right": True,
            "rear_middle": True
        }
    }
    return full_state.get("air_conditioner", default_state)


def _validate_zone(zone: str) -> str:
    """验证并标准化区域参数"""
    zone_map = {
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
        "后排中间": "rear_middle",
        "rear": "rear_left",
        "后排": "rear_left",
        "all": "all",
        "全车": "all"
    }
    return zone_map.get(zone, zone if zone in VALID_ZONES or zone == "all" else "front_left")


# ================= 核心函数 =================
def power_control(
    state_file: str,
    enable: bool = True,
    auto_mode: str = "comfort"
) -> Dict[str, Any]:
    """空调总电源开关"""
    full_state = load_state(state_file)
    ac_state = get_air_conditioner_state(full_state)
    
    ac_state["power_control"] = {
        "enable": enable,
        "auto_mode": auto_mode
    }
    
    full_state["air_conditioner"] = ac_state
    save_state(state_file, full_state)
    
    if enable:
        mode_desc = {"eco": "节能模式", "auto": "自动模式", "comfort": "舒适模式"}.get(auto_mode, "舒适模式")
        temp = ac_state.get("set_temperature", {}).get("front_left", {}).get("value", 22)
        return {
            "success": True,
            "message": f"空调已开启，驾驶位温度{temp:.0f}°C，{mode_desc}",
            "data": {"enable": True, "auto_mode": auto_mode, "temperature": temp}
        }
    else:
        return {
            "success": True,
            "message": "空调已关闭",
            "data": {"enable": False}
        }


def set_temperature(
    state_file: str,
    temperature: float = 24.0,
    zones: list = None
) -> Dict[str, Any]:
    """设置指定区域温度（绝对值），支持多区域同步设置"""
    target = temperature

    # 仅处理 zones 参数（列表/字符串）
    target_zones = []
    if zones is not None:
        if isinstance(zones, str):
            target_zones = [zones]
        elif isinstance(zones, list):
            target_zones = zones
    else:
        target_zones = ["front_left"]  # 默认
    
    # 标准化所有区域
    normalized_zones = []
    for z in target_zones:
        nz = _validate_zone(z)
        if nz == "all":
            normalized_zones = VALID_ZONES.copy()
            break
        elif nz in VALID_ZONES:
            normalized_zones.append(nz)
    
    # 去重
    normalized_zones = list(dict.fromkeys(normalized_zones))
    
    # 加载状态
    full_state = load_state(state_file)
    ac_state = get_air_conditioner_state(full_state)
    
    new_temp = max(16.0, min(30.0, float(target)))
    
    # 智能联动：如果空调关闭，自动开启
    power_was_off = not ac_state.get("power_control", {}).get("enable", False)
    if power_was_off:
        ac_state["power_control"] = {"enable": True, "auto_mode": "comfort"}
    
    # 初始化 temperature 结构
    if "set_temperature" not in ac_state:
        ac_state["set_temperature"] = {}
    for z in VALID_ZONES:
        if z not in ac_state["set_temperature"]:
            ac_state["set_temperature"][z] = {"value": 22.0, "unit": "celsius"}
    
    # 更新所有指定区域的温度
    for z in normalized_zones:
        ac_state["set_temperature"][z]["value"] = new_temp
    
    # 生成区域描述
    if set(normalized_zones) == set(VALID_ZONES):
        zone_name = "全车"
    elif set(normalized_zones) == {"front_left", "front_right"}:
        zone_name = "前排"
    elif set(normalized_zones) == {"rear_left", "rear_middle", "rear_right"}:
        zone_name = "后排"
    elif len(normalized_zones) == 1:
        zone_name = ZONE_NAMES.get(normalized_zones[0], normalized_zones[0])
    else:
        zone_names = [ZONE_NAMES.get(z, z) for z in normalized_zones]
        zone_name = ",".join(zone_names)
    
    full_state["air_conditioner"] = ac_state
    save_state(state_file, full_state)
    
    power_msg = "空调已自动开启，" if power_was_off else ""
    
    data = {
        "temperature": new_temp,
        "zones": normalized_zones,
        "power_auto_on": power_was_off
    }
    
    return {
        "success": True,
        "message": f"{power_msg}{zone_name}温度已设置为{new_temp:.0f}°C",
        "data": data
    }


def adjust_fan(
    state_file: str,
    level: int = 3,
    zones: list = None,
    enable: bool = None
) -> Dict[str, Any]:
    """调节指定区域风量（绝对值），支持多区域同步设置"""
    
    # 仅处理 zones 参数
    target_zones = []
    if zones is not None:
        if isinstance(zones, str):
            target_zones = [zones]
        elif isinstance(zones, list):
            target_zones = zones
    else:
        target_zones = ["front_left"]  # 默认
    
    # 标准化所有区域
    normalized_zones = []
    for z in target_zones:
        nz = _validate_zone(z)
        if nz == "all":
            normalized_zones = VALID_ZONES.copy()
            break
        elif nz in VALID_ZONES:
            normalized_zones.append(nz)
    
    # 去重
    normalized_zones = list(dict.fromkeys(normalized_zones))
    
    full_state = load_state(state_file)
    ac_state = get_air_conditioner_state(full_state)
    
    # 处理 enable 参数
    if enable is not None:
        if not enable:
            new_level = 0
        else:
            new_level = max(1, min(7, int(level)))
    else:
        new_level = max(0, min(7, int(level)))
    
    # 智能联动
    power_was_off = False
    if new_level > 0 and not ac_state.get("power_control", {}).get("enable", False):
        ac_state["power_control"] = {"enable": True, "auto_mode": "comfort"}
        power_was_off = True
    
    # 初始化 fan 结构
    if "adjust_fan" not in ac_state:
        ac_state["adjust_fan"] = {}
    for z in VALID_ZONES:
        if z not in ac_state["adjust_fan"]:
            ac_state["adjust_fan"][z] = {"level": 2}
    
    # 更新所有指定区域的风量
    for z in normalized_zones:
        ac_state["adjust_fan"][z]["level"] = new_level
    
    # 生成区域描述
    if set(normalized_zones) == set(VALID_ZONES):
        zone_name = "全车"
    elif set(normalized_zones) == {"front_left", "front_right"}:
        zone_name = "前排"
    elif set(normalized_zones) == {"rear_left", "rear_middle", "rear_right"}:
        zone_name = "后排"
    elif len(normalized_zones) == 1:
        zone_name = ZONE_NAMES.get(normalized_zones[0], normalized_zones[0])
    else:
        zone_names = [ZONE_NAMES.get(z, z) for z in normalized_zones]
        zone_name = ",".join(zone_names)
    
    full_state["air_conditioner"] = ac_state
    save_state(state_file, full_state)
    
    msg = f"{zone_name}风量设置为{new_level}档"
    if power_was_off:
        msg = "空调已自动开启，" + msg
    
    data = {
        "level": new_level,
        "zones": normalized_zones,
        "power_auto_on": power_was_off
    }
    
    return {
        "success": True,
        "message": msg,
        "data": data
    }


def set_mode(
    state_file: str,
    mode: str = "auto",
    direction: str = "auto",
    intensity: str = "normal",
    recirculation: bool = False
) -> Dict[str, Any]:
    """模式与风向设置"""
    full_state = load_state(state_file)
    ac_state = get_air_conditioner_state(full_state)
    
    mode_name = MODE_NAMES.get(mode, mode)
    
    # 智能联动
    power_was_off = False
    if not ac_state.get("power_control", {}).get("enable", False):
        ac_state["power_control"] = {"enable": True, "auto_mode": "comfort"}
        power_was_off = True
    
    ac_state["set_mode"] = {
        "mode": mode,
        "direction": direction,
        "intensity": intensity,
        "recirculation": recirculation
    }
    
    # 除霜模式自动提高风速
    if mode in ["defrost", "defrost_feet"]:
        if "adjust_fan" not in ac_state:
            ac_state["adjust_fan"] = {}
        for z in VALID_ZONES:
            if z not in ac_state["adjust_fan"]:
                ac_state["adjust_fan"][z] = {"level": 2}
            ac_state["adjust_fan"][z]["level"] = 5
    
    full_state["air_conditioner"] = ac_state
    save_state(state_file, full_state)
    
    msg = f"空调模式设置为{mode_name}"
    if power_was_off:
        msg = "空调已自动开启，" + msg
    
    return {
        "success": True,
        "message": msg,
        "data": {"mode": mode, "direction": direction, "intensity": intensity, 
                 "recirculation": recirculation, "power_auto_on": power_was_off}
    }


def zone_control(
    state_file: str,
    zones: list = None,
    enable: bool = True
) -> Dict[str, Any]:
    """独立控制特定区域的空调开关，支持多区域同步控制"""
    
    # 仅处理 zones 参数
    target_zones = []
    if zones is not None:
        if isinstance(zones, str):
            target_zones = [zones]
        elif isinstance(zones, list):
            target_zones = zones
    else:
        target_zones = ["front_left"]  # 默认
    
    # 标准化所有区域
    normalized_zones = []
    for z in target_zones:
        nz = _validate_zone(z)
        if nz == "all":
            normalized_zones = VALID_ZONES.copy()
            break
        elif nz in VALID_ZONES:
            normalized_zones.append(nz)
    
    # 去重
    normalized_zones = list(dict.fromkeys(normalized_zones))
    
    full_state = load_state(state_file)
    ac_state = get_air_conditioner_state(full_state)
    
    if "zone_control" not in ac_state:
        ac_state["zone_control"] = {z: True for z in VALID_ZONES}
    
    # 更新所有指定区域的开关状态
    for z in normalized_zones:
        ac_state["zone_control"][z] = enable
    
    # 生成区域描述
    if set(normalized_zones) == set(VALID_ZONES):
        zone_name = "全车"
    elif set(normalized_zones) == {"front_left", "front_right"}:
        zone_name = "前排"
    elif set(normalized_zones) == {"rear_left", "rear_middle", "rear_right"}:
        zone_name = "后排"
    elif len(normalized_zones) == 1:
        zone_name = ZONE_NAMES.get(normalized_zones[0], normalized_zones[0])
    else:
        zone_names = [ZONE_NAMES.get(z, z) for z in normalized_zones]
        zone_name = ",".join(zone_names)
    
    full_state["air_conditioner"] = ac_state
    save_state(state_file, full_state)
    
    action = "开启" if enable else "关闭"
    
    data = {
        "zones": normalized_zones,
        "enable": enable
    }
    
    return {
        "success": True,
        "message": f"{zone_name}空调已{action}",
        "data": data
    }


def execute(script: str, parameters: Dict[str, Any], state_file: str) -> Dict[str, Any]:
    """执行指定函数，支持多区域操作"""
    func_map = {
        "power_control": power_control,
        "set_temperature": set_temperature,
        "adjust_fan": adjust_fan,
        "set_mode": set_mode,
        "zone_control": zone_control
    }
    
    if script not in func_map:
        return {
            "success": False,
            "message": f"不支持的函数: {script}",
            "data": {}
        }
    
    try:
        params = parameters.copy()
        params["state_file"] = state_file
        result = func_map[script](**params)
        return result
    except Exception as e:
        import traceback
        print(f"[AirConditioner] 执行 {script} 失败: {e}")
        traceback.print_exc()
        return {
            "success": False,
            "message": f"执行失败: {str(e)}",
            "data": {}
        }