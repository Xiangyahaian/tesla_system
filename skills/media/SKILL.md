# Media Skill - 多媒体娱乐系统 (20首本地音乐 + 10个预设电台)

---
name: media
description: 控制车内多媒体系统，包括本地音乐播放、广播收听和音量调节
metadata:
  functions:
    - name: music_control
      description: 本地音乐播放控制（播放/暂停/停止）
    - name: music_switch
      description: 本地音乐切换（上一首/下一首）
    - name: radio_control
      description: 广播收听控制（播放/暂停/停止）
    - name: radio_switch
      description: 电台切换（上一个/下一个电台）
    - name: volume_control
      description: 控制系统音量（统一控制媒体/导航/通话等音量）
---

## 本地音乐库 (共20首)

**注意：本地音乐播放仅支持以下歌曲，播放不在库中的歌曲会提示"对不起，音乐库里没有这首歌"**

### 王菲 (4首)
| 歌曲 | 专辑 |
|-----|------|
| 红豆 | 《唱游》 |
| 流年 | 《王菲》 |
| 执迷不悔 | 《执迷不悔》 |
| 矜持 | 《红豆》 |

### 周杰伦 (4首)
| 歌曲 | 专辑 |
|-----|------|
| 晴天 | 《叶惠美》 |
| 七里香 | 《七里香》 |
| 稻香 | 《魔杰座》 |
| 青花瓷 | 《我很忙》 |

### 陈奕迅 (4首)
| 歌曲 | 专辑 |
|-----|------|
| 浮夸 | 《U87》 |
| 十年 | 《黑白灰》 |
| 富士山下 | 《What's Going On...?》 |
| K歌之王 | 《打得火热》 |

### 邓紫棋 (4首)
| 歌曲 | 专辑 |
|-----|------|
| 泡沫 | 《Xposed》 |
| 光年之外 | 《光年之外》 |
| 句号 | 《摩天动物园》 |
| 来自天堂的魔鬼 | 《新的心跳》 |

### 林俊杰 (4首)
| 歌曲 | 专辑 |
|-----|------|
| 江南 | 《第二天堂》 |
| 可惜没如果 | 《新地球》 |
| 修炼爱情 | 《因你而在》 |
| 不为谁而作的歌 | 《和自己对话》 |

---

## 预设电台列表 (共10个)

**注意：电台收听仅支持以下10个预设电台**

| 频率 | 电台名称 | 波段 | 类别 |
|-----|---------|-----|-----|
| 91.5 | 中国之声 | FM | 新闻 |
| 106.1 | 音乐之声 | FM | 音乐 |
| 103.9 | 北京交通广播 | FM | 交通 |
| 87.6 | 北京音乐广播 | FM | 音乐 |
| 101.7 | 上海音乐广播 | FM | 音乐 |
| 105.7 | 上海交通广播 | FM | 交通 |
| 94.7 | 经典947 | FM | 古典 |
| 105.2 | 广东音乐之声 | FM | 音乐 |
| 639 | 中国之声AM | AM | 新闻 |
| 102.6 | 重庆音乐广播 | FM | 音乐 |

---

## 函数详细说明

### 1. music_control - 本地音乐播放控制
**功能**：播放本地音乐库中的歌曲，支持播放、暂停、停止

**注意：仅支持上方列表中的20首歌曲，其他歌曲会返回"对不起，音乐库里没有这首歌"**

**参数**：
- `action` (string): 操作类型，默认 "play"
  - `"play"`: 播放指定歌曲
  - `"pause"`: 暂停
  - `"stop"`: 停止
- `source` (string): 音乐源，默认 "local"
  - `"local"`: 本地音乐库（仅支持50首固定歌曲）
  - `"usb"`: USB音乐（不校验曲库）
- `artist` (string): 歌手名称
- `title` (string): 歌曲名称
- `album` (string): 专辑名称（自动匹配）

**完整参数示例**：
播放歌曲时必须提供完整的歌曲信息：
- "播放周杰伦的晴天" → 
  ```
  music_control(
    action="play",
    source="local",
    artist="周杰伦",
    title="晴天",
    album="叶惠美"
  )
  ```

- "播放邓紫棋的泡沫" → 
  ```
  music_control(
    action="play",
    source="local",
    artist="邓紫棋",
    title="泡沫",
    album="Xposed"
  )
  ```

**参数说明**：
- `action`: "play" | "pause" | "stop"
- `source`: "local" (本地音乐库，固定值)
- `artist`: 歌手名称（必须从上方20首音乐库列表中选择）
- `title`: 歌曲名称（必须从上方20首音乐库列表中选择）
- `album`: 专辑名称（必须与歌曲匹配，见上表）

**注意**：播放本地音乐时，**必须**同时提供 artist、title、album 三个完整参数！

---

### 2. music_switch - 本地音乐切换
**功能**：切换上一首或下一首歌曲（循环播放）

**参数**：
- `direction` (string): 切换方向，默认 "next"
  - `"prev"`: 上一首
  - `"next"`: 下一首

**示例**：
- "下一首" → music_switch(direction="next")
- "上一首" → music_switch(direction="prev")
- "切歌" → music_switch(direction="next")

---

### 3. radio_control - 广播收听控制
**功能**：收听预设电台，支持播放、暂停、停止

**注意：仅支持上方列表中的10个预设电台**

**参数**：
- `action` (string): 操作类型，默认 "play"
  - `"play"`: 播放指定电台
  - `"pause"`: 暂停
  - `"stop"`: 停止
- `band` (string): 波段类型，如 "FM"、"AM"
- `frequency` (string): 频率，如 "91.5"
- `station_name` (string): 电台名称，如 "中国之声"
- `category` (string): 电台类别，如 "音乐"、"新闻"、"交通"

**示例**：
- "打开中国之声" → radio_control(action="play", station_name="中国之声")
- "调到FM91.5" → radio_control(action="play", band="FM", frequency="91.5")
- "播放音乐电台" → radio_control(action="play", category="音乐")
- "暂停广播" → radio_control(action="pause")
- "关闭广播" → radio_control(action="stop")

---

### 4. radio_switch - 电台切换
**功能**：切换到上一个或下一个电台（循环切换）

**参数**：
- `direction` (string): 切换方向，默认 "next"
  - `"prev"`: 上一个电台
  - `"next"`: 下一个电台

**示例**：
- "下一个电台" → radio_switch(direction="next")
- "上一个电台" → radio_switch(direction="prev")
- "换台" → radio_switch(direction="next")

---

### 5. volume_control - 音量控制
**功能**：控制系统音量（媒体、导航、通话等统一控制）

**参数**:
- `action` (string): 音量操作，默认 "adjust"
  - 可选值: "adjust"(调节到指定值), "up"(增加), "down"(减少), "mute"(静音), "unmute"(取消静音)
- `value` (number): 音量值 0-100（仅在 action="adjust" 时使用），默认 50
  - 0 = 静音，100 = 最大

**音量调节规则（重要）**：
- **"增加音量""减少音量"这类相对调节，必须用 `action="up"` 或 `action="down"`**
- **推荐步长为 20**：即增加约20，减少约20（handler 会按此处理）
- **严禁**用 `action="adjust"` 自己计算相对值（如当前48减1变成47是错误的）
- `action="adjust"` **仅用于**用户明确说具体数值时（如"音量调到60"）

**正确示例**:
- "音量调到60" → volume_control(action="adjust", value=60)
- "调高音量" → volume_control(action="up")  // 增加约20
- "降低音量" → volume_control(action="down")  // 减少约20
- "静音" → volume_control(action="mute")
- "取消静音" → volume_control(action="unmute")

**错误示例（严禁）**:
- ❌ "减少音量" → volume_control(action="adjust", value=46)  // 自己算当前值-1是错误的
- ✅ "减少音量" → volume_control(action="down")  // 正确，交给handler处理

---

## 状态追踪

执行后更新 state.json：

```json
{
  "media": {
    "music_control": {
      "action": "play",
      "source": "local",
      "artist": "邓紫棋",
      "title": "泡沫",
      "album": "Xposed",
      "playing": true,
      "current_index": 44
    },
    "music_switch": {
      "direction": "next",
      "current_index": 45
    },
    "radio_control": {
      "action": "play",
      "band": "FM",
      "frequency": "91.5",
      "station_name": "中国之声",
      "category": "新闻",
      "playing": true,
      "current_index": 0
    },
    "radio_switch": {
      "direction": "next",
      "current_index": 1
    },
    "volume_control": {
      "volume": 50,
      "muted": false
    }
  }
}
```
