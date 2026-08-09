# -*- coding: utf-8 -*-
"""
文本处理和JSON提取工具函数
"""
import re
import json


def clean_query(text: str) -> str:
    """清理输入文本中的异常字符"""
    if not text:
        return ""
    text = text.strip()
    text = "".join(ch for ch in text if ord(ch) >= 32 or ch == '\n')
    pattern = re.compile(r'[^\u4e00-\u9fa5a-zA-Z0-9\s,.，。？！?！:：\-—_]')
    return pattern.sub('', text)[:512]


def extract_json(text: str) -> dict:
    """从文本中提取JSON"""
    text = text.strip()
    try:
        return json.loads(text)
    except:
        pass
    
    json_pattern = r'```(?:json)?\s*(\{.*?\})\s*```'
    matches = re.findall(json_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except:
            pass
    
    brace_pattern = r'(\{[^{}]*(?:\{[^{}]*\}[^{}]*)*\})'
    matches = re.findall(brace_pattern, text, re.DOTALL)
    for match in matches:
        try:
            return json.loads(match)
        except:
            pass
    
    raise json.JSONDecodeError("无法解析JSON", text, 0)


def format_params(params: dict) -> str:
    """将参数字典格式化为字符串"""
    parts = []
    for k, v in params.items():
        if isinstance(v, str):
            parts.append(f'{k}="{v}"')
        else:
            parts.append(f'{k}={v}')
    return ", ".join(parts)
