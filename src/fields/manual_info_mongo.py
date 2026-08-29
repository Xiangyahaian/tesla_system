# -*- coding: utf-8 -*-
from typing import Optional

from pydantic import BaseModel, Field

from src.fields.manual_images import ManualImages


class ManualInfo(BaseModel):
    unique_id: str = Field(description="唯一标识符")
    metadata: dict = Field(description="存储文档的meta信息")
    page_content: Optional[str] = Field(description="文档分片的内容")
