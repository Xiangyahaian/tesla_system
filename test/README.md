# 画像 / 记忆 / 偏好 / 压缩 — 真实测试目录

## 结构

```
test/
├── README.md                 # 本说明
├── REPORT.md                 # 最近一次测试报告（自动生成）
├── ISSUES.md                 # 问题梳理与根因
├── test_cases.json             # 30+ 用例定义（可扩展）
├── run_profile_compact_test.py
├── diagnose_extract.py       # 抽取链路诊断
└── results/
    └── memtest_*_results.json  # 完整 JSON（耗时、token、每轮结果）
```

## 如何复跑

```bash
conda activate tesla
cd /home/xiangyahaian/tesla_system
python test/run_profile_compact_test.py
```

要求：
- 本地 vLLM 可用（`.env` 中 `VLLM_API_BASE`，当前 `http://192.168.1.100:8000/v1`）
- `AGENT_ENABLE_AUTO_MEMORY=1`

## 最近一次真实测试

| 项 | 值 |
|----|-----|
| 运行 ID | `memtest_20260823_204010` |
| 会话 ID | `memtest_20260823_204010_f5bb8a8f` |
| 用例数 | 30（见 `test/test_cases.json`） |
| 模型 | `qwen-4b-tesla` |
| 总耗时 | **287.6 s**（30 轮 + 压缩） |
| 总 Token | **117,783** |
| 通过率 | **27/30** |
| 压缩 | **PASS** |

用例定义：`test/test_cases.json`（可增删后复跑）

会话数据：`state/sessions/memtest_20260823_204010_f5bb8a8f/`
