# Agent 上下文动态加载规范（Context Dynamic Loading）

> 目标：按意图/步骤**按需装载**上下文与工具说明，禁止「每句问候都带全家桶」。  
> 现状痛点：NLU 一次 `prompt_tokens≈11k`（工具全目录 + `polyline` 全量 + 曲库全表），输出仅几十 token。

---

## 1. 「动态加载」在本项目里的定义

**动态加载 ≠ 运行时 import 模块。**  
指：每一轮 LLM 调用之前，根据 **阶段（stage）+ 意图线索（cues）+ 已观察结果（observations）**，从完整状态里**裁剪并注入**最小必要切片。

| 静态塞满（禁止） | 动态加载（要求） |
|---|---|
| 每次带全部工具 schema | 先粗分域，再加载该域工具说明 |
| 每次带完整 `navigation.polyline` | 折线永不进 LLM；地图自己用 |
| 每次带 `media.library` / 电台全表 | 仅「放歌/搜歌」时加载候选子集 |
| 闲聊也带整车 JSON | 寒暄短路或只带 1 行定位名 |
| CABIN + MEMORY 全文每轮 | 按路径降级：摘要 / 全文 / 不注入 |

原则一句话：**模型只看见「这一步决策所必需」的信息；其余留在 Gateway / 前端 / 工具实现里。**

---

## 2. 调用分层（Stage）

每轮用户话按阶段装载，不得跳过预算检查。

```text
Stage-0  规则快路径（0 LLM）
   ↓ 未命中
Stage-1  路由/门控（小上下文 LLM 或规则）
   ↓ 得到 intent 或 domain
Stage-2  规划/执行（按域加载工具 + 状态切片）
   ↓
Stage-3  口述包装（仅工具摘要，禁止再塞全车 JSON）
```

### Stage-0（必须优先）

命中则**不调用 LLM**，直接工具或固定话术，例如：

- 寒暄：`你好` / `在吗` / `谢谢`
- 明确状态问句：已有 `try_status_utterance` 等 fast-path
- 导航候选选择：`第一个` / 候选简称

**验收**：`你好` 的 `prompt_tokens` 应为 0（无 LLM）或 &lt; 500（仅极简门控）。

### Stage-1（路由）

输入上限建议：**≤ 1.5k tokens**。

允许注入：

- 极简意图说明（无完整工具目录，最多「域列表」：climate/media/nav/maps/cabin/…）
- `memory_hint`（已有，≤900 字）
- 车况 **micro**：`{position.name, navigating, music.title?, climate.power?}` 级

禁止注入：

- `polyline` / `steps` / `library` / `radio_stations` / 全量 zones 细表（除非路由已判定 climate）
- 完整 CABIN.md

输出：`intent` + 可选 `domains[]`（如 `["navigation","maps"]`）。

### Stage-2（规划 / AgentLoop 每步）

输入上限建议：

| 情形 | 建议上限 |
|---|---|
| 单域 tool | ≤ 3k |
| multi_tool / 第二步观察后 | ≤ 4k |
| 硬顶（超过则强制再裁） | 6k |

按 `domains` **动态加载**：

1. **工具目录**：仅该域（及强相关域）的 `prompt_catalog(domains=...)`
2. **车况切片**：`slim_vehicle_for_stage(state, domains, query, observations)`
3. **观察**：已执行工具结果（保持短 stub，长 POI 只留 name/distance 前 N 条）

### Stage-3（口语包装）

输入上限建议：**≤ 1k**。  
只给：用户原话 + 工具结果摘要（已有 `TOOL_WRAP_STYLE` 路径）。  
禁止：CABIN 全文、车况 JSON、工具目录。

---

## 3. 上下文资产分级

| 资产 | 代号 | 默认 | 动态加载规则 |
|---|---|---|---|
| 人设短指令 | `SYSTEM_CORE` / `CHAT_STYLE` 等 | 按路径带对应 Style | 寒暄可用 2～3 句极简人设 |
| 工具目录 | `tool_catalog` | **不默认全量** | 按 `domains` 加载；未知域才回退「域索引」 |
| 车况 | `vehicle_slice` | micro | 按 query/domain 升到 standard；永不含 polyline |
| 导航折线 | `polyline` | **永不进 LLM** | 仅 Gateway / 地图 / 背景渲染 |
| 导航步骤 | `steps` | 默认无 | 仅「下个路口怎么走」类再加载当前/下一步 |
| 曲库/电台表 | `library` | 默认无 | 播放/搜索时加载 topK 或匹配命中 |
| CABIN.md | `cabin` | CHAT/SEARCH 可摘要 | 全文仅 Agent 调试或显式需要；日常 ≤1k 字摘要 |
| MEMORY / prefs | `memory` | 短块 | 保持现有 preferences 短格式；禁止重复粘贴两遍 |
| transcript | `history` | hint 8 条 | 已截断；工具内容进 hint 再压到 80 字 |
| RAG 手册 | `rag` | 仅 KNOWLEDGE | 保持现有；与车控上下文隔离 |
| Compaction | `compact` | 有则带 ≤200 字 | 不变 |

---

## 4. 车况切片规范（Vehicle Slice）

统一入口（建议）：`app/agent/context.py`

```text
micro(state)           → 定位名 + navigating + 正在播歌曲名（可选）
standard(state, domains, query)  → 复用/加强 slim_vehicle_for_query
never: polyline, steps全文, library, radio_stations, installed应用长列表可缩成 count
```

**硬规则（验收必查）：**

1. 任何 `llm.chat` / `chat_stream` 的 messages 中，不得出现 `"polyline"` 键。  
2. NLU `plan()` 不得再 `vehicle_state.get("media")` / `get("navigation")` 原样 dumps。  
3. `gateway.snapshot()` 可继续给前端全量；**进模型前必须再 slim**。

已有能力：

- `_slim_vehicle` / `_slim_navigation` / `slim_vehicle_for_query`（SEARCH 在用）  
- **缺口**：`StructuredNLU.plan` 未走上述 slim → 本规范要求立刻对齐。

---

## 5. 工具目录动态加载（Tool Catalog）

文件：`app/tools/registry.py`

建议 API：

```text
prompt_catalog(domains: list[str] | None = None, *, max_chars: int = 3500) -> str
domain_index() -> str   # 仅域名 + 一句话，供 Stage-1
```

域划分示例：

| domain | 工具前缀/名 |
|---|---|
| climate | `climate.*` |
| seat | `seat.*` |
| media | `media.*` |
| navigation | `navigation.*` |
| maps | `maps.*` |
| cabin | `cabin.*` |
| driving | `driving.*` |
| apps | `apps.*` |
| connectivity | `connectivity.*` |
| notifications | `notifications.*` |
| assistant | `assistant.*` |

Stage-1 只给 `domain_index()`；Stage-2 用路由结果的 `domains` 调 `prompt_catalog(domains)`。  
若模型输出未注册工具名 → 下一轮可「补载该域 catalog」再规划一次（仍禁止全量）。

---

## 6. 路径 × 装载矩阵

| 路径 | Stage-0/1 | 工具目录 | 车况 | CABIN/MEMORY | 历史 |
|---|---|---|---|---|---|
| 寒暄 | Stage-0 固定回复 | 无 | 无或 micro | 无 | 无或 1 条 |
| SEARCH | 可 fast-path | 无 | `slim_vehicle_for_query` | Style 短 + 可选摘要 | recent 短 |
| CHAT | 门控后 | 无 | micro（问位置可加 position） | CHAT_STYLE + 摘要 CABIN | recent |
| TOOL / Loop | 路由后 | **按域** | standard 按域 | 无（NLU 不带 CABIN） | hint + 观察 |
| KNOWLEDGE | — | 无 | 无 | 无 | 无；改 RAG |
| TOOL_WRAP | — | 无 | 无 | 无 | 无 |

---

## 7. Token 预算与观测

| 调用类型 | prompt 软预算 | prompt 硬顶 | completion 预期 |
|---|---|---|---|
| Stage-0 | 0 | 0 | 0 |
| Stage-1 路由 | 1.5k | 2.5k | ≤150 |
| Stage-2 NLU/步 | 3～4k | 6k | ≤400 |
| Stage-3 包装 | 1k | 1.5k | ≤200 |
| SEARCH/CHAT 回复 | 2～3k | 5k | ≤300 |

**日志（模型端 / 本地）每条调用必须能回答：**

- `stage` / `domains` / `prompt_tokens` / `completion_tokens`
- `injected`: `catalog_domains`, `vehicle_keys`, `has_polyline`（应为 false）

回归用例（必须）：

1. `你好` → 无 NLU 全量 catalog；总 prompt≪1k 或 0 LLM  
2. `我现在在哪里` → NLU/SEARCH **不含 polyline**；prompt 建议 &lt;3k  
3. `导航到最近的充电站` → 允许 2～3 次 LLM，但每次 catalog 仅 maps/navigation（+apps），仍无 polyline  

---

## 8. 实施顺序（建议）

### P0（立刻，收益最大）

1. NLU `plan()` 改用 `_slim_vehicle` / `slim_vehicle_for_query`，**剥离 polyline/library**。  
2. `memory_hint` 去掉重复粘贴的两份 preferences。  
3. 寒暄 Stage-0 短路。

### P1

4. `prompt_catalog(domains=...)` + Stage-1 域路由。  
5. CHAT/SEARCH 的 CABIN 改为摘要版（或截断 800～1200 字）。  

### P2

6. 观察结果结构化短表；AgentLoop 第二步只带相关 POI top3。  
7. 预算中间件：组装后 `estimate_tokens`，超硬顶自动再裁并打 warn 日志。  

---

## 9. 非目标（本规范不做）

- 不把折线「摘要进模型」来画路（折线留给前端/背景 Canvas）。  
- 不改为单次超长 Cosine 记忆检索替代 transcript（可后续另案）。  
- 不降低控车正确性：分区空调/座位等**该留的字段必须留**，只删无关大块。

---

## 10. 验收口令

> 「动态加载」落地的标志：  
> **问位置不再吞下整条 polyline；打招呼不再加载四十个工具；每一次 LLM 调用都能说出自己加载了哪些 domain / 哪些 vehicle keys。**

---

文档版本：v1 · 对应代码热点：`app/nlu/planner.py`、`app/agent/context.py`、`app/tools/registry.py`、`app/orchestrator/runtime.py`、`app/nlu/fast_path.py`
