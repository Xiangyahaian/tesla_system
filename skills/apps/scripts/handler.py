# -*- coding: utf-8 -*-
"""
Apps Skill Handler - 第三方应用管理

提供功能：
- launch_app: 启动/关闭应用，并持久化状态到 state.json
"""

from typing import Dict, Any
import json


# 已安装应用白名单（支持别名映射）
INSTALLED_APPS = {
    # 应用名: [别名列表]
    "网易云音乐": ["网易云"],
    "QQ": ["qq"],
    "微信": ["wechat"],
    "拼多多": ["pdd", "拼夕夕"],
    "高德地图": ["高德"],
    "腾讯地图": [],
    "爱奇艺视频": ["爱奇艺"],
    "邮箱": ["邮件", "email"],
    "腾讯视频": [],
    "飞书": ["lark"],
    "支付宝": [],
    "美团": [],
    "携程": [],
    "淘宝": ["taobao"],
    "腾讯会议": ["会议"],
    "钉钉": ["dingtalk"],
}


def _normalize_app_name(app_name: str) -> str:
    """将输入的应用名称规范化到标准名称"""
    app_lower = app_name.lower()
    
    # 直接匹配
    for standard_name, aliases in INSTALLED_APPS.items():
        if app_lower == standard_name.lower():
            return standard_name
        # 检查别名
        for alias in aliases:
            if app_lower == alias.lower():
                return standard_name
    
    # 如果没有匹配，返回原值（后续会检查是否在白名单中）
    return app_name


def _is_app_installed(app_name: str) -> bool:
    """检查应用是否在已安装列表中"""
    app_lower = app_name.lower()
    
    for standard_name, aliases in INSTALLED_APPS.items():
        if app_lower == standard_name.lower():
            return True
        for alias in aliases:
            if app_lower == alias.lower():
                return True
    
    return False


def launch_app(
    state_file: str,
    app_name: str = "",
    action: str = "open"
) -> Dict[str, Any]:
    """应用调度 - 打开或关闭指定应用
    
    Args:
        state_file: 状态文件路径
        app_name: 应用名称
        action: 动作 - "open"(打开) 或 "close"(关闭)
    
    Returns:
        如果应用不在白名单中，返回"没有安装这个软件"
    """
    
    # 检查应用是否在已安装列表中
    if not _is_app_installed(app_name):
        return {
            "success": False,
            "message": f"没有安装「{app_name}」这个软件",
            "data": {
                "app_name": app_name,
                "action": action,
                "installed": False
            }
        }
    
    # 规范化应用名称
    app_normalized = _normalize_app_name(app_name)
    
    # 加载当前状态
    try:
        with open(state_file, 'r', encoding='utf-8') as f:
            state = json.load(f)
    except:
        state = {"apps": {}}
    
    # 执行操作
    if action == "open":
        msg = f"正在打开「{app_normalized}」"
        # 更新状态：当前打开的应用
        if "apps" not in state:
            state["apps"] = {}
        state["apps"]["current_app"] = {
            "name": app_normalized,
            "active": True
        }
    elif action == "close":
        msg = f"正在关闭「{app_normalized}」"
        # 更新状态：清除当前应用
        if "apps" in state and "current_app" in state["apps"]:
            if state["apps"]["current_app"].get("name") == app_normalized:
                state["apps"]["current_app"] = {"name": None, "active": False}
    else:
        msg = f"应用「{app_normalized}」操作完成"
    
    # 保存状态
    try:
        with open(state_file, 'w', encoding='utf-8') as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[Apps] 保存状态失败: {e}")
    
    return {
        "success": True,
        "message": msg,
        "data": {
            "app_name": app_normalized,
            "action": action
        }
    }


def execute(script: str, params: Dict[str, Any], state_file: str) -> Dict[str, Any]:
    """统一执行入口 - V3 标准接口
    
    Args:
        script: 要执行的函数名
        params: 函数参数
        state_file: 状态文件路径
    """
    scripts = {
        "launch_app": launch_app,
    }
    
    handler = scripts.get(script)
    if not handler:
        return {
            "success": False,
            "message": f"Apps Skill 不支持 script: {script}",
            "data": None
        }
    
    try:
        # 传入 state_file 作为第一个参数
        return handler(state_file, **params)
    except Exception as e:
        return {
            "success": False,
            "message": f"执行失败: {str(e)}",
            "data": None
        }


if __name__ == "__main__":
    print("=" * 60)
    print("Apps Handler 测试")
    print("=" * 60)
    
    test_state_file = "../../../state/state.json"
    
    tests = [
        {"script": "launch_app", "params": {"app_name": "拼多多", "action": "open"}},
        {"script": "launch_app", "params": {"app_name": "淘宝", "action": "close"}},
        {"script": "launch_app", "params": {"app_name": "微信"}},
        {"script": "launch_app", "params": {"app_name": "网易云", "action": "open"}},
        {"script": "launch_app", "params": {"app_name": "抖音", "action": "open"}},  # 未安装
        {"script": "launch_app", "params": {"app_name": "王者荣耀", "action": "open"}},  # 未安装
    ]
    
    for t in tests:
        print(f"\n{t['script']}({t['params']})")
        r = execute(t["script"], t["params"], test_state_file)
        print(f"  → {r['message']}")
