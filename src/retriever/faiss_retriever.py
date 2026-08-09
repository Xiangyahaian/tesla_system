# -*- coding: utf-8 -*-
# --------------------------------------------
# 项目名称: LLM任务型对话Agent
# 版权所有  ©丁师兄大模型
# --------------------------------------------


import os
import jieba
import torch
import hashlib
from langchain.schema import Document
from langchain_community.vectorstores import FAISS
from langchain_community.embeddings import HuggingFaceEmbeddings

from src.constant import faiss_db_path, bce_model_path
from src.retriever.retriever import BaseRetriever


class FaissRetriever(BaseRetriever):
    def __init__(self, docs, retrieve=False):
        # 基于langchain的Faiss库
        self.embeddings = HuggingFaceEmbeddings(
            model_name=bce_model_path,
            model_kwargs={"device": "cuda"},
        )

        if retrieve and os.path.exists(faiss_db_path):
            # 如果之前已经有向量化的结果，直接用
            self.vector_store = FAISS.load_local(save_path, self.embeddings, allow_dangerous_deserialization=True)
        else:
            self.vector_store = FAISS.from_documents(docs, self.embeddings)
            # 对向量结果做一个持久化
            self.vector_store.save_local(faiss_db_path)

        # 使用完模型后释放显存
        del self.embeddings
        torch.cuda.empty_cache()

    def retrieve_topk(self, query, topk):
        # 获取top-K分数最高的文档块
        context = self.vector_store.similarity_search_with_score(query, k=topk)
        return context

    # 返回faiss向量检索对象
    def GetvectorStore(self):
        return self.vector_store


if __name__ == "__main__":
    texts = ["打开车窗", "空调加热", "加热座椅"]
    docs = []
    for text in texts:
        unique_id = hashlib.md5(text.encode('utf-8')).hexdigest()
        metadata = {"unique_id": unique_id}
        docs.append(Document(page_content=text, metadata=metadata))

    # faiss 召回: bce-base, 类似的embedding模型还可以采用gte, m3e, bge
    bce_faissretriever = FaissRetriever(docs)
    bce_faiss_ans = bce_faissretriever.retrieve_topk("座椅加热", 3)
    print(bce_faiss_ans)
