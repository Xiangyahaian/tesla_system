# 路径都以 infer.py 为参考路径
import os

# Windows 路径（当前项目目录）
base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) + "/"

# 数据路径
pdf_path = base_dir + "data/Tesla_Manual.pdf"
test_doc_path = base_dir + "data/test_docs.txt"
stopwords_path = base_dir + "data/stopwords.txt"
image_save_dir = base_dir + "data/saved_images"
raw_docs_path = base_dir + "data/processed_docs/raw_docs.pkl"
clean_docs_path = base_dir + "data/processed_docs/clean_docs.pkl"
split_docs_path = base_dir + "data/processed_docs/split_docs.pkl"

# 索引路径
bm25_pickle_path = base_dir + "data/saved_index/bm25retriever.pkl"
tfidf_pickle_path = base_dir + "data/saved_index/tfidfretriever.pkl"
milvus_db_path = base_dir + "data/saved_index/milvus.db"
faiss_db_path = base_dir + "data/saved_index/faiss.db"
faiss_qwen_db_path = base_dir + "data/saved_index/faiss_qwen.db"


# 模型路径
m3e_small_model_path = base_dir + "models/AI-ModelScope/m3e-small"
bge_m3_model_path = base_dir + "models/BAAI/bge-m3"
bce_model_path = base_dir + "models/maidalun/bce-embedding-base_v1"
qwen3_embedding_model_path = base_dir + "models/Qwen3-Embedding-0.6B"
qwen3_reranker_model_path = base_dir + "models/Qwen3-Reranker-0.6B"
qwen3_4b_reranker_model_path = base_dir + "models/Qwen3-Reranker-4B"
bge_reranker_model_path = base_dir + "models/BAAI/bge-reranker-v2-m3"
bge_reranker_tuned_model_path = base_dir + "RAG-Retrieval/rag_retrieval/train/reranker/output/bert/runs/checkpoints/checkpoint_0/"
bge_reranker_minicpm_path = base_dir + "models/bge-reranker-v2-minicpm-layerwise"
text2vec_model_path = base_dir + "models/text2vec-base-chinese"
qwen3_8b_tune_model_name = "Qwen3.5-4B"
