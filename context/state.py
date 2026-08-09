# -*- coding: utf-8 -*-
"""
车辆状态管理 - 加载/保存/更新 state.json
"""
import json
import time
from typing import Dict, Any, List
from config.settings import STATE_FILE


def load_state():
    """从JSON文件加载车辆状态"""
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {}
    except Exception as e:
        print(f"[状态] 加载失败: {e}")
        return {}


def save_state(state):
    """保存车辆状态到JSON文件"""
    try:
        state["meta"]["last_updated"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        with open(STATE_FILE, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[状态] 保存失败: {e}")


def update_state(skill, function, parameters):
    """TOOL执行后更新状态"""
    state = load_state()
    if skill not in state:
        state[skill] = {}
    if function not in state[skill]:
        state[skill][function] = {}
    for key, value in parameters.items():
        state[skill][function][key] = value
    save_state(state)
    print(f"[状态] 已更新 {skill}.{function}: {parameters}")


def get_relevant_state(skill_names: List[str]) -> Dict[str, Any]:
    """获取选中技能相关的状态数据"""
    state = load_state()
    print(f"[状态] 加载 state.json: {len(state)} 个技能")
    
    relevant_state = {}
    
    for skill_name in skill_names:
        print(f"[状态] 检查技能: {skill_name}")
        if skill_name in state:
            skill_state = {k: v for k, v in state[skill_name].items() if k != "meta"}
            if skill_state:
                relevant_state[skill_name] = skill_state
                print(f"[状态] 找到 {skill_name} 状态: {list(skill_state.keys())}")
        else:
            print(f"[状态] {skill_name} 不在状态中")
    
    return relevant_state
