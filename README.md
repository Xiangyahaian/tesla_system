# Tesla System

智能座舱 Agent：车控与问答一体化，支持多意图理解、工具调用网关、用户手册 RAG，以及 React 座舱 HMI。

仓库地址：[Xiangyahaian/tesla_system](https://github.com/Xiangyahaian/tesla_system)

---

## 功能概览

| 模块 | 说明 |
|------|------|
| 多意图编排 | 规则快路径 + 结构化 NLU；复杂语句走有界 ReAct 循环（≤ 5 步） |
| 车辆工具 | 空调 / 座椅 / 座舱 / 媒体 / 导航 / 智驾，经 JSON Schema 工具与 Gateway 下发 |
| 手册 RAG | PDF 解析 → MongoDB / Milvus；稠密 + 稀疏 + BM25 召回，再精排 |
| 记忆与安全 | 按用户隔离人设 / 记忆 / 偏好；高风险动作经 Policy 门控 |
| 座舱 HMI | Vite + React：驾驶页、应用页、Agent 轨迹、设置；可选 ASR / TTS |

---

## 架构

```text
语音 / 文本
    │
    ▼
FastAPI  （python run.py · 默认 :6006）
    │
    ├─ NLU / Agent 循环 ──► 工具注册表 ──► 车辆 Gateway
    │                              └─► 按用户隔离的车态
    ├─ RAG（手册检索 + 引用）
    ├─ 用户档案记忆（人设 / 记忆 / 偏好）
    └─ 静态托管 frontend/dist
```

| 目录 | 作用 |
|------|------|
| `app/` | 后端运行时：API、编排、NLU、工具、网关、RAG、语音、会话 |
| `frontend/` | 座舱 HMI（React + TypeScript + Zustand） |
| `src/` | RAG 所用的检索 / 精排 / PDF 管线 |
| `data/` | 手册与评测语料（本地索引已 gitignore） |
| `tests/` | 单元测试 |
| `docs/` | 产品、设计、演示与架构文档 |
| `scripts/` | 离线评测工具 |
| `state/` | 运行时状态（仅本地；勿提交密钥与会话库） |

---

## 环境要求

- Python 3.10+（推荐 conda 环境名 `tesla`）
- Node.js 18+（前端构建）
- 可选：MongoDB、Milvus（Lite）、本地 vLLM 或云端 LLM 密钥

```bash
conda activate tesla
pip install -r requirements.txt
cp .env.example .env   # 填写 LLM / 地图等密钥
```

### 关键环境变量

| 变量 | 用途 |
|------|------|
| `BAILIAN_*` | 百炼对话 / 语音（云端） |
| `VLLM_*` | 本地 vLLM 地址与模型名 |
| `AMAP_MAPS_API_KEY` / `AMAP_JS_KEY` | 高德路径规划与前端地图 |
| `APP_PORT` | 服务端口（默认 `6006`） |

请勿将 `.env`、私钥或个人 API Token 提交到 Git。

---

## Docker 部署

面向部署的 Compose 栈（应用 + MongoDB）。模型权重、检索索引与 Mongo 数据在**运行时挂载**，不打进镜像。

```bash
cp .env.example .env    # 填写 API Key 与 VLLM_API_BASE
make up-gpu             # 完整手册 RAG 需安装 NVIDIA Container Toolkit
# 浏览器打开 http://127.0.0.1:6006
```

| 文件 | 用途 |
|------|------|
| `Dockerfile` | 多阶段构建（React HMI + PyTorch CUDA 运行时） |
| `docker-compose.yml` | 应用 + MongoDB |
| `docker-compose.gpu.yml` | 为 RAG 预留 GPU |
| `docs/docker.md` | 完整部署说明（卷挂载、vLLM、排障） |

vLLM 一般**在应用容器外**单独运行；将 `VLLM_API_BASE` 指向宿主机（`host.docker.internal`）或内网 GPU 机器即可。

---

## 快速启动

```bash
cd frontend && npm install && npm run build && cd ..
python run.py
```

打开 <http://127.0.0.1:6006>

| 路由 | 页面 |
|------|------|
| `/` | 驾驶页：对话 + 车辆 / 地图 |
| `/apps` | 车载应用 |
| `/agent` | Agent 轨迹与模型输入输出 |
| `/settings` | 模型、语音、工具注册表 |

前端热更新：

```bash
python run.py                 # 终端 1
cd frontend && npm run dev    # 终端 2（:5173）
```

---

## 设计要点

1. **双路径意图**：短指令走代码快路径；长句 / 多域语句交给 LLM。
2. **观察后再规划**：独立工具可并行；有依赖的步骤使用工具结果；参数错误可纠正。
3. **按用户隔离车态**：一用户一车，状态落在 `state/sessions/<user_id>/`。
4. **三文件用户档案**：人设 / 记忆 / 偏好在回合后落盘，不阻塞语音回复。
5. **安全门控**：结合车速 / 挡位 / 工具风险，拒绝或要求确认。

更多说明见：[docs/product.md](docs/product.md)、[docs/design.md](docs/design.md)、[docs/demo.md](docs/demo.md)。

---

## 测试

```bash
python -m unittest discover -s tests -v
```

---

## 许可

除非另有说明，本仓库仅供学习与演示。第三方组件（含 `RAG-Retrieval`）遵循各自原有许可。
