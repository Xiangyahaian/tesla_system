# -*- coding: utf-8 -*-
"""
Agent Skill Handler - 语音助手本身与情景模式域

提供功能：
- set_persona: 人设与声音设置
- set_speech: 语速与播报设置
- switch_scene: 情景模式切换
"""

from typing import Dict, Any


def set_persona(
    voice: str = "",
    tone: str = "",
    name: str = ""
) -> Dict[str, Any]:
    """人设与声音设置"""
    
    voice_names = {
        "folk": "民谣风格",
        "gentle_female": "温柔女声",
        "deep_male": "沉稳男声",
        "robotic": "机械音",
        "cute": "可爱声音"
    }
    voice_name = voice_names.get(voice, voice)
    
    tone_names = {
        "friendly": "亲切",
        "professional": "专业",
        "humorous": "幽默"
    }
    tone_name = tone_names.get(tone, tone)
    
    parts = []
    if voice_name:
        parts.append(f"音色：{voice_name}")
    if tone_name:
        parts.append(f"语气：{tone_name}")
    if name:
        if name == "?":
            parts.append("如需改名，请说'以后叫你XX'")
        else:
            parts.append(f"名称：{name}")
    
    if parts:
        msg = "语音助手人设已更新 - " + "，".join(parts)
    else:
        msg = "语音助手人设设置"
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "voice": voice,
            "tone": tone,
            "name": name
        }
    }


def set_speech(
    speed: str = "normal",
    mode: str = "normal",
    volume: int = None
) -> Dict[str, Any]:
    """语速与播报设置"""
    
    speed_names = {
        "slow": "较慢",
        "normal": "正常",
        "fast": "较快"
    }
    speed_name = speed_names.get(speed, speed)
    
    mode_names = {
        "brief": "简洁播报",
        "normal": "标准播报",
        "detailed": "详细播报",
        "silent": "静音模式"
    }
    mode_name = mode_names.get(mode, mode)
    
    parts = [f"语速：{speed_name}", f"模式：{mode_name}"]
    if volume is not None:
        parts.append(f"音量：{volume}")
    
    msg = "播报设置已更新 - " + "，".join(parts)
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "speed": speed,
            "mode": mode,
            "volume": volume
        }
    }


def switch_scene(
    scene: str = "",
    enable: bool = True
) -> Dict[str, Any]:
    """情景模式切换"""
    
    scene_names = {
        "romantic": "甜蜜时光",
        "sleep": "睡眠模式",
        "sport": "运动模式",
        "baby": "宝宝模式",
        "meeting": "会议模式",
        "drive": "驾驶模式"
    }
    scene_name = scene_names.get(scene, scene)
    
    # 场景描述
    scene_desc = {
        "romantic": "氛围灯柔和，音乐轻缓",
        "sleep": "空调静音，座椅放倒，灯光关闭",
        "sport": "氛围灯激情，音乐动感，空调加强",
        "baby": "空调柔和，音量降低，车窗锁定",
        "meeting": "静音模式，氛围灯关闭，座椅舒适"
    }
    
    if enable:
        msg = f"已切换至{scene_name}"
        if scene in scene_desc:
            msg += f" - {scene_desc[scene]}"
    else:
        msg = f"已退出{scene_name}"
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "scene": scene,
            "enable": enable,
            "actions": []  # 实际应触发的动作列表
        }
    }


def execute(script: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """统一执行入口"""
    params = {k: v for k, v in params.items() if k != "action"}
    
    scripts = {
        "set_persona": set_persona,
        "set_speech": set_speech,
        "switch_scene": switch_scene,
    }
    
    handler = scripts.get(script)
    if not handler:
        return {
            "success": False,
            "message": f"Agent Skill 不支持 script: {script}",
            "data": None
        }
    
    try:
        return handler(**params)
    except Exception as e:
        return {
            "success": False,
            "message": f"执行失败: {str(e)}",
            "data": None
        }


if __name__ == "__main__":
    print("=" * 60)
    print("Agent Handler 测试")
    print("=" * 60)
    
    tests = [
        {"script": "set_persona", "params": {"voice": "folk"}},
        {"script": "set_speech", "params": {"speed": "slow"}},
        {"script": "set_speech", "params": {"mode": "brief"}},
        {"script": "switch_scene", "params": {"scene": "romantic", "enable": False}},
        {"script": "switch_scene", "params": {"scene": "sleep"}},
    ]
    
    for t in tests:
        print(f"\n{t['script']}({t['params']})")
        r = execute(t["script"], t["params"])
        print(f"  → {r['message']}")
