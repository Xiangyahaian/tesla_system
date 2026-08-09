# -*- coding: utf-8 -*-
"""
Vehicle Skill Handler V4 - 四位置车窗车门控制版本

V4 变更：
- 添加 control_window: 四位置车窗独立控制
- 添加 control_door: 四位置车门独立锁止/解锁
- 添加 control_trunk: 后备箱/充电口/前备箱控制
"""

import json
import os
from typing import Dict, Any

# ================= 常量定义 =================
ZONE_NAMES = {
    "front_left": "前排左",
    "front_right": "前排右",
    "rear_left": "后排左",
    "rear_right": "后排右",
    "all": "全车"
}

VALID_POSITIONS = ["front_left", "front_right", "rear_left", "rear_right"]


# ================= 状态读写工具 =================
def load_state(state_file: str) -> Dict[str, Any]:
    """从 state.json 加载状态"""
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception as e:
        print(f"[Vehicle] 加载状态失败: {e}")
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
        print(f"[Vehicle] 保存状态失败: {e}")
        return False


def get_vehicle_state(full_state: Dict) -> Dict[str, Any]:
    """获取 vehicle 部分的当前状态（V4 结构）"""
    default_state = {
        "control_adas": {},
        "control_window": {
            "front_left": {"open": False, "level": 0},
            "front_right": {"open": False, "level": 0},
            "rear_left": {"open": False, "level": 0},
            "rear_right": {"open": False, "level": 0}
        },
        "control_door": {
            "front_left": {"locked": True},
            "front_right": {"locked": True},
            "rear_left": {"locked": True},
            "rear_right": {"locked": True}
        },
        "control_trunk": {
            "trunk": {"open": False},
            "charge_port": {"open": False},
            "frunk": {"open": False}
        },
        "switch_drive_mode": {"mode": "comfort"},
        "query_status": {"battery": 78, "range": 350}
    }
    return full_state.get("vehicle", default_state)


def _validate_position(position: str, default: str = "front_left") -> str:
    """验证并标准化位置参数"""
    position_map = {
        "driver": "front_left",
        "驾驶位": "front_left",
        "主驾": "front_left",
        "左前": "front_left",
        "passenger": "front_right",
        "副驾": "front_right",
        "副驾驶": "front_right",
        "右前": "front_right",
        "rear_left": "rear_left",
        "左后": "rear_left",
        "后排左侧": "rear_left",
        "左后门": "rear_left",
        "rear_right": "rear_right",
        "右后": "rear_right",
        "后排右侧": "rear_right",
        "右后门": "rear_right",
        "all": "all",
        "全车": "all",
        "全部": "all"
    }
    result = position_map.get(position, position)
    if result not in VALID_POSITIONS and result != "all":
        return default
    return result


# ================= 核心函数 =================
def control_adas(
    state_file: str,
    feature: str = "",
    enable: bool = True
) -> Dict[str, Any]:
    """驾驶辅助控制"""
    feature_names = {
        "auto_hold": "自动驻车",
        "auto_start_stop": "自动启停",
        "acc": "自适应巡航",
        "lane_keep": "车道保持",
        "auto_park": "自动泊车",
        "aeb": "自动紧急制动"
    }
    feature_name = feature_names.get(feature, feature)
    
    # 更新状态
    full_state = load_state(state_file)
    vehicle_state = get_vehicle_state(full_state)
    
    if "control_adas" not in vehicle_state:
        vehicle_state["control_adas"] = {}
    vehicle_state["control_adas"][feature] = {"enable": enable}
    
    full_state["vehicle"] = vehicle_state
    save_state(state_file, full_state)
    
    msg = f"{feature_name}已{'开启' if enable else '关闭'}"
    
    return {
        "success": True,
        "message": msg,
        "data": {"feature": feature, "enable": enable}
    }


def control_window(
    state_file: str,
    position: str = "front_left",
    action: str = "open",
    level: int = 100
) -> Dict[str, Any]:
    """
    控制指定位置车窗
    
    Args:
        position: 车窗位置 (front_left/front_right/rear_left/rear_right/all)
        action: 操作类型 (open/close/vent)
        level: 开合程度 0-100%，默认100
    """
    position = _validate_position(position, "front_left")
    
    full_state = load_state(state_file)
    vehicle_state = get_vehicle_state(full_state)
    
    # 初始化 window 结构
    if "control_window" not in vehicle_state:
        vehicle_state["control_window"] = {}
    for pos in VALID_POSITIONS:
        if pos not in vehicle_state["control_window"]:
            vehicle_state["control_window"][pos] = {"open": False, "level": 0}
    
    # 执行操作
    if action == "open":
        target_level = max(0, min(100, int(level)))
        if position == "all":
            for pos in VALID_POSITIONS:
                vehicle_state["control_window"][pos] = {"open": True, "level": target_level}
            msg = f"所有车窗已打开至{target_level}%"
        else:
            vehicle_state["control_window"][position] = {"open": True, "level": target_level}
            zone_name = ZONE_NAMES.get(position, position)
            msg = f"{zone_name}车窗已打开至{target_level}%"
    
    elif action == "close":
        if position == "all":
            for pos in VALID_POSITIONS:
                vehicle_state["control_window"][pos] = {"open": False, "level": 0}
            msg = "所有车窗已关闭"
        else:
            vehicle_state["control_window"][position] = {"open": False, "level": 0}
            zone_name = ZONE_NAMES.get(position, position)
            msg = f"{zone_name}车窗已关闭"
    
    elif action == "vent":
        # 通风模式：微开约10%
        if position == "all":
            for pos in VALID_POSITIONS:
                vehicle_state["control_window"][pos] = {"open": True, "level": 10}
            msg = "所有车窗已微开通风"
        else:
            vehicle_state["control_window"][position] = {"open": True, "level": 10}
            zone_name = ZONE_NAMES.get(position, position)
            msg = f"{zone_name}车窗已微开通风"
    
    else:
        return {"success": False, "message": f"无效的操作类型: {action}", "data": None}
    
    full_state["vehicle"] = vehicle_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {"position": position, "action": action, "level": level if action == "open" else 0}
    }


def control_door(
    state_file: str,
    position: str = "all",
    action: str = "lock"
) -> Dict[str, Any]:
    """
    控制指定位置车门锁止/解锁
    
    Args:
        position: 车门位置 (front_left/front_right/rear_left/rear_right/all)
        action: 操作类型 (lock/unlock)
    """
    position = _validate_position(position, "all")
    
    full_state = load_state(state_file)
    vehicle_state = get_vehicle_state(full_state)
    
    # 初始化 door 结构
    if "control_door" not in vehicle_state:
        vehicle_state["control_door"] = {}
    for pos in VALID_POSITIONS:
        if pos not in vehicle_state["control_door"]:
            vehicle_state["control_door"][pos] = {"locked": True}
    
    # 执行操作
    if action == "lock":
        if position == "all":
            for pos in VALID_POSITIONS:
                vehicle_state["control_door"][pos] = {"locked": True}
            msg = "所有车门已锁止"
        else:
            vehicle_state["control_door"][position] = {"locked": True}
            zone_name = ZONE_NAMES.get(position, position)
            msg = f"{zone_name}车门已锁止"
    
    elif action == "unlock":
        if position == "all":
            for pos in VALID_POSITIONS:
                vehicle_state["control_door"][pos] = {"locked": False}
            msg = "所有车门已解锁"
        else:
            vehicle_state["control_door"][position] = {"locked": False}
            zone_name = ZONE_NAMES.get(position, position)
            msg = f"{zone_name}车门已解锁"
    
    else:
        return {"success": False, "message": f"无效的操作类型: {action}", "data": None}
    
    full_state["vehicle"] = vehicle_state
    save_state(state_file, full_state)
    
    return {
        "success": True,
        "message": msg,
        "data": {"position": position, "action": action}
    }


def control_trunk(
    state_file: str,
    target: str = "trunk",
    action: str = "open"
) -> Dict[str, Any]:
    """
    控制后备箱/充电口/前备箱
    
    Args:
        target: 控制目标 (trunk/charge_port/frunk)
        action: 操作类型 (open/close)
    """
    valid_targets = ["trunk", "charge_port", "frunk"]
    if target not in valid_targets:
        return {"success": False, "message": f"无效的目标: {target}", "data": None}
    
    target_names = {
        "trunk": "后备箱",
        "charge_port": "充电口",
        "frunk": "前备箱"
    }
    
    full_state = load_state(state_file)
    vehicle_state = get_vehicle_state(full_state)
    
    # 初始化 trunk 结构
    if "control_trunk" not in vehicle_state:
        vehicle_state["control_trunk"] = {}
    for t in valid_targets:
        if t not in vehicle_state["control_trunk"]:
            vehicle_state["control_trunk"][t] = {"open": False}
    
    is_open = (action == "open")
    vehicle_state["control_trunk"][target] = {"open": is_open}
    
    full_state["vehicle"] = vehicle_state
    save_state(state_file, full_state)
    
    target_name = target_names.get(target, target)
    msg = f"{target_name}已{'打开' if is_open else '关闭'}"
    
    return {
        "success": True,
        "message": msg,
        "data": {"target": target, "action": action, "open": is_open}
    }


def switch_drive_mode(
    state_file: str,
    mode: str = "comfort",
    custom: Dict[str, Any] = None
) -> Dict[str, Any]:
    """驾驶模式切换"""
    mode_names = {"sport": "运动模式", "comfort": "舒适模式", "eco": "节能模式", "offroad": "越野模式", "snow": "雪地模式"}
    mode_name = mode_names.get(mode, mode)
    
    full_state = load_state(state_file)
    vehicle_state = get_vehicle_state(full_state)
    vehicle_state["switch_drive_mode"] = {"mode": mode}
    full_state["vehicle"] = vehicle_state
    save_state(state_file, full_state)
    
    msg = f"已切换至{mode_name}"
    mode_desc = {
        "sport": "油门响应灵敏，转向加重，悬挂变硬",
        "comfort": "平衡舒适与操控",
        "eco": "节能优先，降低能耗",
        "offroad": "提高底盘，增强牵引力",
        "snow": "平缓起步，防滑控制"
    }
    if mode in mode_desc:
        msg += f" - {mode_desc[mode]}"
    
    return {
        "success": True,
        "message": msg,
        "data": {"mode": mode, "custom": custom}
    }


def query_status(
    state_file: str,
    metric: str = "status",
    detail: bool = False
) -> Dict[str, Any]:
    """车辆状态查询"""
    metric_names = {
        "status": "整体状态", "battery": "电池电量", "fuel": "燃油量",
        "tire_pressure": "胎压", "oil": "机油状态", "range": "续航里程",
        "consumption": "能耗/油耗"
    }
    metric_name = metric_names.get(metric, metric)
    
    mock_data = {
        "status": "车辆状态良好，所有系统正常",
        "battery": "电池电量 78%，约可行驶 350 公里",
        "fuel": "燃油量 65%，约可行驶 400 公里",
        "tire_pressure": "胎压正常：前胎 2.4bar，后胎 2.5bar",
        "oil": "机油状态良好，剩余寿命 85%",
        "range": "综合续航约 450 公里",
        "consumption": "百公里油耗 6.8L / 电耗 15.2kWh"
    }
    
    msg = f"查询{metric_name}：{mock_data.get(metric, '数据获取中')}"
    
    return {
        "success": True,
        "message": msg,
        "data": {"metric": metric, "value": mock_data.get(metric, ""), "detail": detail}
    }


def manage_maintenance(
    state_file: str,
    action: str = "diagnose",
    issue: str = ""
) -> Dict[str, Any]:
    """维保管理"""
    if action == "diagnose":
        if "故障灯" in issue or "报警" in issue:
            msg = "正在诊断故障... 检测到：发动机故障灯亮起，建议尽快到店检查"
        else:
            msg = f"正在诊断：{issue}"
    elif action == "schedule":
        msg = "已打开保养预约界面，请选择预约时间"
    elif action == "history":
        msg = "显示维保历史记录"
    elif action == "alert":
        msg = "当前无警报"
    else:
        msg = "维保信息已更新"
    
    return {
        "success": True,
        "message": msg,
        "data": {"action": action, "issue": issue}
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
    print(f"[Vehicle.execute] script={script}, params={params}")
    
    params = {k: v for k, v in params.items() if k != "action"}
    params_with_state = {"state_file": state_file, **params}
    
    scripts = {
        "control_adas": control_adas,
        "control_window": control_window,
        "control_door": control_door,
        "control_trunk": control_trunk,
        "query_status": query_status,
        "manage_maintenance": manage_maintenance,
        "switch_drive_mode": switch_drive_mode,
    }
    
    handler = scripts.get(script)
    if not handler:
        return {"success": False, "message": f"Vehicle Skill 不支持 script: {script}", "data": None}
    
    try:
        result = handler(**params_with_state)
        print(f"[Vehicle.execute] 成功: {result['message']}")
        return result
    except Exception as e:
        import traceback
        error_msg = f"执行失败: {str(e)}"
        print(f"[Vehicle.execute] 错误: {error_msg}")
        return {"success": False, "message": error_msg, "data": {"traceback": traceback.format_exc()}}
