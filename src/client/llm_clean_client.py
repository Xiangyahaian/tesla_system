# -*- coding: utf-8 -*-
import os
import json
import re
import requests
from openai import OpenAI
import concurrent.futures
from tqdm import tqdm
from more_itertools import divide
from langchain_core.documents import Document


MAX_WORKERS = 20

LLM_CLEAN_PROMPT = """
你是一个专业的文档整理助手，负责对汽车用户手册中的内容进行整理和总结。请根据以下要求对文档进行处理：

1. **让句子变得更加通顺**：重新整合句子、段落，去除一些不必要的符号，例如换行符等。
2. **按标题归类整理**：按照文档的语义关系，把属于同一个标题下的文档做归类合并, 记住标题要用markdown的形式加粗，例如###。

请根据以下文档内容进行整理：
{}
整理后的输出：
"""

llm_client = OpenAI(
    api_key=os.environ['DOUBAO_API_KEY'],
    base_url=os.environ['DOUBAO_BASE_URL']
)


def chat(doc, model="ep-20260308002713-kftjg"):

    headers = {
        "Authorization": os.environ["DOUBAO_API_KEY"],
        "Content-Type": "application/json"
    }

    completion = llm_client.chat.completions.create(
        model=os.environ["DOUBAO_MODEL_NAME"],
        messages=[
            {"role": "user", "content": doc}
        ],
        top_p=0,
        temperature=0.001
    )
    result = completion.choices[0].message.content

    return result


def request_llm_clean(docs):
    clean_docs = []
    docs_mapping = {doc.metadata['unique_id']: doc for doc in docs}
    docs_groups = [list(group) for group in divide(MAX_WORKERS, docs)]
    for groups in docs_groups:
        with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = {doc.metadata['unique_id']: executor.submit(chat,
                LLM_CLEAN_PROMPT.format(doc.page_content)) for doc in groups}

            for unique_id in tqdm(futures):
                future = futures[unique_id]
                result = future.result()
                if result is None:
                    continue
                clean_docs.append(
                   Document(page_content=result, metadata=docs_mapping[unique_id].metadata) 
                )
    return clean_docs


if __name__ == "__main__":
    doc = "".join(open("./data/ut/test_docs.txt").readlines())
    res = chat(LLM_CLEAN_PROMPT.format(doc))
    print(res)
