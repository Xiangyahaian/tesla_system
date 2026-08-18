# Cabin HMI（React）

独立前端工程：Vite + React 19 + TypeScript + Zustand + Framer Motion + React Router。

## 页面

| 路由 | 说明 |
|------|------|
| `/` | Drive：声纹球、对话、演示指令、LIVE STATE HUD |
| `/apps` | 车机应用目录，点击走 `apps.launch` |
| `/agent` | Turn 时间线、详情 JSON、Memory preview、Compact |
| `/settings` | 模型/TTS、工具注册表 |
| `/legacy` | 旧 HTML UI |
| `/agent-console` | 旧 Agent HTML Console |

## 设计语言

- 石墨底 + 香槟金点缀，无紫渐变、无霓虹 AI 风
- Instrument Serif + DM Sans
- 状态条 / 侧栏 / 确认门控 三层信息架构

## 开发

```bash
# 终端 1
conda activate tesla && python run.py

# 终端 2
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173 → 代理到 6006
```

## 生产构建（由 FastAPI 托管）

```bash
cd frontend && npm run build
python run.py
# http://127.0.0.1:6006
```

`PREFER_CABIN_HMI=0` 可强制回退旧 webui。
