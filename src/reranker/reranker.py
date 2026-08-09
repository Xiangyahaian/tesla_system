# -*- coding: utf-8 -*-
# --------------------------------------------
# 项目名称: LLM任务型对话Agent
# 版权所有  ©丁师兄大模型
# --------------------------------------------

import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union, Any


class RerankerBase(ABC):
    def __init__(self,  model_path: str, max_length: int = 512) -> None:
        super().__init__()
        
        # 设置模型标识符
        self.model_path = model_path

        self.max_length = max_length

    @abstractmethod
    def rank(self, query: str, candidate_docs: List[str], top_k=10)  -> List[Tuple[float, str]]:
        # 当尝试实例化该抽象基类时抛出未实现错误
        raise NotImplementedError
