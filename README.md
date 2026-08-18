# Tesla System · 智能座舱 Agent

多意图车载助手（「小特」）：自然语言控车 + RAG 手册问答 + React 座舱 HMI。  
带 **Gateway 车控、Policy 确认、可观测轨迹** 的 Cabin Runtime。

> GitHub: [Xiangyahaian/tesla_system](https://github.com/Xiangyahaian/tesla_system)

## 能力一览

- **对话控车**：空调 / 座椅 / 媒体 / 导航 / 车窗等 Skills，状态实时回写 HUD
- **安全门控**：高风险操作（如开后备箱）需用户确认后再执行
- **RAG 手册**：Tesla 说明书检索 + 引用，可与车控同轮编排
- **座舱 HMI**：Vite + React 多路由（Drive / Apps / Agent / Setup）
- **地图导航**：高德折线路网、巡航走廊与导航模式
- **语音**：ASR / TTS（可配置百炼等）；支持按住说话

## 架构（简图）

```text
用户语音/文本
    ↓
FastAPI (`python run.py` · 默认 :6006)
    ↓
NLU / Agent Loop ──→ Tools / Skills ──→ Stub Gateway（可换真车机）
    ↓                      ↓
 RAG 手册              vehicle state
    ↓
React Cabin HMI（`frontend/dist` 由后端托管）
```

| 目录 | 说明 |
|------|------|
| `app/` | Runtime：API、Agent、Gateway、NLU、地图、语音 |
| `frontend/` | 座舱 HMI（React + TypeScript + Zustand） |
| `skills/` | 各域 Skill 说明与约定 |
| `context/` / `data/` | RAG 与语料相关 |
| `webui/` | 旧版 HTML UI（`/legacy`） |
| `state/` | 运行时状态（本地，勿提交密钥） |

更细的产品说明见 [`PRODUCT.md`](PRODUCT.md)，演示剧本见 [`DEMO.md`](DEMO.md)。

## 快速开始

### 环境

- Python 3.10+（推荐 conda 环境名 `tesla`）
- Node.js 18+（构建前端）
- 可选：MongoDB（部分数据路径）、本地 vLLM / 云端 LLM Key

```bash
conda activate tesla   # 或自行创建虚拟环境
pip install -r requirements.txt

cp .env.example .env   # 填入 LLM / 地图等密钥
```

### 配置（`.env`）

至少配置一种 LLM（示例见 `.env.example`）：

| 变量 | 用途 |
|------|------|
| `BAILIAN_API_KEY` 等 | 阿里云百炼 / 兼容 OpenAI 的对话与语音 |
| `VLLM_*` | 本地 vLLM |
| `AMAP_MAPS_API_KEY` / `AMAP_JS_KEY` | 高德路径规划与前端地图 |
| `APP_PORT` | 服务端口，默认 `6006` |

**不要**把 `.env`、`.pem`、个人密钥提交进仓库。

### 启动

生产式（后端托管已构建的 HMI）：

```bash
cd frontend && npm install && npm run build && cd ..
python run.py
```

浏览器打开：<http://127.0.0.1:6006>

热更新开发：

```bash
# 终端 1
python run.py

# 终端 2
cd frontend && npm run dev   # 通常 http://127.0.0.1:5173，代理到 6006
```

| 路由 | 说明 |
|------|------|
| `/` | Drive：对话 + 车况中控 |
| `/apps` | 车机应用 |
| `/agent` | Agent 轨迹 / 上下文 |
| `/settings` | 模型、TTS、工具注册表 |
| `/legacy` | 旧 UI |

`PREFER_CABIN_HMI=0` 可强制回退旧 webui。

## 演示建议

约 3–4 分钟剧本见 [`DEMO.md`](DEMO.md)，例如：

1. 「打开空调并播放周杰伦的晴天」→ 多工具 + HUD 变化  
2. 「现在音量多少」→「小一点」→ 指代与状态读写  
3. 「打开后备箱」→ 确认门控  
4. Apps 打开应用后问「自动泊车怎么用」→ RAG 引用  

## 分支说明

| 分支 | 说明 |
|------|------|
| `main` | 稳定 Runtime 基线 |
| `feature/cabin-cockpit` | 座舱 HMI / 导航 / 多路由壳（见 [PR #1](https://github.com/Xiangyahaian/tesla_system/pull/1)） |

## 前端单独说明

见 [`frontend/README.md`](frontend/README.md)。

## License

如无另行声明，仅供学习与演示；第三方依赖（含 `RAG-Retrieval` 等）遵循各自许可证。
