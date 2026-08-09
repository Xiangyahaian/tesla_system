import os

os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
from sentence_transformers import SentenceTransformer
from datasets import load_dataset
import numpy as np
from utils import (
    find_topk_by_single_vecs,
    find_topk_by_multi_vecs,
    find_topk_by_reranker,
    find_topk_by_bm25
)
from sklearn.metrics import ndcg_score


if __name__ == "__main__":
    import argparse

    # 创建 ArgumentParser 对象
    parser = argparse.ArgumentParser(description="Myopic Trap - SQuAD-PosQ")
    parser.add_argument("--data_name_or_path", type=str, required=True)
    parser.add_argument("--model_name_or_path", type=str, default=None)
    parser.add_argument("--model_type", default="local", type=str, choices=["local", "api"])
    parser.add_argument("--first_stage_model_name_or_path", type=str, default=None)
    parser.add_argument("--first_stage_model_type", default="local", type=str, choices=["local", "api"])
    parser.add_argument("--cache_path", type=str, default="./rerank_cache.pickle", help="Path to save the first stage cache for reranking.")
    parser.add_argument(
        "--query_sampling",
        action="store_true",
        help="Whether to sample the queries for evaluation.",
    )
    parser.add_argument(
        "--score_type",
        required=True,
        type=str,
        choices=["bm25", "single_vec", "multi_vec", "reranker"],
    )

    args = parser.parse_args()

    data_name_or_path = args.data_name_or_path
    model_name_or_path = args.model_name_or_path
    model_type = args.model_type
    topk_list = [5, 10, 20, 30, 50, 100]


    # load and process data
    query_answer_start_list, passage_list, query2passage = [], [], {}
    for item in (
        load_dataset(data_name_or_path, split="train").to_list()
        + load_dataset(data_name_or_path, split="validation").to_list()
    ):
        # if the answer of question is in the document, then the document is a positive document
        if item["answers"]["answer_start"]:
            query_answer_start_list.append(
                [item["question"], item["answers"]["answer_start"][0]]
            )
            passage_list.append(item["context"])
            query2passage[item["question"]] = item["context"]
        else:
            passage_list.append(item["context"])
    passage_list = list(set(passage_list))
    passage_list.sort()
    passage2id = {passage: idx for idx, passage in enumerate(passage_list)}
    
    
    if args.query_sampling:
        print("Sampling 1w query due to efficiency")
        import random
        random.seed(42)
        random.shuffle(query_answer_start_list)
        query_answer_start_list = query_answer_start_list[:10000]
    else:
        print("Using all queries!")
    
    query_list = [item[0] for item in query_answer_start_list]  
    labels = np.array(
        [[passage2id[query2passage[query]]] for query, _ in query_answer_start_list]
    )
    answer_start_list = [answer_start for _, answer_start in query_answer_start_list]

    
    print("Data Statistics:")
    print(f"data_name_or_path: {data_name_or_path}")
    print("min(answer_start_list)", min(answer_start_list))
    print("max(answer_start_list)", max(answer_start_list))
    print("number of all queries", len(query_list))
    print("number of all passages", len(passage_list))
    print("min len of passage (words): ", min([len(passage.split(" ")) for passage in passage_list]))
    print("max len of passage (words): ", max([len(passage.split(" ")) for passage in passage_list]))
    
    
    print("Searching Topk ...")
    print(f"Using {args.score_type} {model_type} {model_name_or_path} ")
    if args.score_type == "single_vec":
        topk_index, topk_scores = find_topk_by_single_vecs(
            model_name_or_path, model_type, query_list, passage_list, max(topk_list)
        )
    elif args.score_type == "multi_vec":
        topk_index, topk_scores = find_topk_by_multi_vecs(
            model_name_or_path, model_type, query_list, passage_list, max(topk_list)
        )
    elif args.score_type == "reranker":
        topk_index, topk_scores = find_topk_by_reranker(
            reranker_model_name_or_path=model_name_or_path,
            embedding_model_name_or_path=args.first_stage_model_name_or_path,
            reranker_model_type=args.model_type,
            embedding_model_type=args.first_stage_model_type,
            query_list=query_list,
            passage_list=passage_list,
            topk=max(topk_list),
            recall_topk=max(topk_list),
            cache_path=args.cache_path,
        )
    elif args.score_type == "bm25":
        topk_index, topk_scores = find_topk_by_bm25(
            query_list=query_list,
            passage_list=passage_list,
            topk=max(topk_list),
        )
    print("Search Topk Done.")
    print(f"Result shape: {topk_scores.shape}")
    
    print("--------Evaluation--------")
    print(
        f"model, #queries, min_answer_start, max_answer_start, {', '.join([f'Recall@{k}' for k in topk_list])}, {', '.join([f'NDCG@{k}' for k in topk_list])}"
    )
    # compute recall with different answer_start and top-k
    for min_len, max_len in [
        (0, 100),
        (100, 200),
        (200, 300),
        (300, 400),
        (400, 500),
        (500, 3120),
    ]:
        recall_at_k_list = []
        ndcg_at_k_list = []
        selected_ids = [
            idx
            for idx, answer_start in enumerate(answer_start_list)
            if min_len <= answer_start <= max_len
        ]
        if len(selected_ids) == 0:
            continue
        for topk in topk_list:
            recall_at_k_list.append(
                (topk_index[selected_ids, :topk] == labels[selected_ids, :]).sum()
                / len(selected_ids)
            )
            ndcg_at_k_list.append(
                ndcg_score(
                    y_true=topk_index[selected_ids, :] == labels[selected_ids, :],
                    y_score=topk_scores[selected_ids, :],
                    k=topk,
                )
            )
        recall_at_k_list = [str(float(i)) for i in recall_at_k_list]  # for joining
        ndcg_at_k_list = [str(float(i)) for i in ndcg_at_k_list]  # for joining
        print(
            f"{model_name_or_path}, {len(selected_ids)}, {min_len}, {max_len}, {', '.join(recall_at_k_list)}, {', '.join(ndcg_at_k_list)}"
        )
    print("-------------------------------")