# -*- coding: utf-8 -*-
import random
import json
import requests
import os
import pickle
from typing import List

from src.constant import clean_docs_path


URL = "http://0.0.0.0:6000/v1/semantic-chunks"


def request_semantic_chunk(sentences, group_size):
    headers = {
        "Content-Type":"application/json"
    }
    payload = json.dumps({
        "sentences": sentences,
        "group_size": group_size
    })
    try:
        response = requests.post(
            URL,
            headers=headers,
            data=payload
        )
        res = response.json()
        text = res["chunks"]
    except Exception as e:
        print(f"call reject failed:{e}")
        text = sentences
    return text


if __name__ == '__main__':
    data = pickle.load(open("data/processed_docs/clean_docs.pkl", "rb"))
    index = random.sample(range(len(data)), 10)
    for idx in index:
        doc = data[idx].page_content
        res = request_semantic_chunk(doc, 10)
        print("="*100)
        for r in res:
            print(r)
            print("="*100)

