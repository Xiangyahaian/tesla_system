# -*- coding: utf-8 -*-
"""
Skills 工具函数
"""


def format_success_message(action: str, detail: str = "") -> str:
    """格式化成功消息"""
    if detail:
        return f"{action} - {detail}"
    return action


def format_error_message(error: str) -> str:
    """格式化错误消息"""
    return f"执行失败: {error}"


def get_position_name(position: str, default: str = "") -> str:
    """获取位置的中文名称"""
    names = {
        "driver": "驾驶位",
        "passenger": "副驾",
        "rear": "后排",
        "rear_left": "后排左",
        "rear_right": "后排右",
        "front": "前排",
        "front_left": "左前",
        "front_right": "右前",
        "all": "全车",
        "sunroof": "天窗",
        "sunshade": "遮阳帘"
    }
    return names.get(position, default or position)


def percent_to_desc(percent: int) -> str:
    """百分比转为描述"""
    if percent == 0:
        return "已关闭"
    elif percent == 100:
        return "已完全打开"
    elif percent <= 20:
        return "微开"
    elif percent <= 50:
        return "半开"
    elif percent <= 80:
        return "大半开"
    else:
        return "接近全开"
