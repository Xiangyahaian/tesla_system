# Cabin Runtime V2 改动说明

## 怎么启动

```bash
cd /home/xiangyahaian/tesla_system
python run.py
# http://127.0.0.1:6006  （UI 仍为 webui/index.html）
```

## Agent Harness（Claude Code 风格，V2.1）

对齐思路（非逐行抄代码）：

| Claude Code | 本项目 |
|-------------|--------|
| Agentic loop gather→act→verify | `app/agent/loop.py` |
| JSONL transcript | `state/sessions/<id>/transcript.jsonl` |
| CLAUDE.md + auto memory | `state/CABIN.md` + `memory/MEMORY.md` |
| 分层 compact | `app/agent/compact.py`（budget→snip→micro→collapse→auto） |
| Context assembly | `app/agent/context.py` |
| Hooks / permissions | `app/agent/hooks.py` + `app/policy` |

会话目录：

```text
state/sessions/<id>/
  vehicle.json
  transcript.jsonl
  session.json          # slots / pending
  CABIN.md
  memory/MEMORY.md
state/CABIN.md          # 全局持久指令
```

API：`GET /api/agent/context` · `POST /api/agent/compact` · `GET /api/state`（含 agent 摘要）

## 架构变化（核心）

| 旧 (V1) | 新 (V2) |
|---------|---------|
| `main.py` + skills Prompt | `app/` Cabin Runtime |
| 短列表 memory | JSONL transcript + 文件记忆 + 压缩 |
| 无确认门控 | PolicyEngine + 确认 |

**RAG：保持原样**，`app/rag/service.py` 薄封装。

## 回归

```bash
python -m unittest tests.test_vehicle_tools tests.test_fast_path tests.test_agent_harness -v
```
