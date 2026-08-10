# Cabin · 智能座舱演示

## 一键启动

```bash
conda activate tesla
cd frontend && npm run build && cd ..
python run.py
```

打开 http://127.0.0.1:6006

- Drive `/` · Apps `/apps` · Agent `/agent` · Setup `/settings`
- 旧 UI `/legacy` · 旧轨迹页 `/agent-console`

## 开发热更新

```bash
# 终端 1
conda activate tesla && python run.py

# 终端 2
cd frontend && npm run dev
```

## Demo 剧本

见 `DEMO.md`。
