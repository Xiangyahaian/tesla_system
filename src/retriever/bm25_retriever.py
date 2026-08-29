# -*- coding: utf-8 -*-
import os
import pickle
import jieba
import hashlib
from langchain.schema import Document
from langchain_community.retrievers import BM25Retriever

from src.constant import bm25_pickle_path, stopwords_path

with open(stopwords_path) as fd:
    tokens = fd.readlines()
    _stopwords = [t.strip() for t in tokens]


class BM25(object):
    def __init__(self, docs, retrieve=False):
        # 创建待编码文档集
        self.documents = docs 

        # 初始化BM25的知识库
        self.retriever = self.get_BM25_retriever(retrieve=retrieve)



    def get_BM25_retriever(self, retrieve):
        """
        获取BM25检索器，如果已经存在则加载，否则创建并持久化
        """
        if retrieve and os.path.exists(bm25_pickle_path):
            bm25_retriever = pickle.load(open(bm25_pickle_path, 'rb'))
        else:
            bm25_retriever = BM25Retriever.from_documents(self.documents, preprocess_func=self.tokenize)
            pickle.dump(bm25_retriever, open(bm25_pickle_path, 'wb'))
        return bm25_retriever


    def tokenize(self, text):
        """
        使用jieba进行中文分词
        """
        tokens = jieba.lcut(text)
        return [t for t in tokens if t not in _stopwords]


    def retrieve_topk(self, query, topk=10):
        # 获得得分在topk的文档和分数
        self.retriever.k = topk
        # query_tokens = jieba.cut_for_search(query)
        # query_tokens_filter = [t for t in query_tokens if t not in _stopwords]
        # query = " ".join(query_tokens_filter)
        ans_docs = self.retriever.invoke(query)
        return ans_docs


if __name__ == "__main__":
    texts = ["打开车窗", "空调加热", "加热座椅"]
    docs = []
    for text in texts:
        unique_id = hashlib.md5(text.encode('utf-8')).hexdigest()
        metadata = {"unique_id": unique_id}
        docs.append(Document(page_content=text, metadata=metadata))
    bm25 = BM25(docs)
    bm25_res = bm25.retrieve_topk("座椅加热", 3)
    print(bm25_res)

