# -*- coding: utf-8 -*-
import os
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Tuple, Union, Any


class BaseRetriever(ABC):
    def __init__(self,  docs: str, retrieve: bool = False) -> None:
        super().__init__()
        self.docs = docs
        self.retrieve = retrieve

    @abstractmethod
    def retrieve_topk(self, query: str, topk=3):
        # 子类必须实现该方法 
        raise NotImplementedError
