# 面试 Demo 剧本（约 3 分钟）

入口：`python run.py` → http://127.0.0.1:6006

## 开场（15s）

「这不是 ChatGPT 套壳，是座舱 Agent：Gateway 车控、Policy 确认、Transcript 可观测。」

展示：右侧 LIVE STATE、中间声纹球、顶部 CABIN。

## 片段 1 · 多工具（40s）

语音或输入：`打开空调并播放周杰伦的晴天`

看点：
- 对话里出现 intent / tool 轨迹条
- 右侧 Climate / Media 数值变化

## 片段 2 · 状态 + 指代（40s）

`现在音量多少` → 再 `小一点`

看点：SEARCH 读 state，再 TOOL 改 volume，HUD 同步。

## 片段 3 · 安全门控（40s）

`打开后备箱`

看点：确认卡片出现 → 点确认 → 执行。讲「高风险不靠模型嘴炮」。

## 片段 4 · 知识 RAG（40s）

`自动泊车怎么用`

看点：Retrieved 片段 + 引用页码（若有图更好）。

## 收尾（20s）

点「轨迹」打开 Agent Console，展示 turns.jsonl 时间线。

金句：「Stub Gateway 可替换真车机；前端是独立 React 工程，不是单页 HTML 堆砌。」
