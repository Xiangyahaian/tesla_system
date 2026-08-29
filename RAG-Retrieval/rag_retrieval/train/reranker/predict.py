# -*- coding: utf-8 -*-
import json
from FlagEmbedding import FlagReranker
model_path = "output/bert_ex1/runs/checkpoints/checkpoint_0/"
reranker = FlagReranker(model_path, use_fp16=True)

data_path = "/root/autodl-tmp/RAG/data/rerank_data/test.json"

total = 0
top1_right= 0
top3_right= 0
for line in open(data_path):
    info = json.loads(line)
    preds = []
    for i in range(len(info["content"])):
        score = reranker.compute_score([info["query"], info["content"][i]], normalize=True)
        preds.append(score[0])
    print("预测：", info["query"], preds)
    if all(preds[0] >= preds[i+1] for i in range(len(preds)-1)):
        top1_right += 1
    if all(preds[i] >= preds[i+1] for i in range(len(preds)-1)):
        top3_right += 1
    total += 1

print("total:", total, "\testimated top1 acc: ", top1_right/total, "top3 acc: ", top3_right/total)
