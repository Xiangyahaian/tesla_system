# 人设 · 记忆 · 偏好 — 面试口述稿（从头到尾）

> 面向智能座舱 Agent 项目。用「小特」助手举例，三样东西**分开存、分开用、分开更新**。

---

## 一、先用一句话说清楚三者

| 概念 | 文件 | 一句话 |
|------|------|--------|
| **人设 persona** | `persona.json` | **助手怎么说话**（温柔/专业/简洁），不是用户是谁 |
| **身份记忆 memories** | `memories.json` | **用户是谁**（家住哪、女儿叫什么、公司在哪） |
| **行为偏好 preferences** | `preferences.json` | **车机默认怎么伺候用户**（常坐哪、默认几度、叫啥、听啥歌） |

**记忆口诀**：人设改「小特的嘴」，记忆记「用户的事」，偏好记「车的默认档」。

---

## 二、为什么要拆成三个文件？

1. **语义不同**：「我家在国贸」是事实；「以后空调 21 度」是默认设置；「你说话简洁点」是助手风格——混在一个 JSON 里，模型和用户都容易搞混。
2. **更新方式不同**：记忆按 `category + key` 覆盖（如 `location/home_address`）；偏好按字段合并（只改音乐不动座位）；人设改 `tone` 和少量 `style_notes`。
3. **使用方式不同**：人设进 **system prompt**；记忆和偏好进 **user context** 分块，给规划和问答看。
4. **压缩隔离**：对话 transcript 可以截断、摘要，但三文件是**长期画像**，不被会话压缩覆盖。

---

## 三、端到端流程（用户说一句话之后发生了什么）

```
用户口语
    │
    ▼
┌──────────────────────────────────────┐
│ 1. 主干第一轮 StructuredNLU          │
│    同一 JSON 输出 intent + tool_calls  │
│    + profile_update（是否更新三文件）  │
│    → 控车 / 查车况 / 手册 / 闲聊      │
│    → 生成助手回复写入 transcript      │
│    （快路径无 LLM 时 profile 全 false）│
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│ 2. 轮末画像管道（仅 intent 触发时）   │
│    加载已有 persona/memories/prefs     │
│    → 分路 LLM 合并/冲突消解 → 落盘    │
│    不再每轮单独 triage                 │
└──────────────────────────────────────┘
    │
    ▼
┌──────────────────────────────────────┐
│ 3. 下一轮规划前                       │
│    ContextAssembler 组装上下文        │
│    system ← persona                   │
│    user_context ← memories + prefs    │
│    + 车况 + 近轮对话 + 压缩摘要       │
└──────────────────────────────────────┘
```

**面试关键词**：「首轮意图一并分拣、主干先答、按需更新、下一轮再注入」。

---

## 四、画像管道（三步）

### 第 1 步：首轮意图分拣（与 StructuredNLU 同一次 LLM）

规划 JSON 里带 `profile_update`，读**用户本轮原话**决定三路与清空：

```json
{
  "profile_update": {
    "persona": true/false,
    "memory": true/false,
    "preferences": true/false,
    "clear": { "persona": false, "memory": false, "preferences": false }
  }
}
```

**举例**：
- 「打开空调」→ 全 false（一次性控车；快路径亦同）
- 「我家在望京」→ memory true
- 「以后叫我老板」→ preferences true
- 「温柔点，我家国贸，以后听周杰伦」→ 三个都可能 true

### 第 2 步：分路更新 LLM（仅 profile_update 为 true 的路）

轮末主干结束后才调用。输入 = **system 抽取 prompt + 用户原话 + 已加载的现有记录**。

| 路 | 上下文加载 | 产出示例 |
|----|------------|----------|
| persona | 当前 `persona.json` | `tone`, `style_notes`, `resolve_note` |
| memory | 当前 `memories.items[]` | 先比对冲突再 upsert/delete |
| preferences | 当前 `preferences.json` | 新值覆盖旧默认 |

记忆路会做**语义冲突消解**：同 key 或同一事实矛盾时以用户本轮原话为准。

### 第 3 步：落盘 + 轨迹（UserProfileStore + trace）

- `persona.json` / `memories.json` / `preferences.json` 落盘
- trace 步骤 `MEMORY` 记录 `intent_decision` + `update_steps[]`（含 `context_loaded`、`user_input`、`delta`/`changes`）

- 执行轨迹里记 `轮末画像更新` 或 `分拣无落盘`
- 失败打日志，不再静默吞异常

---

## 五、三者分别记什么、不记什么

### 人设 persona

| 记 | 不记 |
|----|------|
| 温柔/专业/简洁/活泼 | 用户住址、家人 |
| 「别卖萌」「少用 emoji」 | 空调温度、座位 |
| 助手语速风格 | 用户昵称（那是偏好） |

**注入位置**：`build_system_prompt(persona)` → 拼进 system，影响所有路径语气。

### 身份记忆 memories

| 记 | 不记 |
|----|------|
| 家地址、公司、家人姓名 | 音乐口味、昵称 |
| 可导航的「回家」锚点 | 空调默认温度 |
| 长期稳定的事实 | 一次性控车指令 |

**结构**：`[{category, key, value}]`，如 `location/home_address → 望京`。

### 行为偏好 preferences

| 记 | 不记 |
|----|------|
| 常用座位 `preferred_seat` | 家住哪（memory） |
| 分区默认温度 `climate_temp_c` | 女儿叫什么（memory） |
| 昵称 `display_name` | 助手语气（persona） |
| 音乐口味 `music_pref` | 「现在调到 26 度」一次性指令 |

**生效时机**：用户说「开空调」但没说几度 → 用偏好温度补工具参数；没说座位 → `resolve_active_seat` 用偏好座位。

---

## 六、上下文怎么组装（规划时怎么用）

```
system prompt
├── SYSTEM_CORE（小特边界：不能假控车…）
└── persona overlay（用户定制语气）

user_context（拼成一大块给 NLU / Agent）
├── ### 用户人设 (persona.json)      ← 给模型看摘要
├── ### 身份记忆 (memories.json)
├── ### 行为偏好 (preferences.json)
├── ### 车辆状态快照（按问题裁剪）
├── ### 压缩摘要（若有）
└── ### 最近对话 transcript

memory_hint（给 NLU 的短串）
├── 偏好块 + 记忆块 + 近轮对话（≤900 字）
```

**面试点**：人设进 system 管「怎么说」；记忆+偏好进 user context 管「知道用户什么」；车况单独裁剪防「加戏」。

---

## 七、会话压缩 vs 长期画像

| | transcript（对话流水） | persona / memories / preferences |
|--|------------------------|----------------------------------|
| 存在哪 | `transcript.jsonl` | `memory/*.json` |
| 超长怎么办 | 截断 tool、丢掉旧消息、LLM 摘要 | **不压缩、不覆盖** |
| 摘要放哪 | compaction 角色消息 | 摘要只辅助读历史，画像仍以 JSON 为准 |

压缩五层（由轻到重）：`budget_reduction → snip → microcompact → context_collapse → auto_compact`。

---

## 八、典型口语 → 落哪一类（面试爱问）

| 用户说 | 分类 | 原因 |
|--------|------|------|
| 希望你专业点 | persona | 改助手语气 |
| 我家在望京 | memory | 用户身份事实 |
| 女儿叫小雨 | memory | 家人信息 |
| 以后叫我老板 | preferences | 称呼习惯 |
| 我坐副驾，喜欢 22 度 | preferences | 默认座位+温度 |
| 以后空调全开 21 度 | preferences | 全车默认 |
| 喜欢听周杰伦 | preferences | 音乐默认 |
| 打开空调 | 无 | 一次性控车 |
| 现在调到 26 度 | 无 | 当轮指令，非长期 |
| 忘掉我的偏好 | clear.preferences | 清空偏好文件 |
| 说话简洁，家在国贸，音乐偏好周杰伦 | 三者可能同时更新 | 混合句 triage 多路 true |

---

## 九、和控车链路的关系（易错面试题）

**问**：「我坐副驾，喜欢 22 度」会先控车还是先记偏好？

**答**：
1. **同一轮**里，规划器可能识别为 `tool`，立刻调 `climate.set_temperature`（用户马上凉快）。
2. **轮末**再走 triage + preferences 抽取，把「副驾 + 22 度」写入 `preferences.json`。
3. **下一轮**用户只说「有点热」或「开空调」，系统用偏好补座位和温度。

**设计原则**：控车是「当下执行」，偏好是「下次默认」——两条线，轮末统一收口落盘。

**五座分区**（NLU 必须用英文 zone）：
- 主驾 `front_left`，副驾 `front_right`（不是右后 `rear_right`）

---

## 十、存储路径与数据结构（扫一眼即可）

```
state/sessions/<session_id>/memory/
  persona.json      → { tone, style_notes, updated_at }
  memories.json     → { items: [{category,key,value,id}] }
  preferences.json  → { preferred_seat, climate_temp_c, display_name, music_pref, climate_apply_all }
```

每用户 / 每 session 独立目录，SQLite 管会话列表，文件管画像与 transcript。

---

## 十一、我们测过什么问题、系统层怎么修

| 问题 | 系统层修复思路（非硬编码规则） |
|------|-------------------------------|
| 控车+偏好同句偏好不落盘 | triage/抽取 prompt 明确：「已控车仍要写长期偏好」 |
| 副驾控成右后 | NLU 系统提示补全五座分区表 + 规划上下文对照 |
| 音乐偏好进 memories | memory 抽取 prompt 禁止音乐/昵称/空调 |
| 换语气后 style_notes 堆叠 | persona 抽取要求 replace；tone 切换时清空旧 notes |
| 全车 21 度只写单区 | preferences 抽取要求 all+apply_all；落盘时 apply_all 覆盖五区 |
| 抽取失败无感知 | 轮末打日志 + trace 步骤，分拣无落盘也记录 |

---

## 十二、30 秒电梯版（背这个）

「我们把用户画像拆成三块：助手人设、身份记忆、行为偏好，三个 JSON 独立管理。每轮用户说完，主干先回答；尾巴上 LLM 先分拣再分路抽取，异步落盘，不拖慢语音。下一轮规划时，人设进 system，记忆和偏好进 user context，结合裁剪车况和近轮对话。对话太长只压缩 transcript，不动长期画像。偏好还能在控车时当默认值，比如没说温度就用记住的 22 度。」

---

## 十三、可能追问

**Q：和 RAG 记忆有什么区别？**  
A：RAG 是手册/文档检索；这三块是**用户级长期画像**，结构化 key-value，轮末 LLM 更新，不是向量检索。

**Q：为什么不用一个 LLM 一次抽完？**  
A：分路降低串类（地址写进温度、音乐写进记忆）；triage 为 false 的路不调模型，省 token。

**Q：`AGENT_ENABLE_AUTO_MEMORY=false` 会怎样？**  
A：轮末不抽取，三文件不变，只剩手动或旧逻辑。

**Q：多 session 会串吗？**  
A：每 session 独立 `memory/` 目录；同昵称不同 session 不共享（除非产品层做用户登录绑定）。

---

相关代码入口：
- 抽取：`app/agent/profile_extract.py`
- 存储：`app/agent/user_profile.py`
- 门面：`app/agent/memory.py`
- 轮末调用：`app/orchestrator/runtime.py` → `_persist_turn`
- 上下文：`app/agent/context.py` → `ContextAssembler`
