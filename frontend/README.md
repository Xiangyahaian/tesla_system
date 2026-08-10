# Cabin HMI（React）

智能座舱演示前端：Vite + React + TypeScript + Zustand + Framer Motion。

## 开发

```bash
# 终端 1：后端
conda activate tesla
python run.py

# 终端 2：前端
cd frontend
npm install
npm run dev
# http://127.0.0.1:5173 （API 代理到 6006）
```

## 生产托管（由 FastAPI 提供）

```bash
cd frontend && npm run build
conda activate tesla && python run.py
# http://127.0.0.1:6006 → 座舱 HMI
# http://127.0.0.1:6006/legacy → 旧 webui
```

## 演示亮点

- 按住声纹球：浏览器语音识别 → Agent → TTS 播报
- 右侧 LIVE STATE 与控车结果同步
- 对话内嵌本轮 Agent 轨迹 steps
- 高风险操作确认卡片
- 无紫渐变模板风：石墨底 + 单点香槟金点缀
