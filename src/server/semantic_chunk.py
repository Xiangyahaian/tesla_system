# -*- coding: utf-8 -*-
import gc
import re
import sys
import math
import requests
import uvicorn
import torch
import pandas as pd
from contextlib import asynccontextmanager
from typing import List, Literal, Optional, Tuple, Union
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse
from sentence_transformers import SentenceTransformer
from sklearn.cluster import AgglomerativeClustering

from src import constant


gc.collect()
torch.cuda.empty_cache()
device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
_min_chunk_size = 50
_min_doc_size = 256 


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    An asynchronous context manager for managing the lifecycle of the FastAPI app.
    It ensures that GPU memory is cleared after the app's lifecycle ends.
    """
    yield
    if torch.cuda.is_available():
        torch.cuda.empty_cache()
        torch.cuda.ipc_collect()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class SemanticRequest(BaseModel):
    sentences: str
    group_size: Optional[int] = 5


class ChunkResponse(BaseModel):
    chunks: List[str]


@app.post("/v1/semantic-chunks", response_model=ChunkResponse)
async def create_chat_completion(request: SemanticRequest):
    """将句子按语义相似性分组

    Args:
        sentences: 待分组的句子列表
        group_size: 每组的目标最大句子数（实际可能略多）

    Returns:
        合并后的分组文本列表

    Raises:
        HTTPException: 当输入参数不合法时
    """

    global embedding_model

    # 参数校验
    if request.group_size < 1:
        raise HTTPException(status_code=400, detail="Invalid request")

    # 当数据量不足时直接返回
    if len(request.sentences) <= _min_doc_size:
        return ChunkResponse(chunks=[request.sentences])

    # 考虑考虑文档标题
    split_docs = re.split(f'(###)', request.sentences) 
    split_docs = [k for k in split_docs if k.strip()]
    if split_docs[0] == "###":
        split_docs = [''.join(split_docs[i:i+2]) for i in range(0, len(split_docs), 2)]
    else:
        split_docs = [split_docs[0]] + [''.join(split_docs[i:i+2]) for i in range(1, len(split_docs), 2)]


    if len(split_docs) > 1:
        return ChunkResponse(chunks=split_docs)

    split_docs = request.sentences.split("\n\n")

    if len(split_docs) <= request.group_size:
        return ChunkResponse(chunks=split_docs)

    # 计算合理的聚类数量（向上取整）
    n_clusters = max(1, math.ceil(len(split_docs) / request.group_size))

    # 生成嵌入向量（已自动使用GPU加速）
    embeddings = embedding_model.encode(split_docs)

    # 使用余弦相似度的层次聚类
    clustering = AgglomerativeClustering(
        n_clusters=n_clusters,
        metric="cosine",  # 使用余弦距离
        linkage="average",  # 使用平均链接算法
        compute_full_tree="auto"
    )

    try:
        labels = clustering.fit_predict(embeddings)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Clustering failed: {str(e)}")

    df = pd.DataFrame({"sentence": split_docs, "label": labels})

    result = (df.groupby("label", sort=True)['sentence']
              .agg(lambda x: " ".join(x))
              .to_dict())

    # 合并误切分的small chunks
    docs = list(result.values())
    merged_docs = []
    index = 0
    while index < len(docs):
        cur_doc = docs[index]
        plus = 1
        for sub_idx in range(index+1, len(docs)):
             if len(docs[sub_idx]) < _min_chunk_size:
                 cur_doc += docs[sub_idx]
                 plus += 1
             else:
                 break
        index += plus
        merged_docs.append(cur_doc)

    return ChunkResponse(chunks=merged_docs)


if __name__ == "__main__":
    embedding_model = SentenceTransformer(constant.m3e_small_model_path)
    uvicorn.run(app, host="0.0.0.0", port=6000, workers=1)
