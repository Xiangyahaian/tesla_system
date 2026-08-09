# -*- coding: utf-8 -*-
"""
RAG检索引擎 - BM25 + Milvus + Reranker
"""
import os
import sys
from typing import List, Tuple, Dict, Any

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from src.retriever.bm25_retriever import BM25
from src.retriever.milvus_retriever import MilvusRetriever
from src.reranker.bge_m3_reranker import BGEM3ReRanker
from src.constant import bge_reranker_tuned_model_path
from src.utils import merge_docs, post_processing, convert_db_path_to_local, to_absolute_path


class RAGEngine:
    """RAG引擎 - 整合BM25、Milvus和重排序器"""
    
    def __init__(self):
        self.bm25 = BM25(docs=None, retrieve=True)
        self.milvus = MilvusRetriever(docs=None, retrieve=True)
        self.reranker = BGEM3ReRanker(model_path=bge_reranker_tuned_model_path)
    
    def retrieve(self, query: str, topk: int = 5) -> List:
        """使用BM25 + Milvus + Reranker检索文档"""
        bm25_docs = self.bm25.retrieve_topk(query, topk=10)
        milvus_docs = self.milvus.retrieve_topk(query, topk=10)
        merged_docs = merge_docs(bm25_docs, milvus_docs)
        
        if not merged_docs:
            return []
        
        ranked_docs = self.reranker.rank(query, merged_docs, topk=topk)
        return ranked_docs
    
    def build_context(self, docs: List) -> Tuple[str, List[str]]:
        """从文档构建上下文字符串和列表"""
        context_list = [doc.page_content for doc in docs]
        
        context_parts = []
        for idx, doc in enumerate(docs):
            part = f"【{idx+1}】{doc.page_content}"
            images_info = doc.metadata.get("images_info", [])
            if images_info:
                part += "\n[相关图片]"
                for img in images_info:
                    if img.get("title"):
                        # 转换图片路径为本地相对路径
                        original_path = img.get("image_path", "")
                        relative_path = convert_db_path_to_local(original_path)
                        part += f"\n  - {img['title']}: {relative_path}"
            context_parts.append(part)
        
        context_str = "\n\n".join(context_parts)
        return context_str, context_list
    
    def post_process(self, response: str, docs: List) -> Dict[str, Any]:
        """后处理响应，提取引用和图片"""
        return post_processing(response, docs)
