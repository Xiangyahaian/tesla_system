# Tesla System

基于多意图识别的智能座舱问答与控车系统。面向车载口语场景，统一处理手册问答、指令执行、车况查询与闲聊，并提供可演示的 React 座舱 HMI。

仓库地址：[Xiangyahaian/tesla_system](https://github.com/Xiangyahaian/tesla_system)

---

## 系统概览

| 能力 | 说明 |
|------|------|
| 多意图编排 | 规则快路径 + Structured NLU；复杂句走 ReAct 多步规划（最多 5 步） |
| 工具控车 | 气候 / 座椅 / 舱体 / 媒体 / 导航 / ADAS 等 JSON Schema 工具，经 Gateway 回写车况 |
| 手册 RAG | PyMuPDF 解析 + MongoDB / Milvus；稠密+稀疏+BM25 多路召回，Rerank 精排 |
| 记忆与安全 | 每用户 persona / memories / preferences 三文件；高风险操作 Policy 确认 |
| 座舱 HMI | Vite + React：驾驶页、应用、Agent 轨迹、设置；语音 ASR / TTS 可选 |

---

## 架构

```text
语音 / 文本
    │
    ▼
FastAPI  (python run.py · 默认 :6006)
    │
    ├─ NLU / Agent Loop ──► Tool Registry ──► Vehicle Gateway
    │                              │
    │                              └─► vehicle.json（按用户隔离）
    ├─ RAG（手册检索 + 引用）
    ├─ 记忆落盘（persona / memories / preferences）
    └─ 静态托管 frontend/dist
```

| 路径 | 说明 |
|------|------|
| `app/` | 后端 Runtime：API、编排、NLU、工具、Gateway、RAG、语音、会话 |
| `frontend/` | 座舱 HMI（React + TypeScript + Zustand） |
| `data/` | 手册与评测语料（本地索引 / Mongo 数据默认不入库） |
| `tests/` / `test/` | 单元测试与压测用例 |
| `docs/` | 规则目录等补充文档 |
| `state/` | 运行时状态（本地生成，勿提交密钥与会话库） |

---

## 环境要求

- Python 3.10+（推荐 conda 环境 `tesla`）
- Node.js 18+（构建前端）
- 可选：MongoDB、Milvus（Lite）、本地 vLLM 或云端 LLM Key

```bash
conda activate tesla
pip install -r requirements.txt
cp .env.example .env   # 填入 LLM / 地图等配置
```

### 关键配置（`.env`）

| 变量 | 用途 |
|------|------|
| `BAILIAN_*` | 阿里云百炼对话 / 语音（远程模型） |
| `VLLM_*` | 本地 vLLM 端点与模型名 |
| `AMAP_MAPS_API_KEY` / `AMAP_JS_KEY` | 高德路径规划与前端地图 |
| `APP_PORT` | 服务端口，默认 `6006` |

请勿将 `.env`、私钥或个人 API Key 提交到仓库。

---

## 启动

```bash
# 构建座舱前端（首次或前端变更后）
cd frontend && npm install && npm run build && cd ..

# 启动后端（托管 frontend/dist）
python run.py
```

浏览器访问：<http://127.0.0.1:6006>

前端热更新开发：

```bash
python run.py                 # 终端 1
cd frontend && npm run dev    # 终端 2，通常 :5173
```

| 路由 | 说明 |
|------|------|
| `/` | 驾驶页：对话 + 车况 / 地图 |
| `/apps` | 车机应用 |
| `/agent` | Agent 轨迹与本轮模型输入 |
| `/settings` | 模型、语音、工具等设置 |

---

## 设计要点（摘要）

1. **意图双通道**：短指令可走代码快路径；超长 / 多域复合句交给 LLM，避免误解析。
2. **观察后再规划**：无依赖工具可并行；有依赖按返回结果拆步，失败可纠参。
3. **用户级车况隔离**：一用户一辆车（`state/sessions/<user_id>/`），会话间共享车况、分开 transcript。
4. **画像三文件**：人设 / 身份记忆 / 偏好语义改写落盘；轮末更新不阻塞口语回复。
5. **安全门控**：结合车速、挡位与工具风险等级，拒绝或二次确认。

更细的产品约定见 [`PRODUCT.md`](PRODUCT.md)，演示剧本见 [`DEMO.md`](DEMO.md)。

---

## 测试

```bash
python -m unittest discover -s tests -v
```

压测用例与脚本位于 `test/`（需本地或远程模型可用）。

---

## License

如无另行声明，本仓库仅供学习与演示。第三方依赖（含 `RAG-Retrieval` 等）遵循各自许可证。
