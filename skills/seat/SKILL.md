# Seat Skill - 座椅与方向盘舒适度域 V4

---
name: seat
description: 控制座椅加热、通风、按摩以及方向盘加热等舒适功能，支持五个独立座位位置的多区域同步操作
metadata:
  functions:
    - name: seat_heat
      description: 控制指定位置座椅加热的开关和档位，支持多区域同步设置
    - name: seat_ventilation
      description: 控制指定位置座椅通风的开关和档位，支持多区域同步设置
    - name: seat_massage
      description: 控制指定位置座椅按摩的开关、模式和强度，支持多区域同步设置
    - name: steering_wheel_heat
      description: 控制方向盘加热的开关和档位
---

## 座位位置定义

系统支持 **5个独立座位位置**，每个位置的状态完全独立：

| 位置参数值 | 说明 | 同义词 |
|-----------|------|--------|
| `front_left` | 前排左座（驾驶位） | driver, 驾驶位, 主驾, 驾驶员座椅 |
| `front_right` | 前排右座（副驾位） | passenger, 副驾, 副驾驶, 副驾驶员座椅 |
| `rear_left` | 后排左座 | 左后座, 后排左侧 |
| `rear_right` | 后排右座 | 右后座, 后排右侧 |
| `rear_middle` | 后排中间座 | 中后座, 后排中间 |

**多区域同步**: 使用 `positions` 数组参数可同时操作多个位置
- 全车座椅: `["front_left", "front_right", "rear_left", "rear_middle", "rear_right"]`
- 前排座椅: `["front_left", "front_right"]`
- 后排座椅: `["rear_left", "rear_middle", "rear_right"]`
- 左侧座椅: `["front_left", "rear_left"]`
- 右侧座椅: `["front_right", "rear_right"]`

**默认行为**:
- 未指定位置时，默认操作 `front_left`（驾驶位）
- 支持 `position`（单位置）和 `positions`（多位置）两种参数形式

---

## 函数详细说明

### 1. seat_heat - 座椅加热
**功能**：控制指定位置座椅加热的开关和档位，支持多区域同步设置

**参数**：
- `positions` (array): **推荐**，座位位置列表，如 `["rear_left", "rear_middle", "rear_right"]`
  - 当 `positions` 和 `position` 同时存在时，优先使用 `positions`
  - 默认值: `front_left`
- `level` (number): **必填，绝对值**，加热档位 0-3
  - 0: 关闭
  - 1: 低温
  - 2: 中温
  - 3: 高温
- `enable` (boolean): **必填**，开关状态（true=开, false=关）

**使用规则**:
- `level > 0` 时，`enable` 必须为 `true`
- `level = 0` 时，`enable` 必须为 `false`

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开座椅加热" | `seat_heat(positions=["front_left"], level=2, enable=true)` |
| "打开右后座椅加热" | `seat_heat(positions=["rear_right"], level=2, enable=true)` |
| "副驾加热调到1档" | `seat_heat(positions=["front_right"], level=1, enable=true)` |
| "后排中间加热关闭" | `seat_heat(positions=["rear_middle"], level=0, enable=false)` |
| **"打开后排所有座椅加热"** | `seat_heat(positions=["rear_left", "rear_middle", "rear_right"], level=2, enable=true)` |
| **"全车座椅加热打开"** | `seat_heat(positions=["front_left", "front_right", "rear_left", "rear_middle", "rear_right"], level=2, enable=true)` |
| **"前排座椅加热都打开"** | `seat_heat(positions=["front_left", "front_right"], level=2, enable=true)` |

---

### 2. seat_ventilation - 座椅通风
**功能**：控制指定位置座椅通风的开关和档位，支持多区域同步设置

**参数**：
- `positions` (array): **推荐**，座位位置列表
- `position` (string): **兼容旧版**，单个座位位置
  - 默认值: `front_left`
- `level` (number): **必填，绝对值**，通风档位 0-3
  - 0: 关闭
  - 1: 弱风
  - 2: 中风
  - 3: 强风
- `enable` (boolean): **必填**，开关状态

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开座椅通风" | `seat_ventilation(positions=["front_left"], level=2, enable=true)` |
| "右后座通风调到最大" | `seat_ventilation(positions=["rear_right"], level=3, enable=true)` |
| "关闭副驾通风" | `seat_ventilation(positions=["front_right"], level=0, enable=false)` |
| **"后排通风全部打开"** | `seat_ventilation(positions=["rear_left", "rear_middle", "rear_right"], level=2, enable=true)` |
| **"全车通风打开"** | `seat_ventilation(positions=["front_left", "front_right", "rear_left", "rear_middle", "rear_right"], level=2, enable=true)` |

---

### 3. seat_massage - 座椅按摩
**功能**：控制指定位置座椅按摩的开关、模式和强度，支持多区域同步设置

**参数**：
- `positions` (array): **推荐**，座位位置列表
- `position` (string): **兼容旧版**，单个座位位置
  - 默认值: `front_left`
- `level` (number): **必填，绝对值**，按摩强度 0-3
  - 0: 关闭
  - 1: 轻柔
  - 2: 标准
  - 3: 强劲
- `mode` (string): **可选**，按摩模式，默认 `"normal"`
  - 可选值: `normal`(标准), `wave`(波浪), `pulse`(脉冲), `knead`(揉捏)
- `enable` (boolean): **必填**，开关状态

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开按摩" | `seat_massage(positions=["front_left"], level=2, mode="normal", enable=true)` |
| "右后座按摩改成波浪模式" | `seat_massage(positions=["rear_right"], level=2, mode="wave", enable=true)` |
| "副驾按摩调弱一点"（当前2档） | `seat_massage(positions=["front_right"], level=1, enable=true)` |
| "关闭后排中间按摩" | `seat_massage(positions=["rear_middle"], level=0, enable=false)` |
| **"后排按摩全部打开"** | `seat_massage(positions=["rear_left", "rear_middle", "rear_right"], level=2, mode="normal", enable=true)` |
| **"全车按摩打开"** | `seat_massage(positions=["front_left", "front_right", "rear_left", "rear_middle", "rear_right"], level=2, mode="normal", enable=true)` |

---

### 4. steering_wheel_heat - 方向盘加热
**功能**：控制方向盘加热的开关和档位

**参数**：
- `level` (number): **必填，绝对值**，加热档位 0-3
  - 0: 关闭
  - 1: 低温
  - 2: 中温
  - 3: 高温
- `enable` (boolean): **必填**，开关状态（true=开, false=关）

**注意**：方向盘没有位置参数，全车只有一个方向盘

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开方向盘加热" | `steering_wheel_heat(level=2, enable=true)` |
| "关掉方向盘加热" | `steering_wheel_heat(level=0, enable=false)` |
| "方向盘加热调高一点"（当前1档） | `steering_wheel_heat(level=2, enable=true)` |

---

## V4 版本重要变更

### 变更1: 支持多区域同步操作
- **旧版本**: 单次只能操作一个位置（`position` 参数为字符串）
- **新版本**: 新增 `positions` 数组参数，可同时操作多个位置
- 例如：`positions=["rear_left", "rear_middle", "rear_right"]` 同时打开后排三个座位的加热

### 变更2: 保留向后兼容
- `position` 参数仍然有效，用于单位置操作
- 当 `positions` 和 `position` 同时存在时，优先使用 `positions`
- 未指定任何位置参数时，默认操作 `front_left`（驾驶位）

### 变更3: 默认行为不变
- 未指定位置时，默认操作 `front_left`（驾驶位）
- 每个位置仍有独立的 `level`（档位）和 `enable`（开关）状态

### 变更4: 状态结构不变
```json
{
  "seat": {
    "seat_heat": {
      "front_left": {"level": 2, "enable": true},
      "front_right": {"level": 0, "enable": false},
      "rear_left": {"level": 2, "enable": true},
      "rear_right": {"level": 2, "enable": true},
      "rear_middle": {"level": 2, "enable": true}
    },
    "seat_ventilation": { ... },
    "seat_massage": { ... },
    "steering_wheel_heat": {"level": 0, "enable": false}
  }
}
```

---

## 状态追踪

执行后自动更新 state.json 中对应位置的值：

```json
{
  "seat": {
    "seat_heat": {
      "front_left": {"level": 2, "enable": true},
      "front_right": {"level": 0, "enable": false},
      "rear_left": {"level": 2, "enable": true},
      "rear_right": {"level": 2, "enable": true},
      "rear_middle": {"level": 2, "enable": true}
    },
    "seat_ventilation": {
      "front_left": {"level": 1, "enable": true},
      "front_right": {"level": 0, "enable": false},
      "rear_left": {"level": 0, "enable": false},
      "rear_right": {"level": 0, "enable": false},
      "rear_middle": {"level": 0, "enable": false}
    },
    "seat_massage": {
      "front_left": {"level": 1, "mode": "wave", "enable": true},
      "front_right": {"level": 0, "mode": "normal", "enable": false},
      "rear_left": {"level": 0, "mode": "normal", "enable": false},
      "rear_right": {"level": 0, "mode": "normal", "enable": false},
      "rear_middle": {"level": 0, "mode": "normal", "enable": false}
    },
    "steering_wheel_heat": {
      "level": 1,
      "enable": true
    }
  }
}
```
