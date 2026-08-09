# -*- coding: utf-8 -*-
"""
技能元数据加载、路由和函数签名提取
"""
import ast
import json
import importlib.util
from pathlib import Path
from typing import Dict, Any, List, Optional, Tuple
from config.settings import SKILLS_DIR, STATE_FILE
from context.models import SkillMeta


def parse_yaml_frontmatter(content: str) -> Tuple[Dict, str]:
    """解析YAML前置元数据，返回(frontmatter字典, 正文内容)"""
    if not content.startswith('---'):
        return {}, content
    
    parts = content.split('---', 2)
    if len(parts) < 3:
        return {}, content
    
    yaml_content = parts[1].strip()
    body = parts[2].strip()
    
    result = {}
    current_key = None
    current_list = None
    lines = yaml_content.split('\n')
    
    i = 0
    while i < len(lines):
        line = lines[i].rstrip()
        if not line or line.startswith('#'):
            i += 1
            continue
        
        if line.strip().startswith('- ') and current_key:
            if current_list is None:
                current_list = []
            item_text = line.strip()[2:].strip()
            if ':' in item_text:
                key, value = item_text.split(':', 1)
                if current_list and isinstance(current_list[-1], dict):
                    current_list[-1][key.strip()] = value.strip()
                else:
                    current_list.append({key.strip(): value.strip()})
            i += 1
            continue
        
        if ':' in line and not line.startswith(' '):
            if current_key and current_list is not None:
                result[current_key] = current_list
                current_list = None
            
            key, value = line.split(':', 1)
            key = key.strip()
            value = value.strip()
            
            if value:
                result[key] = value
            else:
                current_key = key
        
        i += 1
    
    if current_key and current_list is not None:
        result[current_key] = current_list
    
    return result, body


def load_skill_meta(skill_dir: Path) -> Optional[SkillMeta]:
    """加载轻量级技能元数据"""
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return None
    
    try:
        content = skill_md.read_text(encoding='utf-8')
        frontmatter, body = parse_yaml_frontmatter(content)
        
        name = frontmatter.get('name', skill_dir.name)
        description = frontmatter.get('description', '')
        
        functions = []
        metadata = frontmatter.get('metadata', {})
        if isinstance(metadata, dict):
            funcs = metadata.get('functions', [])
            for func in funcs:
                if isinstance(func, dict):
                    functions.append({
                        "name": func.get('name', ''),
                        "description": func.get('description', '')
                    })
        
        return SkillMeta(name=name, description=description, functions=functions)
    except Exception as e:
        print(f"[技能加载] 加载 {skill_dir.name} 失败: {e}")
        return None


def load_all_skill_metas() -> List[SkillMeta]:
    """加载所有技能的元数据"""
    metas = []
    for skill_dir in SKILLS_DIR.iterdir():
        if skill_dir.is_dir():
            meta = load_skill_meta(skill_dir)
            if meta:
                metas.append(meta)
    return metas


def load_skill_detail(skill_name: str) -> str:
    """加载技能完整详情（函数参数）"""
    skill_md = SKILLS_DIR / skill_name / "SKILL.md"
    if not skill_md.exists():
        return ""
    
    try:
        content = skill_md.read_text(encoding='utf-8')
        _, body = parse_yaml_frontmatter(content)
        return body
    except Exception as e:
        print(f"[技能详情] 加载 {skill_name} 详情失败: {e}")
        return ""


def get_skill_handler(skill_name: str):
    """获取技能处理器模块（返回封装后的execute函数）"""
    try:
        handler_path = SKILLS_DIR / skill_name / "scripts" / "handler.py"
        if not handler_path.exists():
            return None
        
        spec = importlib.util.spec_from_file_location(f"skill_{skill_name}", handler_path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        
        if hasattr(module, 'execute'):
            original_execute = module.execute
            
            def wrapped_execute(script: str, parameters: Dict[str, Any]):
                return original_execute(script, parameters, str(STATE_FILE))
            
            return wrapped_execute
        return None
    except Exception as e:
        print(f"[处理器] 加载 {skill_name} 处理器失败: {e}")
        return None


def extract_function_signatures(skill_name: str) -> Dict[str, Dict[str, Any]]:
    """从handler.py提取完整的函数签名信息"""
    try:
        handler_path = SKILLS_DIR / skill_name / "scripts" / "handler.py"
        if not handler_path.exists():
            return {}
        
        content = handler_path.read_text(encoding='utf-8')
        tree = ast.parse(content)
        functions = {}
        
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_name = node.name
                if func_name.startswith('_') or func_name == 'execute':
                    continue
                
                params = []
                args = node.args.args
                defaults = node.args.defaults
                
                defaults_start = len(args) - len(defaults)
                
                for i, arg in enumerate(args):
                    param_name = arg.arg
                    if param_name == 'state_file':
                        continue
                    
                    default_value = None
                    if i >= defaults_start:
                        default_node = defaults[i - defaults_start]
                        try:
                            if isinstance(default_node, ast.Constant):
                                default_value = default_node.value
                            elif isinstance(default_node, ast.NameConstant):
                                default_value = default_node.value
                            elif isinstance(default_node, ast.Str):
                                default_value = default_node.s
                            elif isinstance(default_node, ast.Num):
                                default_value = default_node.n
                            elif isinstance(default_node, ast.List):
                                default_value = []
                            elif isinstance(default_node, ast.Dict):
                                default_value = {}
                        except:
                            default_value = None
                    
                    param_type = "any"
                    if arg.annotation:
                        if isinstance(arg.annotation, ast.Name):
                            param_type = arg.annotation.id
                        elif isinstance(arg.annotation, ast.Subscript):
                            param_type = "list/dict"
                    
                    params.append({
                        "name": param_name,
                        "default": default_value,
                        "type": param_type
                    })
                
                docstring = ast.get_docstring(node) or ""
                
                functions[func_name] = {
                    "params": params,
                    "docstring": docstring
                }
        
        return functions
    except Exception as e:
        print(f"[签名提取] 提取 {skill_name} 函数签名失败: {e}")
        return {}


def get_function_full_schema(skill_name: str, function_name: str) -> Optional[Dict[str, Any]]:
    """获取指定函数的完整参数结构"""
    signatures = extract_function_signatures(skill_name)
    return signatures.get(function_name)


def build_complete_function_prompt(skill_names: List[str]) -> str:
    """构建带完整参数定义的函数描述"""
    sections = []
    
    for skill_name in skill_names:
        signatures = extract_function_signatures(skill_name)
        if not signatures:
            continue
        
        skill_section = [f"## {skill_name} 技能"]
        
        for func_name, func_info in signatures.items():
            params_desc = []
            for param in func_info["params"]:
                default_str = f" (默认值: {param['default']})" if param['default'] is not None else ""
                params_desc.append(f"  - {param['name']}: {param['type']}{default_str}")
            
            doc = func_info["docstring"].strip() if func_info["docstring"] else ""
            doc_lines = doc.split('\n')[:2]
            doc_short = ' '.join(doc_lines).strip()
            
            func_desc = f"""### {func_name}
功能: {doc_short}
参数:
{chr(10).join(params_desc) if params_desc else '  (无参数)'}
"""
            skill_section.append(func_desc)
        
        sections.append('\n'.join(skill_section))
    
    return '\n\n'.join(sections)


def build_skill_routing_prompt(skill_metas: List[SkillMeta]) -> str:
    """构建轻量级技能路由提示词"""
    skill_list = []
    for meta in skill_metas:
        funcs = ", ".join([f["name"] for f in meta.functions])
        skill_list.append(f"- {meta.name}: {meta.description} (函数: {funcs})")
    
    skills_text = "\n".join(skill_list)
    
    return f"""你是 Tesla 车载系统技能路由模块。

根据用户指令选择最相关的技能。

## 可用技能
{skills_text}

## 重要路由规则
### 媒体相关 (media)
1. **音乐播放控制**（播放/暂停/停止、选歌）-> 使用 media.music_control
2. **音乐切换**（上一首/下一首）-> 使用 media.music_switch
3. **电台播放控制**（播放/暂停/停止、选台）-> 使用 media.radio_control
4. **电台切换**（上/下一个台）-> 使用 media.radio_switch
5. **音量控制**（升高/降低/静音）-> 使用 media.volume_control

### 硬件相关 (hardware)
6. **车窗控制**（升降/开合）-> 使用 hardware.control_window
7. **灯光控制**（大灯/雾灯/氛围灯）-> 使用 hardware.control_lighting
8. **后备箱/车门** -> 使用 hardware 技能

### 座椅舒适 (seat)
9. **座椅加热**（打开/关闭/调节档位）-> 使用 seat.seat_heat
10. **座椅通风**（打开/关闭/调节档位）-> 使用 seat.seat_ventilation
11. **座椅按摩**（打开/关闭/调节模式）-> 使用 seat.seat_massage
12. **方向盘加热**（打开/关闭/调节档位）-> 使用 seat.steering_wheel_heat

### 空调系统 (air_conditioner)
13. **空调开关**（打开/关闭空调）-> 使用 air_conditioner.power_control
14. **温度设置**（调温度/制冷/制热）-> 使用 air_conditioner.set_temperature
15. **风量调节**（风大/风小/风速）-> 使用 air_conditioner.adjust_fan
16. **空调模式**（内循环/外循环/除霜）-> 使用 air_conditioner.set_mode
17. **风向控制**（吹脸/吹脚/吹玻璃）-> 使用 air_conditioner.set_mode

### 导航 (navigation)
18. **导航/去某地/查路线** -> 使用 navigation 技能

### 应用 (apps)
19. **打开APP**（微信/地图/音乐等）-> 使用 apps 技能

### 整车控制 (vehicle)
20. **车辆状态/模式切换** -> 使用 vehicle 技能

### 智能体 (agent)
21. **复杂任务/需要多步执行** -> 使用 agent 技能

## 返回格式（严格JSON）
{{
    "skills": ["skill_name1", "skill_name2"],
    "reason": "简要说明选择原因"
}}

如果没有匹配的技能，返回: `{{"skills": [], "reason": "无匹配"}}`

**重要**：
- "打开方向盘加热" 必须选择 seat 技能
- "空调调到22度" 必须选择 air_conditioner 技能
- 可以同时选择多个相关技能"""


def route_skills(query: str, skill_metas: List[SkillMeta], llm_client) -> List[str]:
    """技能路由: 选择可能相关的技能"""
    from context.utils import extract_json
    prompt = build_skill_routing_prompt(skill_metas)
    try:
        response = llm_client.chat(system=prompt, user=f"用户指令: {query}", stream=False)
        result = extract_json(response)
        return result.get("skills", [])
    except Exception as e:
        print(f"[技能路由] 失败: {e}")
        return []
