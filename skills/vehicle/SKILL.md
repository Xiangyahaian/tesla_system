# Vehicle Skill - 行车安全与底层车控域 V2

---
name: vehicle
description: 控制驾驶模式、ADAS辅助驾驶、车窗车门、车辆状态查询、悬架调节等行车相关功能
metadata:
  functions:
    - name: control_adas
      description: 控制ADAS功能，如自动驻车、巡航、泊车等
    - name: query_status
      description: 查询车辆状态，如电量、里程、胎压等
    - name: manage_maintenance
      description: 管理车辆保养和故障诊断
    - name: switch_drive_mode
      description: 切换驾驶模式，如舒适、运动、经济等
    - name: control_window
      description: 控制指定位置车窗的开关和开合程度（四位置独立）
    - name: control_door
      description: 控制指定位置车门的锁止/解锁（四位置独立）
    - name: control_trunk
      description: 控制后备箱/充电口的开关
---

## 位置定义

### 车窗/车门位置（4个位置）

| 位置参数值 | 说明 | 同义词 |
|-----------|------|--------|
| `front_left` | 前排左（驾驶位） | driver, 驾驶位, 主驾, 左前 |
| `front_right` | 前排右（副驾位） | passenger, 副驾, 副驾驶, 右前 |
| `rear_left` | 后排左 | 左后, 后排左侧, 左后门 |
| `rear_right` | 后排右 | 右后, 后排右侧, 右后门 |
| `all` | 所有位置 | 全车, 全部, 所有车窗/车门 |

**默认行为**：
- 未指定位置时，默认操作 `front_left`（驾驶位车窗/车门）
- 每个位置有独立的开关状态

---

## 函数详细说明

### 1. control_adas - ADAS控制
**功能**：控制ADAS功能，如自动驻车、巡航、泊车等

**参数**：
- `feature` (string): ADAS功能名称，默认 ""
  - 可选值: "autohold", "cruise", "autopark", "lane_keep", "collision_warning"
- `enable` (boolean): 开关状态，默认 true

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开自动驻车" | `control_adas(feature="autohold", enable=true)` |
| "关闭巡航" | `control_adas(feature="cruise", enable=false)` |

---

### 2. control_window - 车窗控制
**功能**：控制指定位置车窗的开关和开合程度

**参数**：
- `position` (string): **必填**，车窗位置
  - 可选值: `front_left`, `front_right`, `rear_left`, `rear_right`, `all`
  - 默认值: `front_left`
- `action` (string): **必填**，操作类型
  - `"open"`: 打开/降下
  - `"close"`: 关闭/升起
  - `"vent"`: 通风模式（微开）
- `level` (number): 开合程度 0-100%，默认 100
  - 0: 完全关闭
  - 100: 完全打开
  - 仅当 action="open" 时有效

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开车窗" | `control_window(position="front_left", action="open", level=100)` |
| "右后车窗降一半" | `control_window(position="rear_right", action="open", level=50)` |
| "关闭所有车窗" | `control_window(position="all", action="close")` |
| "副驾车窗留个缝" | `control_window(position="front_right", action="vent")` |
| "左后车窗打开" | `control_window(position="rear_left", action="open", level=100)` |

---

### 3. control_door - 车门控制
**功能**：控制指定位置车门的锁止/解锁

**参数**：
- `position` (string): **必填**，车门位置
  - 可选值: `front_left`, `front_right`, `rear_left`, `rear_right`, `all`
  - 默认值: `all`（车门控制默认全车）
- `action` (string): **必填**，操作类型
  - `"lock"`: 锁止
  - `"unlock"`: 解锁

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "锁车" | `control_door(position="all", action="lock")` |
| "解锁" | `control_door(position="all", action="unlock")` |
| "锁上右后门" | `control_door(position="rear_right", action="lock")` |
| "解锁左前门" | `control_door(position="front_left", action="unlock")` |

---

### 4. control_trunk - 后备箱/充电口控制
**功能**：控制后备箱和充电口的开关

**参数**：
- `target` (string): **必填**，控制目标
  - `"trunk"`: 后备箱
  - `"charge_port"`: 充电口
  - `"frunk"`: 前备箱
- `action` (string): **必填**，操作类型
  - `"open"`: 打开
  - `"close"`: 关闭

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开后备箱" | `control_trunk(target="trunk", action="open")` |
| "关闭充电口" | `control_trunk(target="charge_port", action="close")` |
| "开前备箱" | `control_trunk(target="frunk", action="open")` |

---

### 5. switch_drive_mode - 驾驶模式
**功能**：切换驾驶模式，如舒适、运动、经济等

**参数**：
- `mode` (string): 驾驶模式，默认 "comfort"
  - 可选值: "comfort", "sport", "eco", "snow", "offroad"

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "切换到运动模式" | `switch_drive_mode(mode="sport")` |
| "打开雪地模式" | `switch_drive_mode(mode="snow")` |

---

### 6. query_status - 状态查询
**功能**：查询车辆状态，如电量、里程、胎压等

**参数**：
- `metric` (string): 查询指标，默认 "status"
  - 可选值: "status", "battery", "range", "tire_pressure", "oil"
- `detail` (boolean): 是否详细模式，默认 false

---

### 7. manage_maintenance - 保养管理
**功能**：管理车辆保养和故障诊断

**参数**：
- `action` (string): 动作，默认 "diagnose"
  - 可选值: "diagnose", "schedule", "history"

---

## V2 状态结构

```json
{
  "vehicle": {
    "control_adas": {
      "auto_hold": {"enable": true},
      "lane_keep": {"enable": false}
    },
    "control_window": {
      "front_left": {"open": false, "level": 0},
      "front_right": {"open": false, "level": 0},
      "rear_left": {"open": false, "level": 0},
      "rear_right": {"open": false, "level": 0}
    },
    "control_door": {
      "front_left": {"locked": true},
      "front_right": {"locked": true},
      "rear_left": {"locked": true},
      "rear_right": {"locked": true}
    },
    "control_trunk": {
      "trunk": {"open": false},
      "charge_port": {"open": false},
      "frunk": {"open": false}
    },
    "switch_drive_mode": {
      "mode": "comfort"
    },
    "query_status": {
      "battery": 78,
      "range": 350
    }
  }
}
```

---

## V2 版本变更

### 新增功能
- **control_window**: 支持四位置车窗独立控制
- **control_door**: 支持四位置车门独立锁止/解锁
- **control_trunk**: 支持后备箱、充电口、前备箱控制

### 位置参数
- 车窗/车门统一使用四位置：front_left, front_right, rear_left, rear_right
- 支持 `all` 作为所有位置的快捷方式
