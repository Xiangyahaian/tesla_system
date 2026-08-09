export HF_ENDPOINT="https://hf-mirror.com"
export VOYAGE_KEY=""
# export CUDA_VISIBLE_DEVICES=1

# echo "run exp3 bm25"

# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --score_type bm25 \
#     2>&1 >> run_exp_FineWeb-PosQ.log

# echo "run exp3 single embedding"

# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/NovaSearch/stella_en_400M_v5 \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_FineWeb-PosQ.log

# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_FineWeb-PosQ.log

# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/BAAI/bge-m3 \
#     --model_type local \
#     --score_type single_vec \
#     2>&1 >> run_exp_FineWeb-PosQ.log 

# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path voyage \
#     --model_type api \
#     --score_type single_vec \
#     2>&1 >> run_exp_FineWeb-PosQ.log

# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path openai \
#     --model_type api \
#     --score_type single_vec \
#     2>&1 >> run_exp_FineWeb-PosQ.log

# echo "run exp3 reranker"

# python exp_FineWeb-PosQ.py\
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/BAAI/bge-reranker-v2-m3 \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_FineWeb-PosQ.log 

# python exp_FineWeb-PosQ.py\
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/Alibaba-NLP/gte-multilingual-reranker-base \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_FineWeb-PosQ.log 


# python exp_FineWeb-PosQ.py\
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path rerank-2 \
#     --model_type api \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_FineWeb-PosQ.log 

# python exp_FineWeb-PosQ.py\
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/BAAI/bge-reranker-v2-gemma \
#     --model_type local \
#     --first_stage_model_name_or_path /data/zzy/models/nvidia/NV-embed-v2 \
#     --first_stage_model_type local \
#     --score_type reranker \
#     --query_sampling \
#     2>&1 >> run_exp_FineWeb-PosQ.log


# echo "run exp3 multi embedding"


# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/BAAI/bge-m3 \
#     --model_type local \
#     --score_type multi_vec \
#     --query_sampling \
#     2>&1 >> run_exp_FineWeb-PosQ.log


# python exp_FineWeb-PosQ.py \
#     --data_name_or_path NovaSearch/FineWeb-PosQ \
#     --model_name_or_path /data/zzy/models/lightonai/colbertv2.0 \
#     --model_type local \
#     --score_type multi_vec \
#     --query_sampling \
#     2>&1 >> run_exp_FineWeb-PosQ.log