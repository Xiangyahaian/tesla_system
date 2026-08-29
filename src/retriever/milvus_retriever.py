# -*- coding: utf-8 -*-
import time
import hashlib
import pandas as pd
from pymilvus import (
    connections,
    utility,
    FieldSchema,
    CollectionSchema,
    DataType,
    Collection,
    AnnSearchRequest,
    RRFRanker,
    WeightedRanker
)
from langchain_core.documents import Document
from pymilvus.model.hybrid import BGEM3EmbeddingFunction
from pymilvus.model.reranker import BGERerankFunction

from src.fields.manual_images import ManualImages
from src.constant import test_doc_path, bge_m3_model_path, milvus_db_path
from src.client.mongodb_config import MongoConfig


EMB_BATCH = 50
MAX_TEXT_LENGTH = 512 
ID_MAX_LENGTH = 100
COL_NAME = "hybrid_bge_m3" 

mongo_collection = MongoConfig.get_collection("manual_text")


def _connect_local_milvus(uri: str, attempts: int = 6) -> None:
    """Milvus Lite 同一时刻只能被一个进程打开；占用时等一下再试。"""
    last: Exception | None = None
    for i in range(max(1, attempts)):
        try:
            connections.connect(uri=uri)
            return
        except Exception as e:
            last = e
            text = (str(e) or "").lower()
            locked = "opened by another" in text or "open local milvus" in text
            if not locked or i + 1 >= attempts:
                break
            wait = 0.8 * (i + 1)
            print(f"[Milvus] milvus.db 被其它进程占用，{wait:.1f}s 后重试（{i + 1}/{attempts}）")
            time.sleep(wait)
    raise last or RuntimeError("Open local milvus failed")


_connect_local_milvus(milvus_db_path)
embedding_handler = BGEM3EmbeddingFunction(model_name=bge_m3_model_path, device="cuda")


class MilvusRetriever:
    def __init__ (self, docs, retrieve=False):
        fields = [
            # 构建查询ID，primary key
            FieldSchema(name="unique_id", dtype=DataType.VARCHAR, is_primary=True, max_length=ID_MAX_LENGTH),
            # 存储原文，dense vector和sparse vector
            FieldSchema(name="text", dtype=DataType.VARCHAR, max_length=MAX_TEXT_LENGTH),
            FieldSchema(name="sparse_vector", dtype=DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema(name="dense_vector", dtype=DataType.FLOAT_VECTOR, dim=embedding_handler.dim["dense"]),
        ]
        schema = CollectionSchema(fields)

        if not retrieve and utility.has_collection(COL_NAME):
            Collection(COL_NAME).drop()
        self.col = Collection(COL_NAME, schema, consistency_level="Strong")

        sparse_index = {"index_type": "SPARSE_INVERTED_INDEX", "metric_type": "IP"}
        dense_index = {"index_type": "AUTOINDEX", "metric_type": "IP"}
        self.col.create_index("sparse_vector", sparse_index)
        self.col.create_index("dense_vector", dense_index)
        self.col.load()

        # 如果是非检索阶段，先构建索引
        if not retrieve:
            self.save_vectorstore(docs)


    def save_vectorstore(self, docs: list[str]): 

        raw_texts = [doc.page_content for doc in docs]
        unique_ids = [doc.metadata["unique_id"] for doc in docs]

        # 计算embedding
        texts_embeddings = embedding_handler(raw_texts)

        # batch embedding 插入
        for i in range(0, len(docs), EMB_BATCH):
            batched_entities = [
                unique_ids[i : i + EMB_BATCH],
                raw_texts[i : i + EMB_BATCH],
                texts_embeddings["sparse"][i : i + EMB_BATCH],
                texts_embeddings["dense"][i : i + EMB_BATCH],
            ]
            self.col.insert(batched_entities)
        print("索引构建完成，插入了{}条数据:".format(self.col.num_entities))


    def dense_search(self, query_dense_embedding, limit):
        search_params = {"metric_type": "IP", "params": {}}
        res = self.col.search(
            [query_dense_embedding],
            anns_field="dense_vector",
            limit=limit,
            output_fields=["unique_id", "text"],
            param=search_params,
        )
        return res


    def sparse_search(self, query_sparse_embedding, limit):
        search_params = {
            "metric_type": "IP",
            "params": {},
        }
        res = self.col.search(
            [query_sparse_embedding],
            anns_field="sparse_vector",
            limit=limit,
            output_fields=["unique_id", "text"],
            param=search_params,
        )
        return res


    def hybrid_search(
        self,
        query_dense_embedding,
        query_sparse_embedding,
        sparse_weight=1.0,
        dense_weight=1.0,
        limit=10,
    ):
        dense_search_params = {"metric_type": "IP", "params": {}}
        dense_req = AnnSearchRequest(
            [query_dense_embedding], "dense_vector", dense_search_params, limit=limit
        )
        sparse_search_params = {"metric_type": "IP", "params": {}}
        sparse_req = AnnSearchRequest(
            [query_sparse_embedding], "sparse_vector", sparse_search_params, limit=limit
        )
        # rerank = WeightedRanker(sparse_weight, dense_weight)
        rerank = RRFRanker()
        res = self.col.hybrid_search(
            [sparse_req, dense_req],
            rerank=rerank,
            limit=limit,
            output_fields=["unique_id", "text"]
        )
        return res


    def retrieve_topk(self, query, topk=10):
        t1 = time.time()
        # 抽取query的embedding 
        query_embeddings = embedding_handler.encode_queries([query])

        # 检索Topk
        hybrid_results = self.hybrid_search(
            query_embeddings["dense"][0],
            query_embeddings["sparse"][[0]],
            sparse_weight=0.7,
            dense_weight=1.0,
            limit=topk
        )[0]

        # 关联mongo数据
        related_docs = []
        for result in hybrid_results:
            search_res = mongo_collection.find_one({"unique_id": result["id"]})
            #images_list = []
            #for image in search_res["metadata"]["images_info"]:
            #    images_list.append(ManualImages(**image))
            #search_res["metadata"]["images_info"] =  images_list 
            doc = Document(page_content=search_res["page_content"], metadata=search_res["metadata"])
            related_docs.append(doc)

        return related_docs 


if __name__ == "__main__":
    texts = [k for k in open(test_doc_path).readlines()]
    docs = []
    for text in texts:
        unique_id = hashlib.md5(text.encode('utf-8')).hexdigest()
        metadata = {"unique_id": unique_id}
        docs.append(Document(page_content=text, metadata=metadata))
    retriever = MilvusRetriever(docs)
    query = "Model3支持的钥匙类型"
    results = retriever.retrieve_topk(query, 2)
    for res in results:
        print(res)
        print("="*100)


