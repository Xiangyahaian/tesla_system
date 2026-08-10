# -*- coding: utf-8 -*-
"""模拟车机应用商店 / App API 目录。

演示用：假定这些 App 已安装，可通过 apps.launch 打开/关闭。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


# name: 标准显示名；aliases: 口语/英文别名；category: 分类
INSTALLED_APPS: List[Dict[str, Any]] = [
    # —— 系统 / 车机 ——
    {"name": "地图", "aliases": ["车载地图", "导航app"], "category": "system"},
    {"name": "音乐", "aliases": ["车载音乐"], "category": "system"},
    {"name": "电台", "aliases": ["广播", "radio"], "category": "system"},
    {"name": "电话", "aliases": ["通话", "phone"], "category": "system"},
    {"name": "邮箱", "aliases": ["邮件", "email", "mail"], "category": "system"},
    {"name": "浏览器", "aliases": ["browser"], "category": "system"},
    {"name": "摄像头", "aliases": ["行车记录仪", "camera"], "category": "system"},
    {"name": "充电", "aliases": ["充电管理"], "category": "system"},
    {"name": "设置", "aliases": ["系统设置", "settings"], "category": "system"},
    # —— 社交 / 办公 ——
    {"name": "飞书", "aliases": ["lark", "Lark"], "category": "office"},
    {"name": "钉钉", "aliases": ["dingtalk", "DingTalk"], "category": "office"},
    {"name": "微信", "aliases": ["wechat", "WeChat"], "category": "social"},
    {"name": "QQ", "aliases": ["qq"], "category": "social"},
    {"name": "腾讯会议", "aliases": ["会议", "tencent meeting"], "category": "office"},
    # —— 出行 / 生活 ——
    {"name": "高德地图", "aliases": ["高德", "amap"], "category": "travel"},
    {"name": "腾讯地图", "aliases": [], "category": "travel"},
    {"name": "百度", "aliases": ["百度一下", "baidu"], "category": "travel"},
    {"name": "美团", "aliases": ["meituan"], "category": "life"},
    {"name": "携程", "aliases": ["ctrip"], "category": "travel"},
    {"name": "支付宝", "aliases": ["alipay"], "category": "finance"},
    {"name": "淘宝", "aliases": ["taobao"], "category": "shopping"},
    {"name": "拼多多", "aliases": ["pdd", "拼夕夕"], "category": "shopping"},
    # —— 影音 ——
    {"name": "网易云音乐", "aliases": ["网易云", "云音乐"], "category": "media"},
    {"name": "QQ音乐", "aliases": ["qq音乐"], "category": "media"},
    {"name": "爱奇艺视频", "aliases": ["爱奇艺"], "category": "media"},
    {"name": "腾讯视频", "aliases": [], "category": "media"},
]


def _alias_index() -> Dict[str, str]:
    idx: Dict[str, str] = {}
    for app in INSTALLED_APPS:
        name = app["name"]
        idx[name.lower()] = name
        for a in app.get("aliases") or []:
            idx[str(a).lower()] = name
    return idx


_ALIAS_TO_NAME = _alias_index()
ALLOWED_APP_NAMES = {app["name"] for app in INSTALLED_APPS}


def normalize_app_name(name: str) -> str:
    raw = (name or "").strip()
    if not raw:
        return raw
    if raw in ALLOWED_APP_NAMES:
        return raw
    return _ALIAS_TO_NAME.get(raw.lower(), raw)


def is_installed(name: str) -> bool:
    return normalize_app_name(name) in ALLOWED_APP_NAMES


def list_apps(category: Optional[str] = None) -> List[Dict[str, Any]]:
    apps = INSTALLED_APPS
    if category:
        apps = [a for a in apps if a.get("category") == category]
    return [
        {
            "name": a["name"],
            "aliases": list(a.get("aliases") or []),
            "category": a.get("category", "other"),
            "installed": True,
        }
        for a in apps
    ]


def catalog_for_prompt(max_names: int = 40) -> str:
    """给 NLU / Tool 描述用的短目录。"""
    names = [a["name"] for a in INSTALLED_APPS][:max_names]
    return "已安装应用（模拟）: " + "、".join(names)


def resolve_or_suggest(name: str) -> Dict[str, Any]:
    """打开失败时返回建议。"""
    std = normalize_app_name(name)
    if std in ALLOWED_APP_NAMES:
        return {"ok": True, "app_name": std}
    sample = "、".join(a["name"] for a in INSTALLED_APPS[:10])
    return {
        "ok": False,
        "app_name": std or name,
        "message": f"未安装应用「{name}」。可用例如：{sample}…（共{len(INSTALLED_APPS)}个）",
        "available": [a["name"] for a in INSTALLED_APPS],
    }
