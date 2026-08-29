# -*- coding: utf-8 -*-
import os
import fitz
from typing import Tuple
from pymongo.collection import Collection
from typing_extensions import List

from src import constant
from src.fields.manual_images import ManualImages
from src.client.mongodb_config import MongoConfig

# 全局配置
manual_images_collection: Collection = MongoConfig.get_collection("manual_images")
image_save_dir = constant.image_save_dir
pdf_path = constant.pdf_path


# 标题判断配置
TITLE_PROPERTIES = {
    "min_size": 10,
    "max_lines": 3,
    "max_length": 30,
    "bold_weight": 0.7,
    "page_clip": 50,
    "bottom_size": -200
}


def handle_image(img: Tuple, img_index: int, page: fitz.Page) -> ManualImages | None:
    """处理单个图片"""
    xref = img[0]
    base_image = page.parent.extract_image(xref)

    # 跳过小图标
    if base_image["ext"] == "png" or base_image["width"] <= 34:
        return None

    # 保存图片并获取路径
    image_path = save_image(base_image, img_index, page.number)

    # 获取扩展后的图片区域
    img_rect = page.get_image_bbox(img)
    expanded_rect = get_expanded_rect(img_rect, page.rect)

    # 获取关联文本块
    related_blocks = get_related_text_blocks(page, expanded_rect, img_rect.y0)
    title_blocks = [text for is_title, text in related_blocks if is_title]

    return ManualImages(
        image_path=image_path,
        page=page.number + 1,
        title="\n".join(title_blocks)
    )


def save_image(base_image: dict, img_index: int, page_number: int) -> str:
    """保存图片到本地并返回路径"""
    image_name = f"page{page_number + 1}_img{img_index + 1}.{base_image['ext']}"
    image_path = os.path.join(image_save_dir, image_name)
    with open(image_path, "wb") as f:
        f.write(base_image["image"])
    return image_path


def get_expanded_rect(img_rect: fitz.Rect, page_rect: fitz.Rect) -> fitz.Rect:
    """获取扩展后的搜索区域"""
    #expanded = img_rect + (0, -15, 0, img_rect.height * 3)
    expanded = img_rect + (0, TITLE_PROPERTIES["bottom_size"], 0, img_rect.height * 3)
    expanded[3] = min(expanded[3], page_rect[3] - TITLE_PROPERTIES["page_clip"])
    return expanded.intersect(page_rect)


def get_related_text_blocks(page: fitz.Page, rect: fitz.Rect, img_y: float) -> List[Tuple[bool, str]]:
    """获取与图片相关的文本块"""
    related_blocks = []
    for block in page.get_text("blocks"):
        block_rect = fitz.Rect(block[:4])
        if not block_rect.intersects(rect):
            continue

        block_text = block[4].strip()
        above = block_rect.y1 < img_y
        is_title_block = is_title_block_candidate(page, block, above)
        related_blocks.append((is_title_block, block_text))

    return related_blocks


def is_title_block_candidate(page: fitz.Page, block: tuple, above: bool) -> bool:
    """判断是否为标题候选块"""
    if block[6] != 0 or not block[4].strip():
        return False

    try:
        span = page.get_text("dict")["blocks"][block[5]]["lines"][0]["spans"][0]
    except (IndexError, KeyError):
        return False

    text = block[4].strip()
    font_size = span["size"]
    is_bold = "bold" in span["font"].lower()

    # 排除带句尾标点的文本
    if text.endswith(('.', '。', '!', '！')):
        return False

    # 计分规则
    score = 0
    score += 2 if font_size >= TITLE_PROPERTIES["min_size"] else 0
    score += 1 if is_bold else 0
    score += 0.5 if (text.count('\n') + 1) <= TITLE_PROPERTIES["max_lines"] else 0
    score += 0.5 if len(text) <= TITLE_PROPERTIES["max_length"] else 0
    score += 2 if above else -1

    return score >= 3
