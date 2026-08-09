# Data 文件夹结构说明

本文档详细说明 `data/` 文件夹下所有 JSON/PKL 文件的来源、内容和用途。

---

## 目录结构概览

```
data/
├── qa_pairs/           # 问答对数据（原始问题 + RAG生成的结果）
├── summary_data/       # 生成模型训练数据（SFT数据）
├── rerank_data/        # 重排序器训练数据
├── processed_docs/     # 文档处理中间产物
├── saved_index/        # 检索索引文件（BM25/FAISS等）
├── saved_images/       # PDF中提取的图片
├── mongodb/            # MongoDB数据备份
├── ut/                 # 单元测试数据
├── Tesla_Manual.pdf    # 原始PDF文档
└── stopwords.txt       # 中文停用词表
```

---

## 一、qa_pairs/ 文件夹

**用途**：存储问答对数据，包括原始问题和通过RAG流程生成的训练数据

### 1. qa_pair.json / test_qa_pair.json / train_qa_pair.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 人工标注或从PDF自动提取的原始问题 |
| **内容** | 纯问题列表，无答案 |
| **格式** | `[{"question": "Model Y电池多大？"}, ...]` |
| **用途** | RAG流程的输入，用于生成训练数据 |

**示例**：
```json
[
  {"question": "Model Y电池容量多大？"},
  {"question": "Model 3充电需要多久？"}
]
```

### 2. expand_qa_pair.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 通过Query Expansion（查询扩展）生成的扩展问题 |
| **内容** | 原始问题 + 扩展变体问题 |
| **用途** | 增加训练数据多样性，提升模型泛化能力 |

### 3. train_data.json / test_data.json ⭐重要

| 属性 | 说明 |
|:---:|:---|
| **来源** | `generate_sft_data.py` 脚本 **自动生成** |
| **内容** | 完整的RAG链路结果（问题→召回→精排→生成答案）|
| **用途** | 生成后续训练数据的**原材料** |

**格式说明**（每行一个JSON对象）：
```json
{
  "query": "Model Y电池容量多大？",
  "context": [
    "Model Y配备78.4kWh电池...",
    "Model Y续航可达525公里...",
    "..."
  ],
  "response": "Model Y配备78.4kWh三元锂电池【1】",
  "merged_docs": [
    "Model Y配备78.4kWh电池...",
    "Model 3充电接口...",
    "..."
  ]
}
```

**字段解释**：
| 字段 | 说明 |
|:---:|:---|
| `query` | 用户问题 |
| `context` | Reranker精排后的 **Top5 文档**（用于生成答案）|
| `response` | 大模型生成的答案（带引用编号如【1】）|
| `merged_docs` | 召回阶段的所有候选文档（BM25+Milvus合并去重）|

**生成流程**：
```
train_qa_pair.json
      │
      ▼
BM25召回Top5 ──┐
               ├──→ merge_docs ──→ Qwen3-Reranker精排Top5 ──→ 大模型生成答案
train_data.json
```

### 4. test_qa_pair_pred.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 模型推理结果 |
| **内容** | 测试集问题 + 模型预测答案 |
| **用途** | 评估模型性能（与标准答案对比）|

### 5. test_qa_pair_verify.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 人工验证后的测试集 |
| **内容** | 经过人工检查和修正的问答对 |
| **用途** | 作为金标准（Gold Standard）评估模型 |

### 6. test_keywords_pair.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 关键词形式的测试查询 |
| **内容** | 提取的关键词组合而非完整问题 |
| **用途** | 测试检索系统对关键词的召回能力 |

---

## 二、summary_data/ 文件夹 ⭐重要

**用途**：**生成模型（Qwen3-8B）的 SFT 训练数据**

### train.json / test.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 从 `qa_pairs/train_data.json` **自动转换** |
| **生成脚本** | `generate_sft_data.py` 中的 `generate_summary_data()` |
| **格式** | **Alpaca 格式**（instruction + input + output）|
| **用途** | **Qwen3-8B LoRA 微调** |

**格式示例**：
```json
{
  "query": "Model Y电池容量多大？",
  "context": "1. Model Y配备78.4kWh电池...\n2. Model Y续航525公里...",
  "instruction": "### 信息\n1. Model Y配备78.4kWh电池...\n\n### 任务\n你是特斯拉电动汽车Model 3车型的用户手册问答系统...",
  "input": "",
  "output": "Model Y配备78.4kWh三元锂电池【1】"
}
```

**字段说明**：
| 字段 | 说明 |
|:---:|:---|
| `query` | 原始问题 |
| `context` | 带编号的参考文档（Top5）|
| `instruction` | 完整的System Prompt + 上下文 |
| `input` | 用户输入（此处为空，问题在instruction中）|
| `output` | 期望的模型输出（带引用标记的答案）|

**数据划分**：
- `train.json`: 约 92% 数据用于训练
- `test.json`: 约 8% 数据用于测试

---

## 三、rerank_data/ 文件夹 ⭐重要

**用途**：**重排序器（Qwen3-Reranker）的训练数据**

### train.json / dev.json / test.json

| 属性 | 说明 |
|:---:|:---|
| **来源** | 从 `qa_pairs/train_data.json` **自动转换** |
| **生成脚本** | `generate_sft_data.py` 中的 `generate_rerank_data()` |
| **格式** | 三元组（query, content, label）|
| **用途** | **Qwen3-Reranker 微调**（三分类任务）|

**格式示例**：
```json
// train.json - 单文档样本
{"query": "Model Y电池容量多大？", "content": "Model Y配备78.4kWh电池...", "label": 2}
{"query": "Model Y电池容量多大？", "content": "Model Y续航可达525公里...", "label": 1}
{"query": "Model Y电池容量多大？", "content": "Model 3充电接口位于...", "label": 0}

// test.json - 列表格式（每个查询3篇文档）
{
  "query": "Model Y电池容量多大？",
  "content": [
    "Model Y配备78.4kWh电池...",  // 高度相关
    "Model Y续航可达525公里...",  // 中等相关
    "Model 3充电接口位于..."      // 不相关
  ]
}
```

**标签定义**：
| label | 含义 | 来源 |
|:---:|:---:|:---|
| **2** | 高度相关 | Reranker Top1 文档（被引用）|
| **1** | 中等相关 | Reranker Top4-5 文档 |
| **0** | 不相关 | 召回但未进 Top5 的文档 |

**数据划分**：
- `train.json`: 训练集（大部分数据）
- `dev.json`: 验证集（最后1000条）
- `test.json`: 测试集（每个查询3篇文档，用于评估排序能力）

---

## 四、processed_docs/ 文件夹

**用途**：PDF文档处理过程中的中间产物

### 1. raw_docs.pkl / raw_docs.md

| 属性 | 说明 |
|:---:|:---|
| **来源** | `pdf_parse.py` 解析PDF后的原始文档 |
| **内容** | 未经清洗的原始文本块 |
| **格式** | Python pickle / Markdown |
| **用途** | 保留原始解析结果，方便调试 |

### 2. clean_docs.pkl / clean_docs.md

| 属性 | 说明 |
|:---:|:---|
| **来源** | `pdf_parse.py` 清洗后的文档 |
| **内容** | 去除噪声（页眉页脚、特殊字符）后的文档 |
| **用途** | 作为文本切分的输入 |

### 3. split_docs.pkl / split_docs.md

| 属性 | 说明 |
|:---:|:---|
| **来源** | `texts_split()` 切分后的最终文档 |
| **内容** | 经过语义切分 + 递归字符切分后的文档块 |
| **用途** | **构建索引的输入**（BM25、Milvus、FAISS）|

**切分流程**：
```
raw_docs.pkl
      │
      ▼ 清洗
 clean_docs.pkl
      │
      ▼ 语义切分 + 递归切分
 split_docs.pkl ──→ 存入 Milvus / BM25 / FAISS
```

---

## 五、saved_index/ 文件夹

**用途**：存储构建好的检索索引（二进制文件）

| 文件 | 说明 |
|:---:|:---|
| `bm25retriever.pkl` | BM25 关键词索引（jieba分词 + 停用词过滤）|
| `faiss.db/` | FAISS 向量索引（HuggingFace BCE-Embedding）|
| `tfidf.pkl` | TF-IDF 索引（备选检索方案）|

**注意**：Milvus 是独立数据库服务，索引存储在 MongoDB 中，不在此文件夹。

---

## 六、其他文件

### stopwords.txt

| 属性 | 说明 |
|:---:|:---|
| **来源** | 标准中文停用词表 |
| **用途** | BM25 分词时过滤无意义词汇（"的"、"了"、"是"等）|
| **使用位置** | `bm25_retriever.py` |

### saved_images/

| 属性 | 说明 |
|:---:|:---|
| **来源** | `pdf_parse.py` 从PDF提取的图片 |
| **命名规则** | `img_{page}_{idx}.png` |
| **用途** | 与文本关联，支持多模态问答 |

---

## 七、数据流转总图

```
                                    人工标注/提取
                                         │
                                         ▼
                           ┌─────────────────────────────┐
                           │  qa_pairs/train_qa_pair.json │
                           │  (原始问题列表)               │
                           └──────────────┬──────────────┘
                                          │
              ┌───────────────────────────┼───────────────────────────┐
              │                           │                           │
              ▼                           ▼                           ▼
    ┌─────────────────┐        ┌─────────────────┐        ┌─────────────────┐
    │ BM25 召回 Top5  │        │ Milvus 召回 Top10│        │  Query Expansion │
    └────────┬────────┘        └────────┬────────┘        └────────┬────────┘
             │                          │                          │
             └────────────────────┬─────┘                          │
                                  ▼                                ▼
                        ┌─────────────────┐            ┌─────────────────────┐
                        │  merge_docs()   │            │ expand_qa_pair.json │
                        │  (合并去重)      │            │ (扩展问题)           │
                        └────────┬────────┘            └─────────────────────┘
                                 │
                                 ▼
                      ┌───────────────────────┐
                      │ Qwen3-4B-Reranker 精排 │
                      │ (判断文档相关性)        │
                      └───────────┬───────────┘
                                  │
                                  ▼
                    ┌─────────────────────────────┐
                    │ 大模型生成答案 (带引用标记)   │
                    │ request_chat()              │
                    └──────────────┬──────────────┘
                                   │
                                   ▼
                    ┌─────────────────────────────┐
                    │ qa_pairs/train_data.json    │  ◄── 中间产物
                    │ (原始RAG结果)                │      (问题+文档+答案)
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
    ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
    │ summary_data/   │  │  rerank_data/   │  │  模型评估        │
    │                 │  │                 │  │                 │
    │  train.json     │  │  train.json     │  │  test_qa_pair_  │
    │  test.json      │  │  dev.json       │  │  pred.json      │
    │  (Alpaca格式)   │  │  test.json      │  │                 │
    │                 │  │  (3分类标签)    │  │                 │
    └────────┬────────┘  └────────┬────────┘  └─────────────────┘
             │                    │
             ▼                    ▼
    ┌─────────────────┐  ┌─────────────────┐
    │ Qwen3-8B LoRA  │  │ Qwen3-Reranker  │
    │   SFT 微调      │  │   微调          │
    │                 │  │                 │
    │ 生成答案模型    │  │  精排模型        │
    └─────────────────┘  └─────────────────┘
```

---

## 八、快速参考表

| 文件路径 | 类型 | 用途 | 生成方式 |
|:---:|:---:|:---:|:---:|
| `qa_pairs/train_qa_pair.json` | 输入 | 原始问题列表 | 人工/自动提取 |
| `qa_pairs/train_data.json` | 中间产物 | RAG完整链路结果 | `generate_sft_data.py` 自动生成 |
| `summary_data/train.json` | 训练数据 | Qwen3-8B SFT | 从 train_data.json 转换 |
| `rerank_data/train.json` | 训练数据 | Qwen3-Reranker | 从 train_data.json 转换 |
| `processed_docs/split_docs.pkl` | 中间产物 | 切分后的文档块 | `pdf_parse.py` 生成 |
| `saved_index/bm25retriever.pkl` | 索引 | BM25检索索引 | `build_index.py` 生成 |

---

## 附：重要脚本对应关系

| 脚本 | 输入 | 输出 |
|:---:|:---:|:---:|
| `pdf_parse.py` | `Tesla_Manual.pdf` | `processed_docs/*.pkl` |
| `build_index.py` | `split_docs.pkl` | `saved_index/*` + Milvus |
| `generate_sft_data.py` | `train_qa_pair.json` | `train_data.json` + `summary_data/*` + `rerank_data/*` |
| `infer.py` | 用户问题 | 模型回答 |

---

*文档生成时间：2026-03-14*
