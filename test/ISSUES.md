# 真实测试问题梳理

> 最新扩展测试：`memtest_20260823_204010`（**30 轮** + 压缩，会话 `memtest_20260823_204010_f5bb8a8f`）
> 首轮测试：`memtest_20260823_164817`

## 扩展测试汇总（20260823_204010）

| 指标 | 值 |
|------|-----|
| 对话轮次 | **30** |
| 通过 | **27** |
| 失败 | **3** |
| 总耗时 | **约 294 s** |
| 总 Token | **约 118k+**（见 JSON 汇总） |
| 压缩 | PASS |

| 类别 | 通过 | 失败 |
|------|------|------|
| persona | 4 | 1 (P-04 concise) |
| memory | 6 | 0 |
| preferences | 3 | 2 (F-03/F-05) |
| negative | 5 | 0 |
| mixed | 2 | 0 |
| clear | 3 | 0 |
| verify/regression | 4 | 0 |

**新确认**：`以后我坐副驾，空调默认22度`（F-02）端到端 **可落盘**；清空人设/记忆/偏好（C-P01/C-M01/C-F01）**均正常**。

**仍失败**：
- P-04：playful 未切到 concise
- F-03：`以后空调全开21度` 控车后偏好未更新（仍仅 front_right 22）
- F-05：`习惯坐主驾24度` 未覆盖副驾偏好

完整报告：`test/REPORT.md` · JSON：`test/results/memtest_20260823_204010_results.json`

---

## 一、测试结论总览（首轮 9 轮）

## 一、测试结论总览

| 模块 | 结果 | 说明 |
|------|------|------|
| 人设 persona | **基本正常** | professional / gentle / concise 均能写入 `persona.json` |
| 身份记忆 memories | **基本正常** | 住址、家人名可写入；存在与偏好串类 |
| 行为偏好 preferences | **部分失败** | 昵称、音乐偏好 OK；**座位+温度长期偏好未写入** |
| 上下文压缩 | **正常** | 25155→2015 字符；三文件画像未被覆盖 |
| 控车与画像冲突 | **有问题** | 带控车语义的偏好句走 tool 路径后，偏好落盘不稳定 |

**通过率**：画像用例 7/9，压缩 1/1。

---

## 二、每轮耗时与 Token（真实 API usage）

| ID | 输入 | 墙钟 ms | LLM ms | Token (P/C/T) | P/M/F | 结果 |
|----|------|---------|--------|-----------------|-------|------|
| P-01 | 希望你说话专业一点… | 12275 | 12201 | 4134/214/4348 | 1/0/0 | ✓ |
| M-01 | 我家住在望京 | 9003 | 8957 | 4312/238/4550 | 0/1/0 | ✓ |
| F-01 | 我坐副驾，喜欢22度 | 10654 | 10600 | 4161/290/4451 | 0/0/0 | ✗ |
| F-02 | 以后叫我老板 | 8332 | 8290 | 4618/209/4827 | 0/0/1 | ✓ |
| M-02 | 我女儿叫小雨 | 9517 | 9476 | 4700/235/4935 | 0/1/0 | ✓ |
| N-01 | 打开空调 | 2254 | 2212 | 437/56/493 | 0/0/0 | ✓ |
| P-02 | 温柔一点说话 | 8455 | 8418 | 4623/207/4830 | 1/0/0 | ✓ |
| F-03 | 以后空调全开21度 | 13255 | 13215 | 2788/314/3102 | 0/0/0 | ✗* |
| T-01 | 简洁+国贸+音乐偏好 | 17501 | 17436 | 3376/417/3793 | 1/1/1 | ✓ |
| C-01 | 强制压缩 | 2144 | — | (压缩摘要另计) | — | ✓ |

\* F-03 端到端未落盘，但用相同助手回复单独调用 `extract_after_turn` **可以**写入 21℃ 全车偏好（见诊断）。

**合计**：墙钟约 **93.4 s**，对话 Token **35,329**（不含压缩轮内 LLM 摘要 token）。

典型一轮 chat 路径约 **8–12 s / 4000–5000 tokens**（含 NLU 规划 + 闲聊回复 + 轮末 triage/抽取 2–4 次调用）。

---

## 三、已确认问题（按优先级）

### P0 — 控车+偏好同句时偏好不落盘（F-01 / F-03）

**现象**

- `我坐副驾，喜欢22度`：意图 `tool`，控车执行了，但 `preferences.json` 无 `preferred_seat` / `climate_temp_c`。
- `以后空调全开21度`：全车温度工具执行成功，但端到端未更新偏好（诊断脚本可更新）。

**根因（F-01）**

1. **分拣 triage** 对「我坐副驾，喜欢22度」会标 `preferences=true`。
2. **抽取器** `extract_preferences` 按 prompt 规则把「喜欢22度」视为**一次性控车**，返回 `update=false`（无「以后/习惯/默认」）。
3. 与单元测试 `test_memory_preferences.py` 用 Mock 强制返回 seat+temp **不一致**——真实本地模型遵守「一次性不写偏好」规则。

**根因（F-03）**

- 端到端轮次 `llm_calls=4`（说明轮末至少跑了 triage），但 `preferences_updated=false`。
- 相同用户话 + 助手回复离线 `extract_after_turn` **可成功** → 怀疑 `_persist_turn` 内 `except Exception: pass` **吞掉异常**或 triage/抽取在控车上下文下返回空，**缺乏日志无法区分**。

**建议**

1. 偏好句含控车语义时：控车完成后**仍走抽取**；或 triage 规则增加「我坐副驾 + 喜欢温度」→ preferences。
2. `_persist_turn` 禁止裸 `pass`，至少 `logging.warning` + trace 步骤。
3. 单元测试拆成：Mock 理想路径 + 真实 LLM 集成测试两套。

---

### P0 — 副驾座位映射错误（F-01）

**现象**

NLU 将「副驾」映射为 `rear_right`（右后），工具结果：`右后温度已设为22°C`。

**期望**

`front_right`（副驾）。

**影响**

- 控车目标座位错误。
- 即使写入偏好，座位 key 也会错。

**位置**

`StructuredNLU` 规划输出（见 `turns.jsonl` turn `08b3b46ab604`）。

---

### P1 — 记忆与偏好 / 人设串类（T-01）

**现象**

`以后音乐偏好周杰伦` 同时：

- `preferences.music_pref` = 周杰伦 ✓
- `memories` 增加 `other/music_preference` = 周杰伦 ✗（应只在 preferences）

人设「说话简洁点」写入 `tone=concise`，但 `style_notes` 仍保留 P-01 的专业向旧 notes，未按语气切换清理。

---

### P1 — 身份记忆句被当闲聊，回复质量差（M-01）

**现象**

「我家住在望京」→ intent `chat`；助手回复把**车辆 GPS** 和望京混谈，未明确「已记住家庭地址」。

**影响**

用户难以感知记忆已写入（尽管 `memories.json` 实际已更新）。

---

### P1 — 轮末画像异常无观测性

**代码**

```python
# runtime.py _persist_turn
except Exception:
    pass
```

**影响**

抽取失败、JSON 解析失败、LLM 超时等**静默丢失**，测试只能看到「未更新」，无法定位。

---

### P2 — 压缩摘要未保留长期偏好

**现象**

`auto_compact` 摘要：`用户偏好：查询空调温度、车窗状态及心情…`，**未包含**已写入的 nickname、住址、音乐偏好。

**影响**

超长会话后，transcript 摘要可能丢画像细节（三文件 JSON 仍完整，但 context 里的压缩摘要信息偏薄）。

---

## 四、正常能力确认

| 能力 | 证据 |
|------|------|
| persona tone 切换 | professional → gentle → concise 均写入 |
| memories upsert | 望京→国贸覆盖；child_name 小雨 |
| preferences 昵称 | display_name=老板 |
| preferences 音乐 | music_pref=周杰伦 |
| 负例「打开空调」 | triage 不更新画像 |
| 压缩不碰三文件 | persona/memories/preferences JSON 压缩前后一致 |
| 压缩层 | budget_reduction + snip + auto_compact |
| Token 统计 | vLLM 返回真实 usage，`token_source=api` |

---

## 五、建议修复顺序

1. 修复副驾 → `front_right` 座位映射（NLU / seat 词表）。
2. `_persist_turn` 加日志与 trace 失败步骤；去掉裸 `except: pass`。
3. 调整 `PREFERENCES_EXTRACT_SYSTEM`：「我坐X / 喜欢Y度」视为长期偏好（或 triage 后规则层补写）。
4. 控车+偏好混合句：工具执行后**强制** preferences 抽取（若 triage.preferences）。
5. memory 抽取 prompt 禁止 music_pref；persona 切换时可选清空/替换 style_notes。
6. auto_compact prompt 要求保留三文件中的 nickname / 住址 / 空调默认等关键偏好。

---

## 六、复现与诊断命令

```bash
# 全量测试
python test/run_profile_compact_test.py

# 单独诊断抽取
python test/diagnose_extract.py

# 查看会话画像
cat state/sessions/memtest_20260823_164817_480a548b/memory/persona.json
cat state/sessions/memtest_20260823_164817_480a548b/memory/memories.json
cat state/sessions/memtest_20260823_164817_480a548b/memory/preferences.json
```

完整数据：`test/results/memtest_20260823_164817_results.json`
