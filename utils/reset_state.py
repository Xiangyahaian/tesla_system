# -*- coding: utf-8 -*-
"""
车辆状态重置模块
用于汽车重启时恢复 state.json 和 memory.json 到初始状态
"""
import json
import os
from pathlib import Path
from datetime import datetime


def get_project_root() -> Path:
    """获取项目根目录"""
    # 从当前文件位置向上回溯找到项目根目录
    current_file = Path(__file__).resolve()
    # utils/reset_state.py -> 项目根目录
    return current_file.parent.parent


def get_initial_state() -> dict:
    """获取初始状态配置"""
    return {
        "meta": {
            "version": "V12",
            "last_updated": datetime.now().isoformat(),
            "description": "Tesla车载系统状态"
        },
        "media": {
            "music_control": {
                "action": "stop",
                "source": "local",
                "artist": None,
                "title": None,
                "album": None,
                "playing": False
            },
            "music_switch": {
                "direction": None,
                "current_index": -1
            },
            "radio_control": {
                "action": "stop",
                "band": None,
                "frequency": None,
                "station_name": None,
                "category": None,
                "playing": False
            },
            "radio_switch": {
                "direction": None,
                "current_index": -1
            },
            "volume_control": {
                "volume": 50,
                "muted": False
            }
        },
        "hardware": {
            "control_window": {
                "front_left": {"percent": 0},
                "front_right": {"percent": 0},
                "rear_left": {"percent": 0},
                "rear_right": {"percent": 0},
                "sunroof": {"percent": 0}
            },
            "control_lighting": {
                "dome": {"brightness": 0, "enable": False},
                "ambient": {"brightness": 0, "enable": False, "color": "white"},
                "reading_left": {"brightness": 0, "enable": False},
                "reading_right": {"brightness": 0, "enable": False}
            },
            "control_display": {
                "center_screen": {"brightness": 50},
                "instrument": {"brightness": 50},
                "hud": {"brightness": 50}
            },
            "trunk_control": {
                "state": "closed"
            },
            "door_lock": {
                "front_left": {"locked": True},
                "front_right": {"locked": True},
                "rear_left": {"locked": True},
                "rear_right": {"locked": True}
            }
        },
        "air_conditioner": {
            "control": {
                "front_left": False,
                "front_right": False,
                "rear_left": False,
                "rear_right": False,
                "rear_middle": False
            },
            "set_temperature": {
                "front_left": {"value": 22, "unit": "celsius"},
                "front_right": {"value": 22, "unit": "celsius"},
                "rear_left": {"value": 22, "unit": "celsius"},
                "rear_right": {"value": 22, "unit": "celsius"},
                "rear_middle": {"value": 22, "unit": "celsius"}
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
            }
        },
        "seat": {
            "seat_heat": {
                "front_left": {"level": 0, "enable": False},
                "front_right": {"level": 0, "enable": False},
                "rear_left": {"level": 0, "enable": False},
                "rear_right": {"level": 0, "enable": False},
                "rear_middle": {"level": 0, "enable": False}
            },
            "seat_ventilation": {
                "front_left": {"level": 0, "enable": False},
                "front_right": {"level": 0, "enable": False},
                "rear_left": {"level": 0, "enable": False},
                "rear_right": {"level": 0, "enable": False},
                "rear_middle": {"level": 0, "enable": False}
            },
            "seat_massage": {
                "front_left": {"level": 0, "mode": "normal", "enable": False},
                "front_right": {"level": 0, "mode": "normal", "enable": False},
                "rear_left": {"level": 0, "mode": "normal", "enable": False},
                "rear_right": {"level": 0, "mode": "normal", "enable": False},
                "rear_middle": {"level": 0, "mode": "normal", "enable": False}
            },
            "steering_wheel_heat": {
                "level": 0,
                "enable": False
            }
        },
        "navigation": {
            "navigate_to": {
                "destination": None,
                "destination_type": None,
                "routing_preference": "fastest",
                "navigating": False
            },
            "query_traffic": {
                "last_query": None,
                "traffic_condition": None
            }
        },
        "vehicle": {
            "control_adas": {
                "auto_hold": {"enable": False},
                "lane_keep": {"enable": False}
            },
            "control_trunk": {
                "trunk": {"open": False},
                "charge_port": {"open": False},
                "frunk": {"open": False}
            },
            "switch_drive_mode": {
                "mode": "comfort"
            },
            "query_status": {
                "battery": 78,
                "range": 350
            }
        }
    }


def get_initial_memory() -> dict:
    """获取初始记忆配置（归零）"""
    return {
        "meta": {
            "last_updated": datetime.now().isoformat(),
            "total_entries": 0,
            "version": "1.0"
        },
        "memories": []
    }


def reset_all_states(verbose: bool = True) -> dict:
    """
    重置所有状态文件到初始状态
    
    Args:
        verbose: 是否打印日志
        
    Returns:
        dict: 重置结果统计
    """
    project_root = get_project_root()
    state_dir = project_root / "state"
    
    result = {
        "state_reset": False,
        "memory_reset": False,
        "errors": []
    }
    
    # 确保 state 目录存在
    state_dir.mkdir(parents=True, exist_ok=True)
    
    # 1. 重置 state.json
    state_file = state_dir / "state.json"
    try:
        initial_state = get_initial_state()
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(initial_state, f, ensure_ascii=False, indent=2)
        result["state_reset"] = True
        if verbose:
            print(f"[Reset] state.json 已重置为初始状态")
    except Exception as e:
        result["errors"].append(f"state.json 重置失败: {str(e)}")
        if verbose:
            print(f"[Reset Error] state.json 重置失败: {str(e)}")
    
    # 2. 重置 memory.json（归零）
    memory_file = state_dir / "memory.json"
    try:
        initial_memory = get_initial_memory()
        with open(memory_file, 'w', encoding='utf-8') as f:
            json.dump(initial_memory, f, ensure_ascii=False, indent=2)
        result["memory_reset"] = True
        if verbose:
            print(f"[Reset] memory.json 已清空（记忆归零）")
    except Exception as e:
        result["errors"].append(f"memory.json 重置失败: {str(e)}")
        if verbose:
            print(f"[Reset Error] memory.json 重置失败: {str(e)}")
    
    if verbose and not result["errors"]:
        print(f"[Reset] 所有状态文件重置完成，系统已恢复初始状态")
    
    return result


if __name__ == "__main__":
    # 直接运行脚本时执行重置
    reset_all_states(verbose=True)
