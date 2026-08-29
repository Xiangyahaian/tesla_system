# 面试 Demo 剧本（约 3–4 分钟）

入口：`python run.py` → http://127.0.0.1:6006  
（需先 `cd frontend && npm run build`）

## 开场（20s）

「这不是 ChatGPT 套壳，是座舱 Agent Runtime：Gateway 车控、Policy 确认、Transcript 可观测、React HMI。」

展示：左侧导航 Drive/Apps/Agent、顶栏状态条、中间声纹球、右侧 LIVE STATE。

## 片段 1 · 多工具（40s）

点芯片或语音：`打开空调并播放周杰伦的晴天`

看点：对话内 TurnRail；Climate / Media HUD 变化。

## 片段 2 · 状态 + 指代（40s）

`现在音量多少` → `小一点`

看点：读 state 再改 volume，状态条/HUD 同步。

## 片段 3 · 安全门控（40s）

`打开后备箱` → 确认卡 → 确认执行。

金句：「高风险不靠模型嘴炮，靠 Policy。」

## 片段 4 · Apps + RAG（50s）

切到 **Apps** 打开飞书 → 回 Drive 问 `自动泊车怎么用`。

看点：前台 App 同步；Retrieved + 引用页码。

## 收尾（30s）

切到 **Agent** 页：Turn 列表、JSON、Compact。  
Setup 页展示工具注册表。

金句：「Stub Gateway 可换真车机；前端是独立工程，多路由座舱壳，不是单页 HTML。」
