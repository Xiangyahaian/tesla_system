# -*- coding: utf-8 -*-
"""
路径解析工具 - 以 run.py 为基准的相对路径处理

功能：将 MongoDB 中的绝对路径（如 /root/autodl-tmp/RAG/data/xxx）
      转换为本地相对路径（./data/xxx）

使用方式：
    from utils.path_resolver import convert_path, resolve_image_info
    
    # 转换单条路径
    local_path = convert_path("/root/autodl-tmp/RAG/data/saved_images/xxx.jpg")
    # 返回: ./data/saved_images/xxx.jpg
"""

import os
from pathlib import Path
from typing import Dict, List, Any


def _find_project_root() -> Path:
    """查找项目根目录（包含 run.py 的目录）"""
    # 从当前文件向上查找
    current = Path(__file__).resolve().parent  # utils/
    current = current.parent  # 项目根目录
    
    if (current / "run.py").exists():
        return current
    
    # 如果没有，从当前工作目录查找
    cwd = Path.cwd()
    for _ in range(5):
        if (cwd / "run.py").exists():
            return cwd
        parent = cwd.parent
        if parent == cwd:
            break
        cwd = parent
    
    # 默认返回 utils 的父目录
    return Path(__file__).resolve().parent.parent


def convert_path(db_path: str) -> str:
    """
    将 MongoDB 绝对路径转换为相对路径（别名函数）
    
    与 convert_db_path_to_local 功能相同，提供更简洁的调用方式
    """
    return convert_db_path_to_local(db_path)


def convert_db_path_to_local(db_path: str) -> str:
    """
    将 MongoDB 绝对路径转换为相对路径
    
    Args:
        db_path: MongoDB 中存储的路径，如 "/root/autodl-tmp/RAG/data/saved_images/xxx.jpg"
    
    Returns:
        相对路径，如 "./data/saved_images/xxx.jpg"
    """
    if not db_path:
        return ""
    
    path_str = str(db_path).replace("\\", "/")
    
    # 如果已经是相对路径，直接返回
    if not path_str.startswith("/") and not (len(path_str) > 1 and path_str[1] == ":"):
        return path_str if path_str.startswith("./") else f"./{path_str}"
    
    # 查找 "data/" 位置，提取后面的部分
    if "data/" in path_str:
        idx = path_str.find("data/")
        return "./" + path_str[idx:]
    
    # 备用：查找 saved_images/
    if "saved_images/" in path_str:
        idx = path_str.find("saved_images/")
        return "./data/" + path_str[idx:]
    
    # 如果都找不到，返回原始路径
    return path_str


def to_absolute_path(relative_path: str) -> str:
    """
    将相对路径转换为本地绝对路径
    
    Args:
        relative_path: 相对路径，如 "./data/saved_images/xxx.jpg"
    
    Returns:
        本地绝对路径
    """
    if not relative_path:
        return ""
    
    root = _find_project_root()
    rel = relative_path.lstrip("./").replace("\\", "/")
    return str(root / rel)


def resolve_image_info(image_info: Dict[str, Any]) -> Dict[str, Any]:
    """
    解析图片信息，添加本地路径
    
    Args:
        image_info: 包含 image_path 的字典
    
    Returns:
        添加了 relative_path 和 local_path 的字典
    """
    if not image_info or "image_path" not in image_info:
        return image_info
    
    original_path = image_info["image_path"]
    relative_path = convert_path(original_path)
    local_path = to_absolute_path(relative_path)
    
    # 创建新的字典，保留原始信息并添加新字段
    resolved = dict(image_info)
    resolved["original_path"] = original_path
    resolved["relative_path"] = relative_path
    resolved["local_path"] = local_path
    resolved["exists"] = os.path.exists(local_path)
    
    return resolved


def resolve_images_in_doc(doc) -> None:
    """
    处理文档中的所有图片路径（直接修改文档对象）
    
    Args:
        doc: 包含 metadata.images_info 的 Document 对象
    """
    if not hasattr(doc, 'metadata'):
        return
    
    images_info = doc.metadata.get("images_info", [])
    if not images_info:
        return
    
    # 处理每个图片信息
    resolved_images = []
    for img in images_info:
        if isinstance(img, dict) and "image_path" in img:
            resolved = resolve_image_info(img)
            resolved_images.append(resolved)
        else:
            resolved_images.append(img)
    
    # 更新文档
    doc.metadata["images_info"] = resolved_images
