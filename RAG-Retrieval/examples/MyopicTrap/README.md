# Myopic Trap: Positional Bias in Information Retrieval

Code for the paper:
**[Benchmarking the Myopic Trap: Positional Bias in Information Retrieval](https://arxiv.org/abs/2505.13950)**
*Ziyang Zeng, Dun Zhang, Jiacheng Li, Panxiang Zou, Yuqing Yang (2025)*

## 📘 Overview

Why do modern retrieval models often overlook relevant content that appears later in documents?

This repository accompanies our paper, which investigates **positional bias**—a phenomenon we term the **Myopic Trap**, where retrieval systems disproportionately focus on the beginning of documents while neglecting relevant information further down.

Our semantics-preserving evaluation framework offers a comprehensive way to measure how modern SOTA retrieval models—including BM25, embedding models, ColBERT-style models, and rerankers—handle content that appears at different positions in a document, using thoughtfully designed benchmarks that reflect real-world biases.


## 📊 Datasets

We provide two benchmarks for position-aware retrieval:

* **SQuAD-PosQ**: Reformulated from [SQuAD v2.0](https://huggingface.co/datasets/rajpurkar/squad_v2), with queries grouped by the answer span’s position in the passage. Useful for evaluating bias in shorter contexts.

* **[FineWeb-PosQ](https://huggingface.co/datasets/NovaSearch/FineWeb-PosQ)**: A new dataset based on the [FineWeb-edu](https://huggingface.co/datasets/HuggingFaceFW/fineweb-edu) corpus. It contains long passages (500–1024 words) and synthetic position-targeted questions, categorized as `beginning`, `middle`, or `end`.

## 🧪 Reproducing Our Experiments

We provide scripts to reproduce our benchmark experiments:

```bash
# Run on SQuAD-PosQ
sh run_exp_SQuAD-PosQ.sh

# Run on FineWeb-PosQ
sh run_exp_FineWeb-PosQ.sh
```

All experiments use `NDCG@10` as the main metric, and the tiny subsets (i.e., --query_sampling) enable fast evaluation for compute-intensive models.

---

## 🧱 Code Structure

```text
.
├── run_exp_SQuAD-PosQ.sh         # Runs experiments on SQuAD-PosQ
├── run_exp_FineWeb-PosQ.sh       # Runs experiments on FineWeb-PosQ
├── exp_SQuAD-PosQ.py             # Benchmark generation + evaluation on SQuAD-PosQ
├── exp_FineWeb-PosQ.py           # Evaluation on FineWeb-PosQ
├── utils.py                      # Top-K Retrieval utilities (single-vector, ColBERT-style late interaction, reranking)
├── commercial_embedding_api.py   # Wrapper for API-based embedding models
```


## 📈 Key Findings

* BM25, despite its simplicity, shows **robustness** due to position-agnostic term matching.
* Embedding models and ColBERT-style retrievers show a **consistent drop in performance** as answer positions shift toward later document sections.
* ColBERT-style approach **mitigate bias better** than single-vector embedding approach under the same training configuration.
* Reranker models (e.g., based on deep cross-attention) are **largely immune** to the Myopic Trap.

📄 For more results, see our [arXiv paper](https://arxiv.org/abs/2505.13950).


## 📌 Citation

If you use this work, please cite us:

```bibtex
@misc{zeng2025myopictrap,
      title={Benchmarking the Myopic Trap: Positional Bias in Information Retrieval}, 
      author={Ziyang Zeng and Dun Zhang and Jiacheng Li and Panxiang Zou and Yuqing Yang},
      year={2025},
      eprint={2505.13950},
      archivePrefix={arXiv},
      primaryClass={cs.IR},
      url={https://arxiv.org/abs/2505.13950}, 
}
```
