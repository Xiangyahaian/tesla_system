# -*- coding: utf-8 -*-
# --------------------------------------------
# 项目名称: LLM任务型对话Agent
# 版权所有  ©丁师兄大模型
# --------------------------------------------

import os
import pickle
import jieba
import hashlib
from langchain.schema import Document
from langchain_community.retrievers import TFIDFRetriever

from src.constant import tfidf_pickle_path


class TFIDF(object):
    def __init__(self, docs, retrieve=False):

        # 创建待编码文档集
        self.documents = docs

        # 初始化TFIDF的知识库
        self.retriever = self.get_TFIDF_retriever(retrieve=retrieve)


    def get_TFIDF_retriever(self, retrieve):
        """
        获取TFIDF检索器，如果已经存在则加载，否则创建并持久化
        """
        if retrieve and os.path.exists(tfidf_pickle_path):
            tfidf_retriever = pickle.load(open(tfidf_pickle_path, 'rb'))
        else:
            tfidf_retriever = TFIDFRetriever.from_documents(self.documents, preprocess_func=self.tokenize)
            pickle.dump(tfidf_retriever, open(tfidf_pickle_path, 'wb'))
        return tfidf_retriever


    def tokenize(self, text):
        """
        使用jieba进行中文分词
        """
        return jieba.lcut(text)


    def retrieve_topk(self, query, topk=10):
        # 获得得分在topk的文档和分数
        self.retriever.k = topk
        query = " ".join(jieba.cut_for_search(query))
        ans_docs = self.retriever.get_relevant_documents(query)
        return ans_docs


if __name__ == "__main__":
    texts = ["打开车窗", "空调加热", "加热座椅"]
    docs = []
    for text in texts:
        unique_id = hashlib.md5(text.encode('utf-8')).hexdigest()
        metadata = {"unique_id": unique_id}
        docs.append(Document(page_content=text, metadata=metadata))
    tfidf = TFIDF(docs)
    tfidf_res = tfidf.retrieve_topk("座椅加热", 3)
    print(tfidf_res)

