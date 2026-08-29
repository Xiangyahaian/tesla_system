# -*- coding: utf-8 -*-
import re
import os
import sys
from pathlib import Path
from langchain_core.documents import Document
from src.client.mongodb_config import MongoConfig

manual_collection = MongoConfig.get_collection("manual_text")


# 路径解析功能（嵌入 utils）
def _get_project_root() -> Path:
    """查找项目根目录（包含 run.py 的目录）"""
    cwd = Path.cwd()
    for _ in range(5):
        if (cwd / "run.py").exists():
            return cwd
        parent = cwd.parent
        if parent == cwd:
            break
        cwd = parent
    # 默认返回 src 的父目录
    return Path(__file__).resolve().parent.parent


def convert_db_path_to_local(db_path: str) -> str:
    """
    将 MongoDB 绝对路径转换为本地相对路径
    
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
    
    return path_str


def to_absolute_path(relative_path: str) -> str:
    """将相对路径转换为本地绝对路径"""
    if not relative_path:
        return ""
    
    root = _get_project_root()
    rel = relative_path.lstrip("./").replace("\\", "/")
    return str(root / rel)


def merge_docs(docs1, docs2):
    merged_docs = []
    merged_ids = set()
    candidate_docs = docs1 + docs2
    for doc in candidate_docs:
        parent_id = doc.metadata.get("parent_id")
        if parent_id:
            parent_mg = manual_collection.find_one({"unique_id": parent_id})
            unique_id = parent_mg["unique_id"]
            if unique_id and unique_id not in merged_ids:
                merged_ids.add(unique_id)
                parent_doc = Document(page_content=parent_mg["page_content"], metadata=parent_mg["metadata"])
                merged_docs.append(parent_doc)
        else:
            unique_id = doc.metadata.get("unique_id")
            if unique_id and unique_id not in merged_ids:
                merged_ids.add(unique_id)
                merged_docs.append(doc)
    return merged_docs




def post_processing(response, docs):
    all_cites = re.findall("[【](.*?)[】]", response) 
    cites = []
    for cite in all_cites:
        cite = re.sub("[{} 【】]", "", cite)
        cite = cite.replace(",", "，")
        cite = [int(k) for k in cite.split("，") if k.isdigit()]
        cites.extend(cite)
    cites = list(set(cites))
    answer = re.sub("[【](.*?)[】]", "", response)
    answer = re.sub("[{}【】]", "", answer)

    related_images = []
    seen_images = set()  # 用于图片去重
    pages = []
    for index in cites:
        if index > len(docs):
            continue
        images = docs[index-1].metadata["images_info"]
        pages.append(docs[index-1].metadata["page"])
        for image in images:
            if image["title"]:
                # 使用 image_path 作为唯一标识去重
                image_path = image.get("image_path", "")
                if image_path in seen_images:
                    continue
                seen_images.add(image_path)
                
                # 转换图片路径为本地可用路径
                resolved_image = dict(image)
                if image_path:
                    resolved_image["original_path"] = image_path
                    resolved_image["relative_path"] = convert_db_path_to_local(image_path)
                    resolved_image["local_path"] = to_absolute_path(resolved_image["relative_path"])
                    resolved_image["exists"] = os.path.exists(resolved_image["local_path"])
                related_images.append(resolved_image)
    pages = sorted(list(set(pages)))
    return {
        "answer": answer,
        "cite_pages": pages,
        "related_images": related_images
    }
