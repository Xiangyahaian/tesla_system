# Docker 部署指南

本文档说明如何使用 Docker / Docker Compose **规范部署** Tesla System 智能座舱后端与 HMI。

> **架构说明**：应用容器内运行 FastAPI + Milvus Lite + RAG 检索栈；MongoDB 由 Compose 提供；**vLLM 大模型推理服务通常独立部署**（宿主机 GPU 或另一台机器），通过 `VLLM_API_BASE` 连接。

---

## 1. 前置条件

| 项目 | 要求 |
|------|------|
| Docker | Engine 24+，Compose v2（`docker compose`） |
| GPU（完整 RAG） | NVIDIA 驱动 + [NVIDIA Container Toolkit](https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/install-guide.html) |
| 磁盘 | 镜像 ~8GB；另需挂载 `models/`（约 8GB+）与索引 |
| 网络 | 容器需能访问 vLLM 端点（本机或内网） |

### 运行时数据（不打包进镜像）

以下路径需在宿主机准备并通过卷挂载：

| 宿主机路径 | 容器路径 | 说明 |
|-----------|---------|------|
| `./models/BAAI/bge-m3` | `/app/models/BAAI/bge-m3` | Milvus 稠密/稀疏向量 embedding |
| `./RAG-Retrieval/.../checkpoint_0` | 同结构 | 微调 reranker 权重（约 2.2GB） |
| `./data/saved_index/` | `/app/data/saved_index` | `bm25retriever.pkl`、`milvus.db` 等 |
| `./data/saved_images/` | `/app/data/saved_images` | 手册插图（可选只读） |
| MongoDB 数据 | `mongodb` 服务 | 含 `manual_text` 集合；可 bind `./data/mongodb/data` |

模型与索引体积大，已在 `.gitignore` 中排除，**需从本地训练/构建环境或发布包拷贝**。

---

## 2. 快速开始

```bash
git clone https://github.com/Xiangyahaian/tesla_system.git
cd tesla_system

# 1) 配置环境变量
cp .env.example .env
# 编辑 .env：填入 BAILIAN_API_KEY、AMAP_*、VLLM_API_BASE 等

# 2) 准备挂载目录（从已有环境复制）
#    models/、data/saved_index/、RAG-Retrieval/.../checkpoint_0/

# 3) 启动（含 MongoDB）
make up-gpu
# 或：
# docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build

# 4) 验证
curl -s http://127.0.0.1:6006/api/model-status | python -m json.tool
```

浏览器访问：<http://127.0.0.1:6006>

---

## 3. Compose 服务

| 服务 | 镜像 | 端口 | 作用 |
|------|------|------|------|
| `app` | 本地构建 `tesla-system:latest` | `6006` | FastAPI、Agent、RAG、静态 HMI |
| `mongodb` | `mongo:7.0` | `27017` | 手册文本 `manual_text` 等 |

### 环境变量（`.env`）

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_PUBLISH_PORT` | `6006` | 宿主机映射端口 |
| `MONGO_HOST` | （Compose 内固定 `mongodb`） | 勿在容器内改为 localhost |
| `MONGO_DB_NAME` | `mydatabase` | 与本地开发一致 |
| `VLLM_API_BASE` | `http://host.docker.internal:8000/v1` | 指向宿主机 vLLM |
| `VLLM_MODEL_NAME` | `qwen-4b-tesla` | 与 vLLM `--served-model-name` 一致 |
| `BAILIAN_API_KEY` | — | 云端 LLM / 语音（可选） |
| `AMAP_MAPS_API_KEY` | — | 高德路径规划 |
| `RAG_ENABLE` | `1` | 设为 `0` 可跳过 RAG 预热（无 GPU 演示） |
| `RAG_WARMUP_ON_STARTUP` | `1` | 启动时加载检索栈 |

完整列表见 [.env.example](../.env.example)。

### 卷挂载变量（高级）

在 `.env` 中可覆盖宿主机路径：

```bash
MODELS_DIR=./models
SAVED_INDEX_DIR=./data/saved_index
RERANKER_CHECKPOINT_DIR=./RAG-Retrieval/rag_retrieval/train/reranker/output/bert/runs/checkpoints/checkpoint_0
```

---

## 4. GPU 与 CPU 模式

### 完整功能（推荐）

手册 RAG 的 embedding 与 reranker **硬依赖 CUDA**（代码路径 `device="cuda"`）。

```bash
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up -d --build
```

验证 GPU：

```bash
docker compose exec app python -c "import torch; print('cuda:', torch.cuda.is_available())"
```

### 仅演示 Agent / 云端 LLM（无 GPU）

```bash
# .env
RAG_ENABLE=0
RAG_WARMUP_ON_STARTUP=0
```

此时无需 `docker-compose.gpu.yml`，但**无法使用手册 RAG 检索**。

---

## 5. 连接宿主机 vLLM

vLLM 一般不在本仓库镜像内运行。WSL2 / Linux 下 Compose 已配置：

```yaml
extra_hosts:
  - "host.docker.internal:host-gateway"
```

`.env` 示例：

```bash
# vLLM 跑在宿主机 8000
VLLM_API_BASE=http://host.docker.internal:8000/v1

# vLLM 跑在内网另一台机器
VLLM_API_BASE=http://192.168.1.100:8000/v1
```

确保 vLLM 监听 `0.0.0.0:8000`，且防火墙放行。

---

## 6. MongoDB 数据

### 方式 A：绑定已有 WiredTiger 目录

编辑 `docker-compose.yml`，将 MongoDB 卷改为：

```yaml
volumes:
  - ./data/mongodb/data:/data/db
```

### 方式 B：空库 + 导入

首次使用 named volume 时库为空，需自行导入 `manual_text`（例如从开发环境 `mongodump` / `mongorestore`）。

连接串（容器内）：`mongodb://mongodb:27017/mydatabase`

---

## 7. 运维命令

```bash
make logs          # 跟踪 app 日志
make ps            # 服务状态
make down          # 停止并删除容器（保留 named volumes）
make shell         # 进入 app 容器

# 重建镜像
docker compose build --no-cache app
docker compose up -d app
```

### 健康检查

- 容器 `HEALTHCHECK`：`GET /api/model-status`
- 启动宽限期 180s（RAG 模型加载较慢）

### 常见问题

| 现象 | 处理 |
|------|------|
| `Open local milvus failed` / db lock | 确保**仅一个** app 实例挂载同一 `milvus.db` |
| RAG warmup CUDA error | 使用 `docker-compose.gpu.yml` 或 `RAG_ENABLE=0` |
| MongoDB connection refused | 等待 `mongodb` healthy；检查 `MONGO_HOST=mongodb` |
| vLLM unreachable | 检查 `VLLM_API_BASE`、宿主机防火墙、vLLM 是否 `--host 0.0.0.0` |
| 缺少 bm25/milvus/models | 按第 1 节准备挂载目录 |

---

## 8. 镜像说明

- **多阶段构建**：Node 20 构建 `frontend/dist`，PyTorch CUDA runtime 运行 Python
- **非 root**：容器内用户 `tesla` (uid 1000)
- **init**：`tini` + `docker/entrypoint.sh`（等待 MongoDB、启动前检查）
- **不包含**：模型权重、Milvus/BM25 索引、Mongo 数据、`.env` 密钥

---

## 9. 生产建议（checklist）

- [ ] 使用私有镜像仓库 tag 版本号，避免仅 `latest`
- [ ] `.env` 权限 `600`，勿提交 Git
- [ ] 前置反向代理（TLS、限流、WAF）
- [ ] 内网部署 vLLM；勿将 `:6006` 直接暴露公网（见上线审查文档）
- [ ] 定期备份 `tesla_state`、`mongodb_data`、`data/saved_index`
- [ ] 监控 `/api/model-status` 与容器 health

---

## 10. 相关文件

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 镜像定义 |
| `docker-compose.yml` | 默认栈（app + mongodb） |
| `docker-compose.gpu.yml` | GPU 覆盖 |
| `.dockerignore` | 构建上下文排除 |
| `Makefile` | 常用命令封装 |
| `docker/entrypoint.sh` | 启动脚本 |
