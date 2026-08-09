# -*- coding: utf-8 -*-
"""
单工具和多工具的函数选择（State-Aware）
"""
import json
from typing import Dict, Any, List, Optional
from context.models import FunctionCall
from context.skills import build_complete_function_prompt
from context.state import get_relevant_state, load_state
from context.utils import extract_json


def build_function_selection_prompt(skill_names: List[str], query: str, current_state: Dict[str, Any] = None) -> str:
    """构建State-Aware函数选择提示词，带完整参数定义
    
    修改说明：
    - 当 skill_names 包含 "media" 时，不显示 ### 5-10 的区域控制规则
    - 其他功能保持不变
    """
    complete_function_defs = build_complete_function_prompt(skill_names)
    
    state_text = ""
    if current_state:
        state_json = json.dumps(current_state, ensure_ascii=False, indent=2)
        state_text = f"""
## 当前车辆状态（执行前）
以下是与选中技能相关的当前车辆状态数据，这些是当前的真实数值：
```json
{state_json}
```
"""
    
    media_hint = ""
    if "media" in skill_names:
        media_hint = """
## 【重要】媒体技能选择规则
调用 `media.music_control` 播放本地音乐时：
1. 必须从 media 技能文档中定义的20首本地音乐库中选择
2. 必须提供全部三个参数：artist, title, album
3. 如果用户只说"播放周杰伦"，则选择该艺术家的第一首歌
4. 如果指定歌曲不在20首库中，返回错误

调用 `media.radio_control` 播放电台时：
1. 必须从 media 技能文档中定义的10个预设电台中选择
2. 必须提供：band, frequency, station_name
"""
    
    # 非media技能时添加5-10规则
    location_rules = ""
    if "media" not in skill_names:
        location_rules = """

### 5. 区域识别（重要）
- 用户说"副驾"、"后排"，要正确识别 zones/position 参数
- **zones 参数必须是列表格式**，例如：`["front_left"]` 或 `["rear_left", "rear_middle", "rear_right"]`

### 6. 空调控制逻辑
- **control 函数是统一开关**：`control(enable=true/false, zones=[...])`
- "打开空调"（未指定区域）-> `control(enable=true)` - 打开全部5个位置
- "关闭空调"（未指定区域）-> `control(enable=false)` - 关闭所有已打开的位置  
- "打开后排空调" -> `control(enable=true, zones=["rear_left","rear_middle","rear_right"])`
- "关闭副驾空调" -> `control(enable=false, zones=["front_right"])`
- 只操作一个位置时也要用列表：`["front_left"]`

### 7. 座椅控制逻辑
- **seat_heat/seat_ventilation/seat_massage 支持多区域同步**
- 使用 `positions` 数组参数传递多个位置：`["rear_left", "rear_middle", "rear_right"]`
- "打开后排所有座椅加热" -> `seat_heat(positions=["rear_left","rear_middle","rear_right"], level=2, enable=true)`
- "全车座椅通风打开" -> `seat_ventilation(positions=["front_left","front_right","rear_left","rear_middle","rear_right"], level=2, enable=true)`
- "前排按摩打开" -> `seat_massage(positions=["front_left","front_right"], level=2, enable=true)`
- 单个位置也要用数组：`["front_left"]`
- 未指定位置时默认 `front_left`（驾驶位）

### 8. 车窗控制逻辑
- **control_window 支持多位置同步**
- 使用 `positions` 数组传递多个位置：`["front_left", "front_right", "rear_left", "rear_right"]`
- "关闭所有车窗" -> `control_window(positions=["front_left","front_right","rear_left","rear_right"], percent=0)`
- "打开前排车窗" -> `control_window(positions=["front_left","front_right"], percent=50)`
- 单个位置也要用数组：`["front_left"]`
- **默认行为：未指定位置时默认 `front_left`（主驾），不是全车！**（与空调不同）
- "打开车窗" -> `control_window(positions=["front_left"], percent=50)`（仅主驾）

### 9. 车门锁控制逻辑
- **door_lock 支持多位置同步**
- 使用 `positions` 数组传递多个位置
- "前排解锁" -> `door_lock(positions=["front_left","front_right"], action="unlock")`
- "解锁右后门" -> `door_lock(positions=["rear_right"], action="unlock")`
- **默认行为：当未指定位置时默认 `front_left`（主驾），而不是全车！**

### 10. 严格名称匹配（防止幻觉）
- "skill"和"script"字段必须从上方可用函数中精确复制
- 不要自行添加 `_control` 等后缀
- 不要添加不存在的函数参数
"""
    
    return f"""你是 Tesla 车载系统函数选择模块。

## 用户指令
"{query}"
{state_text}{media_hint}
## 可用函数及完整参数定义
每个函数列出了所有可用参数及其默认值。必须返回所有参数的值：

{complete_function_defs}

## 任务
从上述函数中选择最合适的函数，返回所有参数（不仅仅是修改的参数）。

## 重要规则（State-Aware 完整参数）

### 1. 必须返回所有参数（强制）
必须按以下格式返回函数的所有参数：
```json
{{
    "skill": "skill_name",
    "script": "function_name",
    "parameters": {{
        "param1": "当前状态值或LLM计算的新值",
        "param2": "当前状态值或LLM计算的新值",
        "param3": "当前状态值或LLM计算的新值"
    }},
    "reason": "简要说明：1) 为什么选择此函数；2) 各参数值如何确定"
}}
```
如果没有匹配的函数，返回: `{{"skill": null, "reason": "不支持的函数"}}`

### 2. 必须计算相对值
- 如果用户说"调高一点"、"温度降2度"，要根据当前状态计算绝对值
- 示例：当前温度24度，用户说"降2度" -> "value": 22

### 3. 未更改参数使用当前状态值
- 对于用户未提及的参数，使用"当前车辆状态"中的值
- 如果当前状态中没有，使用函数定义中的默认值

### 4. 开关状态判断
- 如果用户说"打开"但已经是开，可以返回当前值或微调
- 如果用户说"关闭"但已经是关，保持关闭状态{location_rules}
"""


def merge_parameters_with_state(skill_name: str, function_name: str, llm_params: Dict[str, Any]) -> Dict[str, Any]:
    """将LLM返回的参数与当前状态值合并"""
    from context.skills import get_function_full_schema
    
    schema = get_function_full_schema(skill_name, function_name)
    if not schema:
        print(f"[参数合并警告] 无法获取 {skill_name}.{function_name} 的签名，直接返回LLM参数")
        return llm_params
    
    state = load_state()
    current_values = {}
    
    # 特殊处理 seat 技能（五个独立座位，V4支持多区域同步）
    if skill_name == "seat" and function_name in ["seat_heat", "seat_ventilation", "seat_massage"]:
        # 优先使用 positions 数组（V4多区域同步），兼容 position 单值（旧版）
        positions = llm_params.get("positions")
        if positions and isinstance(positions, list) and len(positions) > 0:
            position = positions[0]  # 使用第一个位置获取默认值
        else:
            position = llm_params.get("position", "front_left")
        
        if skill_name in state and function_name in state[skill_name]:
            seat_states = state[skill_name][function_name]
            if position in seat_states:
                current_values = seat_states[position]
                print(f"[参数合并] seat {function_name} [{position}] 当前状态: {current_values}")
            else:
                if function_name == "seat_massage":
                    current_values = {"level": 0, "mode": "normal", "enable": False}
                else:
                    current_values = {"level": 0, "enable": False}
                print(f"[参数合并] seat {function_name} [{position}] 未初始化，使用默认值")
        
        # 修复：确保 enable 和 level 一致（防止 level=0 但 enable=true 的矛盾）
        llm_enable = llm_params.get("enable")
        llm_level = llm_params.get("level")
        
        if llm_enable is True:
            # 要开启，但 level=0 或未指定，设置默认档位
            if llm_level == 0 or llm_level is None:
                llm_params["level"] = 2  # 默认2档
                print(f"[参数合并] 开启指令但档位为0，自动设置为默认档位2")
        elif llm_enable is False:
            # 要关闭，确保 level=0
            if llm_level != 0:
                llm_params["level"] = 0
                print(f"[参数合并] 关闭指令，档位自动设为0")
    
    # 特殊处理 air_conditioner 技能（V5：统一control函数）
    elif skill_name == "air_conditioner" and function_name in ["control", "set_temperature", "adjust_fan"]:
        # 处理 zones 参数（支持列表和单个字符串）
        zones = llm_params.get("zones")
        if zones is None:
            zone = llm_params.get("zone", "front_left")
            zones = [zone] if zone else ["front_left"]
        elif isinstance(zones, str):
            zones = [zones]
        
        # 获取第一个zone的状态用于默认值
        first_zone = zones[0] if zones else "front_left"
        
        if skill_name in state:
            ac_state = state[skill_name]
            
            if function_name == "control":
                # control: {zone: boolean}，获取指定zone的状态
                control_states = ac_state.get("control", {})
                if first_zone in control_states:
                    current_values = {"enable": control_states[first_zone]}
                    print(f"[参数合并] air_conditioner {function_name} zone={first_zone} 当前状态: {current_values}")
                else:
                    current_values = {"enable": False}
                    print(f"[参数合并] air_conditioner {function_name} 未初始化，使用默认值")
                    
            elif function_name == "set_temperature":
                temp_states = ac_state.get("set_temperature", {})
                if first_zone in temp_states:
                    current_values = temp_states[first_zone]
                    print(f"[参数合并] air_conditioner {function_name} zone={first_zone} 当前状态: {current_values}")
                else:
                    current_values = {"value": 22.0, "unit": "celsius"}
                    print(f"[参数合并] air_conditioner {function_name} 未初始化，使用默认值")
                    
            elif function_name == "adjust_fan":
                fan_states = ac_state.get("adjust_fan", {})
                if first_zone in fan_states:
                    current_values = fan_states[first_zone]
                    print(f"[参数合并] air_conditioner {function_name} zone={first_zone} 当前状态: {current_values}")
                else:
                    current_values = {"level": 2}
                    print(f"[参数合并] air_conditioner {function_name} 未初始化，使用默认值")
        else:
            # 默认初始值
            if function_name == "control":
                current_values = {"enable": False}
            elif function_name == "set_temperature":
                current_values = {"value": 22.0, "unit": "celsius"}
            else:  # adjust_fan
                current_values = {"level": 2}
            print(f"[参数合并] air_conditioner {function_name} 状态不存在，使用默认值")
    
    # 特殊处理 hardware 技能（车窗/车门，V4支持多位置同步）
    elif skill_name == "hardware" and function_name in ["control_window", "door_lock"]:
        # 处理 positions 列表参数（多位置同步）
        # 注意：车窗/车门默认是驾驶位（与空调不同！）
        positions = llm_params.get("positions")
        if positions and isinstance(positions, list) and len(positions) > 0:
            position = positions[0]
        else:
            position = llm_params.get("position", "front_left")  # 默认驾驶位
        
        if skill_name in state and function_name in state[skill_name]:
            pos_states = state[skill_name][function_name]
            if position in pos_states:
                current_values = pos_states[position]
                print(f"[参数合并] hardware {function_name} [{position}] 当前状态: {current_values}")
            else:
                if function_name == "control_window":
                    current_values = {"percent": 0}
                else:  # door_lock
                    current_values = {"action": "lock"}
                print(f"[参数合并] hardware {function_name} [{position}] 未初始化，使用默认值")
    
    elif skill_name in state and function_name in state[skill_name]:
        current_values = state[skill_name][function_name]
        print(f"[参数合并] 当前状态值: {current_values}")
    
    complete_params = {}
    
    # 首先保留LLM返回的所有参数（特别是zones这种不在schema中的参数）
    for param_name, param_value in llm_params.items():
        complete_params[param_name] = param_value
        print(f"[参数合并] {param_name}: 使用LLM值 = {param_value}")
    
    # 然后从schema中补充缺失的参数
    for param_def in schema["params"]:
        param_name = param_def["name"]
        default_value = param_def["default"]
        
        # 跳过已存在的参数
        if param_name in complete_params:
            continue
        
        if param_name in current_values:
            complete_params[param_name] = current_values[param_name]
            print(f"[参数合并] {param_name}: 使用当前状态值 = {current_values[param_name]}")
        elif default_value is not None:
            complete_params[param_name] = default_value
            print(f"[参数合并] {param_name}: 使用默认值 = {default_value}")
        else:
            print(f"[参数合并警告] {param_name}: 无可用值")
    
    # 最后检查：确保 enable 和 level 一致（针对 seat 技能）
    if skill_name == "seat" and function_name in ["seat_heat", "seat_ventilation", "seat_massage"]:
        final_enable = complete_params.get("enable")
        final_level = complete_params.get("level")
        
        if final_enable is True and final_level == 0:
            complete_params["level"] = 2
            print(f"[参数合并] 最终修复: enable=true 但 level=0，自动设置 level=2")
        elif final_enable is False and final_level != 0:
            complete_params["level"] = 0
            print(f"[参数合并] 最终修复: enable=false 但 level!=0，自动设置 level=0")
    
    print(f"[参数合并] 合并后完整参数: {complete_params}")
    return complete_params


def select_function(query: str, skill_names: List[str], llm_client) -> Optional[FunctionCall]:
    """State-Aware函数选择，带完整参数合并"""
    current_state = get_relevant_state(skill_names)
    if current_state:
        print(f"[State-Aware函数选择] 当前状态: {json.dumps(current_state, ensure_ascii=False)}")
    
    prompt = build_function_selection_prompt(skill_names, query, current_state)
    print(f"[函数选择] 提示词长度: {len(prompt)} 字符")
    
    try:
        response = llm_client.chat(system=prompt, user="请分析用户指令并返回函数调用（必须包含所有参数）", stream=False)
        print(f"[函数选择] LLM原始响应:\n{response[:800]}...")
        
        result = extract_json(response)
        print(f"[函数选择] 解析结果: {result}")
        
        skill = result.get("skill")
        script = result.get("script")
        llm_parameters = result.get("parameters", {})
        reason = result.get("reason", "")
        
        print(f"[函数选择] LLM返回参数: {llm_parameters}")
        
        if not skill or not script:
            print(f"[函数选择] 失败: skill或script为空")
            return None
        
        complete_parameters = merge_parameters_with_state(skill, script, llm_parameters)
        print(f"[函数选择] 最终完整参数: {complete_parameters}")
        
        return FunctionCall(skill=skill, script=script, parameters=complete_parameters, reason=reason)
    except Exception as e:
        print(f"[函数选择] 失败: {e}")
        import traceback
        traceback.print_exc()
        return None


def build_multi_function_selection_prompt(skill_names: List[str], query: str, current_state: Dict[str, Any] = None) -> str:
    """构建State-Aware多函数选择提示词，带完整参数定义"""
    complete_function_defs = build_complete_function_prompt(skill_names)
    
    state_text = ""
    if current_state:
        state_json = json.dumps(current_state, ensure_ascii=False, indent=2)
        state_text = f"""
## 当前车辆状态（执行前）
以下是与选中技能相关的当前车辆状态数据：
```json
{state_json}
```
"""
    
    media_hint = ""
    if "media" in skill_names:
        media_hint = """
## 【重要】媒体技能选择规则
调用 `media.music_control` 播放本地音乐时：
1. 必须从 media 技能文档中定义的20首本地音乐库中选择
2. 必须提供全部三个参数：artist, title, album
3. 如果用户只说"播放周杰伦"，则选择该艺术家的第一首歌
4. 如果指定歌曲不在20首库中，返回错误

调用 `media.radio_control` 播放电台时：
1. 必须从 media 技能文档中定义的10个预设电台中选择
2. 必须提供：band, frequency, station_name
"""
    
    return f"""你是 Tesla 车载系统多任务处理模块。

## 用户指令（可能包含多个操作）
"{query}"
{state_text}{media_hint}
## 可用函数及完整参数定义
每个函数列出了所有可用参数及其默认值。每个任务必须返回该函数的所有参数值：

{complete_function_defs}

## 任务
分析用户指令，识别所有独立的操作任务（最多3个），为每个任务选择最合适的函数。

## 重要规则（State-Aware 完整参数）

### 1. 每个任务必须返回所有参数（强制）
每个任务的参数必须包含该函数的所有参数：
```json
{{
    "tasks": [
        {{
            "task_id": 1,
            "skill": "skill_name",
            "script": "function_name",
            "parameters": {{
                "param1": "当前状态值或LLM计算的新值",
                "param2": "当前状态值或LLM计算的新值",
                "param3": "当前状态值或LLM计算的新值"
            }}
        }}
    ]
}}
```

### 2. 必须计算相对值
- 如果用户说"调高一点"、"温度降2度"，要根据当前状态计算绝对值

### 3. 未更改参数使用当前状态值
- 对于用户未提及的参数，使用"当前车辆状态"中的值
- 如果当前状态中没有，使用函数定义中的默认值

### 4. 区域识别（重要）
- 用户说"副驾"、"后排"，要正确识别 zones/position 参数
- **zones 参数必须是列表格式**，例如：`["front_left"]` 或 `["rear_left", "rear_middle", "rear_right"]`

### 5. 空调控制逻辑（V5版本，重要！）
- **control 函数是统一开关**：`control(enable=true/false, zones=[...])`
- "打开空调"（未指定区域）-> `control(enable=true)` - 打开全部5个位置
- "关闭空调"（未指定区域）-> `control(enable=false)` - 关闭所有已打开的位置
- "打开后排空调" -> `control(enable=true, zones=["rear_left","rear_middle","rear_right"])`
- "关闭副驾空调" -> `control(enable=false, zones=["front_right"])`
- 调温度/风量时如果区域未开启，会自动开启该区域

### 6. 座椅控制逻辑（V4版本，重要！）
- **seat_heat/seat_ventilation/seat_massage 支持多区域同步**
- 使用 `positions` 数组传递多个位置：`["rear_left", "rear_middle", "rear_right"]`
- "打开后排所有座椅加热" -> `seat_heat(positions=["rear_left","rear_middle","rear_right"], level=2, enable=true)`
- "全车座椅加热打开" -> `seat_heat(positions=[...全部五个位置...], level=2, enable=true)`
- 单个位置也要用数组：`["front_left"]`
- 未指定位置时默认 `front_left`（驾驶位）

### 7. 硬件控制逻辑（hardware skill，重要！）
- **control_window 支持多位置同步**（V4版本）
- 使用 `positions` 数组传递多个位置
- "关闭所有车窗" -> `control_window(positions=[...四个位置...], percent=0)`
- "打开前排车窗" -> `control_window(positions=["front_left","front_right"], percent=50)`
- **默认行为：未指定位置时默认 `front_left`（主驾），不是全车！**（与空调不同）
- "打开车窗" -> `control_window(positions=["front_left"], percent=50)`
- **door_lock 也支持多位置同步**
- "全车解锁" -> `door_lock(positions=[...四个位置...], action="unlock")`
- **默认行为：未指定位置时默认 `front_left`（主驾）**

### 8. 任务拆分规则（重要）
- **同一个功能的不同位置 = 一个任务**：用 zones 列表传多个位置
- **不同功能类型 = 多个任务**：如空调+音乐+导航
- 错误示例：把"全车空调打开"拆成3个任务 → 正确：1个任务，zones包含所有位置

## 返回格式（严格JSON）
{{
    "tasks": [
        {{
            "task_id": 1,
            "skill": "skill_name",
            "script": "function_name",
            "parameters": {{
                "param_name1": "value1 (当前状态或LLM计算)",
                "param_name2": "value2 (当前状态或LLM计算)"
            }},
            "description": "简要说明：1) 为什么选择此函数；2) 参数值如何确定"
        }}
    ],
    "reason": "简要说明为什么这样分解任务"
}}

如果没有匹配的函数，返回: `{{"tasks": [], "reason": "不支持这些函数"}}`"""


def select_multiple_functions(query: str, skill_names: List[str], llm_client) -> List[FunctionCall]:
    """State-Aware多函数选择，带完整参数合并"""
    current_state = get_relevant_state(skill_names)
    if current_state:
        print(f"[多任务State-Aware] 当前状态: {json.dumps(current_state, ensure_ascii=False)}")
    
    prompt = build_multi_function_selection_prompt(skill_names, query, current_state)
    
    try:
        response = llm_client.chat(system=prompt, user="请分析用户指令并返回多个函数调用（每个任务必须包含所有参数）", stream=False)
        result = extract_json(response)
        tasks = result.get("tasks", [])
        
        calls = []
        for task in tasks:
            skill = task.get("skill")
            script = task.get("script")
            llm_parameters = task.get("parameters", {})
            description = task.get("description", "")
            
            if skill and script:
                print(f"[多函数选择] 任务 {skill}.{script} LLM参数: {llm_parameters}")
                complete_parameters = merge_parameters_with_state(skill, script, llm_parameters)
                print(f"[多函数选择] 任务 {skill}.{script} 完整参数: {complete_parameters}")
                
                calls.append(FunctionCall(
                    skill=skill,
                    script=script,
                    parameters=complete_parameters,
                    reason=description
                ))
        
        return calls[:3]
    except Exception as e:
        print(f"[多函数选择] 失败: {e}")
        import traceback
        traceback.print_exc()
        return []
