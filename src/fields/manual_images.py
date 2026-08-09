# -*- coding: utf-8 -*-
# --------------------------------------------
# 项目名称: LLM任务型对话Agent
# 版权所有  ©丁师兄大模型
# --------------------------------------------


from typing import Optional

from pydantic import BaseModel, Field


class ManualImages(BaseModel):
    page: Optional[int] = Field(ge=1, description="页码从1开始")
    image_path: Optional[str] = Field(min_length=1, description="图片存储路径")
    title: Optional[str] = Field(
        description="标题内容，多个区块用换行符连接"
    )
