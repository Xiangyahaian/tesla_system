# 画像与压缩真实测试报告

- **运行 ID**: `memtest_20260823_223827`
- **会话 ID**: `memtest_20260823_223827_3fad4a87`
- **本地模型**: `qwen-4b-tesla` @ `http://192.168.1.100:8000/v1`
- **完成时间**: 2026-08-23T22:43:48.326272

## 汇总

| 指标 | 值 |
|------|-----|
| 对话轮次 | 49 |
| 通过 | 42 |
| 失败 | 7 |
| 总耗时 (ms) | 337741 |
| 总 Token | 254934 |
| 压缩测试 | PASS |

## 分类统计

| 类别 | 通过 | 失败 | Token | 耗时ms |
|------|------|------|-------|--------|
| persona | 6 | 0 | 32856 | 30469 |
| memory | 7 | 0 | 40222 | 39316 |
| preferences | 8 | 0 | 41395 | 49672 |
| negative | 7 | 0 | 19355 | 44625 |
| mixed | 1 | 3 | 24667 | 36548 |
| mixed_hard | 1 | 2 | 20986 | 33612 |
| mixed_control | 3 | 1 | 22014 | 38498 |
| mixed_triple | 1 | 1 | 20739 | 30702 |
| regression | 1 | 0 | 5762 | 8592 |
| verify | 4 | 0 | 8399 | 6714 |
| clear | 3 | 0 | 18539 | 17891 |

## 每轮明细

| ID | 输入 | 耗时ms | Token | P/M/F | 意图 | 结果 |
|----|------|--------|-------|-------|------|------|
| P-01 | 希望你说话专业一点，少寒暄套话 | 5539 | 5181 | True/False/False | chat | ✓ persona 已更新；tone=professional |
| P-02 | 温柔一点说话 | 5216 | 5337 | True/False/False | chat | ✓ persona 已更新；tone=gentle |
| P-03 | 轻松活泼点，可以适度俏皮 | 4219 | 5452 | True/False/False | chat | ✓ persona 已更新；tone=playful |
| P-04 | 回复尽量简短干练 | 3911 | 5497 | True/False/False | chat | ✓ persona 已更新；tone=concise |
| P-05 | 别用emoji，也别卖萌 | 5450 | 5556 | True/False/False | chat | ✓ persona 已更新 |
| M-01 | 我家住在望京 | 5298 | 5550 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| M-02 | 我女儿叫小雨 | 9190 | 5646 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| M-03 | 我在中关村软件园上班 | 3957 | 5732 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| M-04 | 我老婆叫小美 | 3770 | 5780 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| F-01 | 以后叫我老板 | 4542 | 6132 | False/False/True | chat | ✓ preferences 已更新 |
| F-02 | 以后我坐副驾，空调默认22度 | 7260 | 4866 | False/False/True | chat | ✓ preferences 已更新；seat=front_right；温度偏好已写 |
| F-03 | 以后空调全开21度 | 5594 | 4032 | False/False/True | tool | ✓ preferences 已更新；温度偏好已写 |
| F-04 | 我平时喜欢听民谣 | 5809 | 6050 | False/False/True | chat | ✓ preferences 已更新 |
| F-05 | 习惯坐主驾，温度24度 | 7996 | 4929 | False/False/True | tool | ✓ preferences 已更新；seat=front_left；温度偏好已写 |
| N-01 | 打开空调 | 323 | 102 | False/False/False | tool | ✓ 画像无变化 |
| N-02 | 今天天气真好 | 5309 | 5921 | False/False/False | chat | ✓ 画像无变化 |
| N-03 | 空调现在多少度 | 3814 | 4504 | False/False/False | search | ✓ 画像无变化 |
| N-04 | 现在调到26度 | 5400 | 3885 | False/False/False | tool | ✓ 画像无变化 |
| N-05 | 胎压怎么看 | 25054 | 1408 | False/False/False | knowledge | ✓ 画像无变化 |
| T-01 | 说话简洁点，我家在国贸，以后音乐偏好周杰伦 | 8734 | 5070 | False/True/True | tool | ✗ persona 未更新 |
| T-02 | 希望你专业点，公司在中关村，以后左后默认23度 | 7107 | 5658 | False/False/True | tool | ✗ persona 未更新；memories 未更新 |
| T-03 | 温柔点，女儿叫朵朵，以后叫我张总，副驾默认20度 | 11191 | 7698 | True/True/True | chat | ✓ persona 已更新；memories 已更新；preferences 已更新 |
| T-04 | 活泼点，老婆叫小丽，喜欢摇滚，习惯中后25度 | 9516 | 6241 | True/False/True | multi_tool | ✗ memories 未更新 |
| T-05 | 简洁干练，我住在西单，公司望京SOHO，以后全车 | 6401 | 3668 | False/False/False | multi_tool | ✗ persona 未更新；memories 未更新；preferences 未更新 |
| T-06 | 专业一点，儿子叫天天，以后右后23度，叫我李哥 | 10988 | 7079 | True/True/True | tool | ✓ persona 已更新；memories 已更新；preferences 已更新 |
| T-07 | 打开空调，我家在亦庄 | 16963 | 8730 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| T-08 | 副驾调到23度，以后默认就这样 | 37 | 0 | False/False/False | tool | ✗ preferences 未更新 |
| T-09 | 温柔点，打开车窗，以后叫我王总 | 7922 | 4913 | True/False/True | tool | ✓ persona 已更新；preferences 已更新 |
| T-10 | 简洁点，宠物叫咪咪，老婆小美，以后民谣，主驾24 | 18080 | 11286 | True/True/True | multi_tool | ✓ persona 已更新；memories 已更新；preferences 已更新 |
| R-01 | 我坐副驾，喜欢22度 | 8592 | 5762 | False/False/True | tool | ✓ 控车+偏好 |
| M-05 | 我搬家了，现在住在国贸 | 6056 | 6522 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| M-06 | 公司换到望京了，不在中关村了 | 7419 | 5097 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| F-06 | 还是喜欢22度吧 | 5508 | 5649 | False/False/False | tool | ✓ 观测用例无硬性断言 |
| F-07 | 以后中后默认25度 | 6131 | 5593 | False/False/True | tool | ✓ preferences 已更新；温度偏好已写 |
| N-06 | 导航去五道口 | 684 | 117 | False/False/False | tool | ✓ 画像无变化 |
| N-07 | 播放晴天 | 4041 | 3418 | False/False/False | tool | ✓ 画像无变化 |
| V-C02 | 打开空调 | 476 | 113 | False/False/False | tool | ✓ 画像无变化 |
| V-C03 | 我家在哪 | 707 | 1454 | False/False/False | search | ✓ 观测用例无硬性断言 |
| C-P01 | 忘掉我的人设，恢复默认说话方式 | 6288 | 5932 | True/True/False | chat | ✓ persona 已恢复 default |
| C-M01 | 忘掉我女儿的名字 | 5628 | 6197 | True/True/False | chat | ✓ 记忆已删除关键词 |
| C-F01 | 忘记我的偏好 | 5975 | 6410 | False/True/True | chat | ✓ 偏好已清空或更新 |
| T-11 | 温柔陪伴，家住望京，叫我老板，习惯副驾21度，喜 | 16223 | 10239 | False/True/True | multi_tool | ✗ persona 未更新 |
| T-12 | 打开主驾座椅加热，以后记住我坐主驾 | 13576 | 8371 | False/False/True | tool | ✓ preferences 已更新；seat=front_left |
| P-06 | 从简洁改回温柔一点 | 6134 | 5833 | True/False/False | chat | ✓ persona 已更新；tone=gentle |
| M-07 | 我爸住在青岛 | 3626 | 5895 | False/True/False | chat | ✓ memories 已更新；记忆含关键词 |
| F-08 | 以后音乐只听周杰伦 | 6832 | 4144 | False/False/True | multi_tool | ✓ preferences 已更新 |
| V-01 | 我叫什么 | 4874 | 5634 | False/False/False | chat | ✓ 观测用例无硬性断言 |
| V-02 | 我家在哪 | 657 | 1198 | False/False/False | search | ✓ 观测用例无硬性断言 |
| T-13 | 专业严谨，公司在国贸，女儿朵朵，以后叫我张总，全 | 12622 | 9453 | False/False/True | tool | ✗ persona 未更新；memories 未更新 |

## 压缩测试 C-MID

- 消息数: 176 → 9
- 字符数: 37901 → 2032
- 压缩层: `['budget_reduction', 'snip', 'auto_compact']`
- 摘要预览: 用户昵称：测试轮次 39。家庭住址、公司、家人、音乐口味、未完成事项、最近车控结果、待确认操作、关键实体均缺失。空调默认偏好：开着；座位默认偏好：关着。最近车控结果：空调开，车窗关。
- 三文件未变: persona=True memories=True prefs=True

## 最终画像

### persona.json
```json
{
  "version": 1,
  "tone": "gentle",
  "style_notes": [
    "使用温柔、亲切的语气",
    "避免使用表情符号或卖萌式表达"
  ],
  "updated_at": "2026-08-23T22:43:21"
}
```

### memories.json (items)
```json
[
  {
    "id": "8660f0234aba",
    "category": "location",
    "key": "home_address",
    "value": "望京",
    "updated_at": "2026-08-23T22:43:01"
  },
  {
    "id": "5b00db10f016",
    "category": "identity",
    "key": "nickname",
    "value": "老板",
    "updated_at": "2026-08-23T22:43:01"
  },
  {
    "id": "c2ec9882b88b",
    "category": "family",
    "key": "father_address",
    "value": "青岛",
    "updated_at": "2026-08-23T22:43:25"
  }
]
```

### preferences.json
```json
{
  "version": 1,
  "preferred_seat": "front_left",
  "climate_temp_c": {
    "front_left": 21.0,
    "front_right": 21.0,
    "rear_left": 21.0,
    "rear_middle": 21.0,
    "rear_right": 21.0
  },
  "climate_apply_all": true,
  "display_name": "张总",
  "music_pref": "周杰伦",
  "updated_at": "2026-08-23T22:43:48"
}
```

完整 JSON: `/home/xiangyahaian/tesla_system/test/results/memtest_20260823_223827_results.json`
会话目录: `/home/xiangyahaian/tesla_system/state/sessions/memtest_20260823_223827_3fad4a87`