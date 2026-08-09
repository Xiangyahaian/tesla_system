export HF_ENDPOINT="https://hf-mirror.com"
export VOYAGE_KEY=""
# export CUDA_VISIBLE_DEVICES=0

# echo "run exp1 bm25"

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2 \
#     --score_type bm25 \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# echo "run exp1 single embedding"

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path /data/zzy/models/jinaai/jina-embeddings-v3 \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path /data/zzy/models/NovaSearch/stella_en_400M_v5\
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path /data/zzy/models/Alibaba-NLP/gte-Qwen2-7B-instruct \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path /data/zzy/models/BAAI/bge-m3 \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log 

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path voyage \
#     --model_type api \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path openai \
#     --model_type api \
#     --score_type single_vec \
#     2>&1 >> run_exp_SQuAD-PosQ.log


# echo "run exp1 multi embedding"

# python exp_SQuAD-PosQ.py \
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2\
#     --model_name_or_path /data/zzy/models/BAAI/bge-m3 \
#     --model_type local \
#     --score_type multi_vec \
#     --query_sampling \
#     2>&1 >> run_exp_SQuAD-PosQ.log 


# echo "run exp1 reranker"

# python exp_SQuAD-PosQ.py\
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2 \
#     --model_name_or_path /data/zzy/models/BAAI/bge-reranker-v2-m3 \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_SQuAD-PosQ.log 

# python exp_SQuAD-PosQ.py\
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2 \
#     --model_name_or_path /data/zzy/models/Alibaba-NLP/gte-multilingual-reranker-base \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_SQuAD-PosQ.log 

# python exp_SQuAD-PosQ.py\
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2 \
#     --model_name_or_path /data/zzy/models/jinaai/jina-reranker-v2-base-multilingual \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_SQuAD-PosQ.log

# python exp_SQuAD-PosQ.py\
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2 \
#     --model_name_or_path rerank-2 \
#     --model_type api \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_SQuAD-PosQ.log 

# python exp_SQuAD-PosQ.py\
#     --data_name_or_path /data/zzy/data/rajpurkar/squad_v2 \
#     --model_name_or_path /data/zzy/models/BAAI/bge-reranker-v2-gemma \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_SQuAD-PosQ.log