# Agent Skill - 语音助手情景模式域

---
name: agent
description: 配置语音助手的行为模式、语音设置、场景切换等个性化设置
metadata:
  functions:
    - name: set_persona
      description: 设置语音助手的形象和性格
    - name: set_speech
      description: 设置语音的语速、音量、说话模式
    - name: switch_scene
      description: 切换情景模式，如驾驶模式、休息模式等
---

## 函数详细说明

### 1. set_persona - 形象设置
**功能**：设置语音助手的形象和性格

**参数**：
- `voice` (string): 声音类型，可选
  - 可选值: "female", "male", "child", "robot"
- `tone` (string): 语气风格，可选
  - 可选值: "friendly", "professional", "humorous", "gentle"
- `name` (string): 助手名称，可选

**示例**：
- "换个男声" → set_persona(voice="male")
- "语气专业一点" → set_persona(tone="professional")

---

### 2. set_speech - 语音设置
**功能**：设置语音的语速、音量、说话模式

**参数**：
- `speed` (string): 语速，默认 "normal"
  - 可选值: "slow", "normal", "fast"
- `mode` (string): 说话模式，默认 "normal"
  - 可选值: "normal", "brief", "detailed"
- `volume` (number): 音量 0-100，可选

**示例**：
- "说快点" → set_speech(speed="fast")
- "声音大点" → set_speech(volume=80)

---

### 3. switch_scene - 场景切换
**功能**：切换情景模式，如驾驶模式、休息模式等

**参数**：
- `scene` (string): 场景名称，默认 ""
  - 可选值: "normal", "sport", "eco", "rest", "meeting", "kids"
- `enable` (boolean): 开启/关闭，默认 true

**示例**：
- "切换到休息模式" → switch_scene(scene="rest")
- "打开儿童模式" → switch_scene(scene="kids", enable=true)
