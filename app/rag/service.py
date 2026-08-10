# -*- coding: utf-8 -*-
"""RAG 薄封装：复用现有 context.rag_engine.RAGEngine（策略保持原样）。"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Tuple


class RagService:
    def __init__(self):
        self._engine = None
        self._error: Optional[str] = None
        self._lock = threading.Lock()
        self._warmed = False

    def _ensure(self):
        if self._engine is not None or self._error:
            return
        with self._lock:
            if self._engine is not None or self._error:
                return
            try:
                print("[RAG] 正在加载知识库引擎(BM25+Milvus+Reranker)，请稍候...")
                from context.rag_engine import RAGEngine

                self._engine = RAGEngine()
                print("[RAG] 引擎加载完成")
            except Exception as e:
                self._error = str(e)
                self._engine = None
                print(f"[RAG] 引擎加载失败: {e}")

    @property
    def available(self) -> bool:
        self._ensure()
        return self._engine is not None

    def warmup(self) -> bool:
        """启动时预热，避免首问卡在加载模型。与旧 main.py 行为一致。"""
        self._ensure()
        if not self._engine:
            return False
        if self._warmed:
            return True
        try:
            print("[RAG] 热身检索中...")
            self._engine.milvus.retrieve_topk("warmup query", topk=3)
            # 顺带热一下 BM25/jieba
            try:
                self._engine.bm25.retrieve_topk("warmup query", topk=3)
            except Exception:
                pass
            self._warmed = True
            print("[RAG] 热身完成，知识问答可直接使用")
            return True
        except Exception as e:
            print(f"[RAG] 热身跳过: {e}")
            self._warmed = True  # 避免反复卡死
            return False

    def retrieve(self, query: str, topk: int = 5) -> List:
        self._ensure()
        if not self._engine:
            raise RuntimeError(self._error or "RAGEngine 不可用")
        return self._engine.retrieve(query, topk=topk)

    def build_context(self, docs: List) -> Tuple[str, List[str]]:
        self._ensure()
        return self._engine.build_context(docs)

    def post_process(self, response: str, docs: List) -> Dict[str, Any]:
        self._ensure()
        return self._engine.post_process(response, docs)


_RAG: Optional[RagService] = None


def get_rag_service() -> RagService:
    global _RAG
    if _RAG is None:
        _RAG = RagService()
    return _RAG
