[English | [中文](README_zh.md)]
# Environment Setup

```bash
conda create -n rag-retrieval python=3.8 && conda activate rag-retrieval
# To avoid compatibility issues between the automatically installed torch and your local CUDA, it is recommended to manually install a torch version compatible with your local CUDA before proceeding to the next step.
pip install -r requirements.txt 
```

| Requirement | Recommend |
| --------------- | ---------------- |
| accelerate | 1.0.1 |
| deepspeed | 0.15.4 |
| transformers | 4.44.2 |

# Fine-tuning the Model

After installing the dependencies, we'll use specific examples to demonstrate how to fine-tune an open-source ranking model (BAAI/bge-reranker-v2-m3) using your own data. Alternatively, you can train a ranking model from scratch using BERT-based models (hfl/chinese-roberta-wwm-ext) or LLM-based models (Qwen/Qwen2.5-1.5B). Additionally, we support distilling the ranking capabilities of LLM-based models into smaller BERT models.

## Data Loading

We offer two ways to load datasets to support different types of loss functions:

### Pointwise Data Loading

The standard format for a pointwise dataset. For an example, see [pointwise_reranker_train_data.jsonl](../../../example_data/pointwise_reranker_train_data.jsonl).
```
{"query": str, "content": str, "label": int|float}
```
- `content` is the actual content of the document corresponding to the query.
- `label` is the supervision signal for model fine-tuning and comes in two types:
  - Continuous: A continuous score between 0 and 1.
  - Discrete: Multi-level relevance labels (0/1/2/...). The data loading module will uniformly scale them to a continuous value in the range of 0 to 1.

> When the relevance is represented by multi-level labels, by setting `max_label` and `min_label`, the dataset will automatically scale the multi-level labels uniformly to the score range of 0 to 1.
> For example, if there are three-level labels (0, 1, 2) in the dataset, after scaling, we get: { label 0: 0, label 1: 0.5, label 2: 1 }.

Two loss functions are supported under this configuration:
- Mean Squared Error Loss (MSE):
```math
\mathrm{MSE}=\frac{1}{N} \sum_{i=1}^{N}\left(y_{i}-\hat{y}_{i}\right)^{2}
```
- Binary Cross Entropy Loss (BCE):
```math
\mathrm{BCE}=-\frac{1}{N} \sum_{i=1}^{N}\left(y_{i} \log \left(\hat{y}_{i}\right)+\left(1-y_{i}\right) \log \left(1-\hat{y}_{i}\right)\right)
```

```math
\mathrm{sigmoid}(x)=\frac{1}{1+e^{-x}}
```

Here, $`y_{i}`$ is the true relevance label in the range of 0 to 1, $`\hat{y}_i`$ is the result of the model's output logit after sigmoid normalization, and $`N`$ is the size of the entire dataset.

The overall optimization objective is to judge the absolute relevance of single-point query-content.

It's worth mentioning that users can use LLMs to obtain continuous relevance labels for distillation. Relevant example code can be found in the [examples/distill_llm_to_bert_reranker](../../../examples/distill_llm_to_bert_reranker) directory.

✅ Example configuration information is as follows:
```
train_dataset: "../../../example_data/pointwise_reranker_train_data.jsonl"
train_dataset_type: "pointwise"
max_label: 2
min_label: 0
max_len: 512
shuffle_rate: 0.0
val_dataset: "../../../example_data/pointwise_reranker_eval_data.jsonl"
val_dataset_type: "pointwise"
loss_type: "pointwise_bce"  # "pointwise_bce" or "pointwise_mse"
```

### Grouped Data Loading

The standard format for a grouped dataset. For examples, see [grouped_reranker_train_data_pointwise_label.jsonl](../../../example_data/grouped_reranker_train_data_pointwise_label.jsonl) & [grouped_reranker_train_data_listwise_label.jsonl](../../../example_data/grouped_reranker_train_data_listwise_label.jsonl).

> In the examples, the `pointwise_label` within a group indicates that the supervision signal comes from single-point evaluation, and `listwise_label` indicates that the supervision signal comes from list ranking evaluation, such as RankGPT.

```
{"query": str, "hits": [{"content": str, "label": int|float}, ...]}
```
- `hits` contains all document samples corresponding to the query, and `content` is the actual content of the document.
- `label` is the supervision signal for model fine-tuning and can be of two types:
  - Continuous: A continuous score between 0 and 1.
  - Discrete: Multi-level relevance labels (0/1/2/...).

Two loss functions are supported under this configuration:

**Pairwise RankNet Loss:**
```math
\mathcal{L}_\mathrm{RankNet}= \sum_{i=1}^M\sum_{j=1}^M \mathbb{1}_{r_{i} < r_{j} } \ |r_j-r_i|\ \log(1 + \exp(s_i-s_j))
```

  - $M$ represents the total number of documents under a certain query.
  - $r_i$ represents the relevance label of the $i$-th document, which measures the true relevance of this document to the query.
  - $s_i$ is the score (logit) output by the model after processing the $i$-th document, representing the model's prediction of the relevance of this document.
  - $`\mathbb{1}_{r_i<r_j}`$ is an indicator function. Its meaning is: when the condition $`r_i < r_j`$ holds, i.e., the relevance label of the $`j`$-th document is greater than that of the $i$-th document, $`\mathbb{1}_{r_i<r_j}=1`$; when the condition $`r_i < r_j`$ does not hold, $`\mathbb{1}_{r_i<r_j}=0`$. 
  - $`|r_j-r_i|`$ is weighting coefficient of the document pairs. The greater the difference between the true relevance labels, the more attention will be given.
  
  The mechanism of this loss function is as follows: When the relevance of the $`j`$-th document is higher than that of the $`i`$-th document (i.e., $`r_j > r_i`$), from the perspective of model optimization, we expect $`s_j`$ to be higher than $`s_i`$.
  
  By minimizing the pairwise ranking loss function $\mathcal{L}_\mathrm{RankNet}$, the model will continuously adjust its parameters so that the logit value corresponding to a highly relevant document is as large as possible compared to that of a less relevant document, thereby achieving the goal of reasonably ranking the documents. 

**Listwise Cross Entropy Loss**:

In a normal scenario, that is, when there is only one relevance label $r_i$ equal to 1, and the relevance labels $r_j$ of other documents are all 0, the listwise ranking loss function is the standard listwise loss:
```math
\mathcal{L}_\text{Listwise CE} \Rightarrow \mathcal{L}_\text{listwise}=-\sum_{i=1}^M\mathbb{1}_{r_i=1}\log(\frac{\exp(s_i)}{\sum_j\exp(s_j)})
```

Where, $`\mathbf{1}_{r_i=1}`$ is an indicator function, which means: when $`r_i = 1`$, $`\mathbb{1}_{r_i=1}=1`$; when $`r_i\neq 1`$, $`\mathbb{1}_{r_i=1}=0`$.

Further considering the distillation scenario, that is, $r_i$ is a continuous or discrete value with dense supervision signals. At this time, the listwise ranking loss function is the distillation loss:

```math
\mathcal{L}_\text{Listwise CE}  \Rightarrow \mathcal{L}_\text{distillation} =-\sum_{i=1}^M\frac{\exp(r_i)}{\sum_j\exp(r_j)}\log(\frac{\exp(s_i)}{\sum_j\exp(s_j)})
```

- $\frac{\exp(r_i)}{\sum_j\exp(r_j)}$ calculates the probability distribution of the true relevance labels. It transforms each document's true relevance label through the exponential function and then normalizes it so that the sum of the probabilities of all documents is 1, thus obtaining a probability distribution based on the true labels.
- $\frac{\exp(s_i)}{\sum_j\exp(s_j)}$ is the probability distribution of the model's predicted scores. Similarly, it transforms and normalizes the scores output by the model through the exponential function to obtain a probability distribution based on the model's predictions. 

This loss function calculates the cross-entropy between the probability distribution of the true relevance labels and the probability distribution of the model's predicted scores, and the cross-entropy measures the degree of difference between the two probability distributions: the smaller the cross-entropy value is when the two distributions are closer.

All in all, by minimizing the listwise ranking loss $`\mathcal{L}_\text{Listwise CE}`$, the model will adjust its parameters to make the probability distribution of the model's predicted scores as close as possible to the probability distribution of the true relevance labels, thus achieving a reasonable ranking of the documents. 

✅ Example configuration information is as follows:
```
train_dataset: "../../../example_data/grouped_reranker_train_data_pointwise_label.jsonl"
train_dataset_type: "grouped"
train_group_size: 10
shuffle_rate: 0.0
max_len: 512
val_dataset: "../../../example_data/grouped_reranker_eval_data.jsonl"
val_dataset_type: "grouped"
loss_type: "pairwise_ranknet"  # "pairwise_ranknet" or "listwise_ce"
```
> `train_group_size`, which is `M` in the above formula, refers to the number of documents whose relative relevance needs to be considered simultaneously for each query. If the number of original documents is less than `train_group_size`, repeated sampling will be performed by default to make up the difference.

## Training

Training BERT-based Models with FSDP (DDP)
```bash
CUDA_VISIBLE_DEVICES="0,1" nohup accelerate launch \
--config_file ../../../config/xlmroberta_default_config.yaml \
train_reranker.py \
--config config/training_bert.yaml \
> ./logs/training_bert.log &
```

Training LLM-based Models with DeepSpeed (Only applicable to zero 1-2; zero 3 is not currently compatible due to a bug when saving the model)
```bash
CUDA_VISIBLE_DEVICES="0,1" nohup accelerate launch \
--config_file ../../../config/deepspeed/deepspeed_zero1.yaml \
train_reranker.py \
--config config/training_llm.yaml \
> ./logs/training_llm_deepspeed1.log &
```

## Parameter Explanation

### Multi-GPU Training Configuration Files
- For BERT-based models, FSDP is used by default to support multi-GPU training. Here are examples of configuration files:
  - [default_fsdp](https://github.com/NLPJCL/RAG-Retrieval/blob/master/config/default_fsdp.yaml): Use this configuration file if you want to train a ranking model from scratch based on hfl/chinese-roberta-wwm-ext.
  - [xlmroberta_default_config](https://github.com/NLPJCL/RAG-Retrieval/blob/master/config/xlmroberta_default_config.yaml): Use this configuration file if you want to fine-tune models such as BAAI/bge-reranker-base, maidalun1020/bce-reranker-base_v1, or BAAI/bge-reranker-v2-m3, as they are all trained on the multilingual XLMRoberta.
- For LLM-based models, DeepSpeed is recommended to support multi-GPU training. Currently, only the training phases of zero1 and zero2 are supported. Here are examples of configuration files:
  - [deepspeed_zero1](https://github.com/NLPJCL/RAG-Retrieval/blob/master/config/deepspeed/deepspeed_zero1.yaml)
  - [deepspeed_zero2](https://github.com/NLPJCL/RAG-Retrieval/blob/master/config/deepspeed/deepspeed_zero2.yaml)
- Modifying Multi-GPU Training Configuration Files:
  - Change `CUDA_VISIBLE_DEVICES="0"` in the command to the GPUs you want to use.
  - Modify the `num_processes` parameter in the above-mentioned configuration files to the number of GPUs you want to use.

### Model-related Parameters
- `model_name_or_path`: The name of an open-source reranker model or the local server location where it is downloaded. For example: BAAI/bge-reranker-base, maidalun1020/bce-reranker-base_v1. You can also train from scratch, such as using BERT: hfl/chinese-roberta-wwm-ext or LLM: Qwen/Qwen2.5-1.5B.
- `model_type`: Currently supports bert_encoder or llm_decoder models.
- `max_len`: The maximum input length supported by the data.

### Dataset-related Parameters
- `train_dataset`: The training dataset. See the above for the specific format.
- `val_dataset`: The validation dataset, with the same format as the training dataset (set to `None` if not available).
- `max_label`: The maximum label in the pointwise dataset, defaulting to 1.
- `min_label`: The minimum label in the pointwise dataset, defaulting to 0.

### Training-related Parameters
- `output_dir`: The directory where checkpoints and the final model are saved during training.
- `loss_type`: Choose from `point_ce` (Cross Entropy Loss) and `point_mse` (Mean Squared Error Loss), `pairwise_ranknet` and `listwise_ce`.
- `epoch`: The number of epochs to train the model on the training dataset.
- `lr`: The learning rate, typically between 1e-5 and 5e-5.
- `batch_size`: The number of query-doc pairs in each batch.
- `seed`: Set a unified seed for reproducibility of experimental results.
- `warmup_proportion`: The proportion of learning rate warm-up steps to the total number of model update steps. If set to 0, no learning rate warm-up will be performed, and the learning rate will directly decay cosine-wise from the set `lr`.
- `stable_proportion`: The proportion of steps during which the learning rate remains stable to the total number of model update steps, defaulting to 0.
- `gradient_accumulation_steps`: The number of gradient accumulation steps. The actual batch size of the model is equal to `batch_size` * `gradient_accumulation_steps` * `num_of_GPUs`.
- `mixed_precision`: Whether to perform mixed-precision training to reduce GPU memory requirements. Mixed-precision training optimizes GPU memory usage by using low precision for computation and high precision for parameter updates. Additionally, bf16 (Brain Floating Point 16) can effectively reduce abnormal loss scaling situations, but this type is only supported by some hardware.
- `save_on_epoch_end`: Whether to save the model after each epoch.
- `num_max_checkpoints`: Controls the maximum number of checkpoints saved during a single training session.
- `log_interval`: Record the loss every `x` parameter updates of the model.
- `log_with`: The visualization tool, choose from `wandb` and `tensorboard`.

### Model Parameter-related Parameters
- `num_labels`: The number of logits output by the model, which is the number of classification categories of the model, usually set to 1 by default.
- When using an LLM for discriminative ranking scoring, you need to manually construct the input format, which introduces the following parameters:
  - `query_format`, e.g., "query: {}"
  - `document_format`, e.g., "document: {}"
  - `seq`: Separates the query and document parts, e.g., " "
  - `special_token`: Indicates the end of the document content and guides the model to start scoring. Theoretically, it can be any token, e.g., "\</s>"
  - The overall format is: "query: xxx document: xxx\</s>"

# Loading the Model for Prediction

You can easily load a saved model for prediction.

### Cross-Encoder Model (BERT-like)
```python
ckpt_path = "./bge-reranker-m3-base"
reranker = CrossEncoder.from_pretrained(
    model_name_or_path=ckpt_path,
    num_labels=1,  # binary classification
)
reranker.model.to("cuda:0")
reranker.eval()

input_lst = [
    ["I like China", "I like China"],
    ["I like the United States", "I don't like the United States at all"]
]

res = reranker.compute_score(input_lst)

print(torch.sigmoid(res[0]))
print(torch.sigmoid(res[1]))
```

### LLM-Decoder Model (Based on MLP for Scalar Mapping)

> To meet the special requirements of using an LLM like "Qwen/Qwen2.5-1.5B" for discriminative ranking, a specific format has been designed. The actual effect is: "query: {xxx} document: {xxx}\</s>". Experiments have shown that the introduction of \</s> significantly improves the ranking performance of the LLM [from https://arxiv.org/abs/2411.04539 section 4.3].

```python
ckpt_path = "./Qwen2-1.5B-Instruct"
reranker = LLMDecoder.from_pretrained(
    model_name_or_path=ckpt_path,
    num_labels=1,  # binary classification
    query_format="query: {}",
    document_format="document: {}",
    seq="\n",
    special_token="\nrelevance",
)
reranker.model.to("cuda:0")
reranker.eval()

input_lst = [
    ["I like China", "I like China"],
    ["I like the United States", "I don't like the United States at all"],
]

res = reranker.compute_score(input_lst)

print(torch.sigmoid(res[0]))
print(torch.sigmoid(res[1]))
```
