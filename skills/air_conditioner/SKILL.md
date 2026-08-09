# Air Conditioner Skill - 智能座舱空调系统 V5

---
name: air_conditioner
description: 控制车内空调系统，支持五区域独立温度和风量控制（前排左/右、后排左/右/中）
metadata:
  functions:
    - name: control
      description: 统一控制空调区域开关，支持智能默认行为
    - name: set_temperature
      description: 设置指定区域的温度（支持多区域同步设置）
    - name: adjust_fan
      description: 调节指定区域的风量档位（支持多区域同步设置）
    - name: set_mode
      description: 设置空调工作模式、风向和循环模式
---

## 区域定义

系统支持 **5个独立空调区域**，每个区域可独立设置温度和风量：

| 区域参数值 | 说明 | 同义词 |
|-----------|------|--------|
| `front_left` | 前排左区（驾驶位） | driver, 驾驶位, 主驾 |
| `front_right` | 前排右区（副驾位） | passenger, 副驾, 副驾驶, 副驾驶位 |
| `rear_left` | 后排左区 | 左后座, 后排左侧 |
| `rear_right` | 后排右区 | 右后座, 后排右侧 |
| `rear_middle` | 后排中区 | 中后座, 后排中间 |

**区域组**: 可用 `zones` 数组同时指定多个区域
- 全车: `["front_left", "front_right", "rear_left", "rear_middle", "rear_right"]`
- 前排: `["front_left", "front_right"]`
- 后排: `["rear_left", "rear_middle", "rear_right"]`
- 左侧: `["front_left", "rear_left"]`
- 右侧: `["front_right", "rear_right"]`

---

## 函数详细说明

### 1. control - 统一开关控制
**功能**：统一控制指定区域空调的开启和关闭

**参数**：
- `enable` (boolean): **必填**，开关状态（true=开, false=关）
- `zones` (array): **可选**，区域列表，如 `["front_left", "rear_right"]`
  - 默认行为见下方逻辑说明
- `auto_mode` (string): **可选**，自动模式类型，默认 `"comfort"`
  - 可选值: `eco`(节能), `auto`(自动), `comfort`(舒适)

**控制逻辑**：
| 场景 | 行为 |
|------|------|
| `enable=true` 且未指定 `zones` | 打开全部5个区域 |
| `enable=false` 且未指定 `zones` | 关闭所有当前已开启的区域 |
| 指定具体 `zones` | 只操作指定区域 |

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "打开空调" | `control(enable=true)` |
| "关闭空调" | `control(enable=false)` |
| "打开前排空调" | `control(enable=true, zones=["front_left", "front_right"])` |
| "关闭后排空调" | `control(enable=false, zones=["rear_left", "rear_middle", "rear_right"])` |
| "打开左后座位空调" | `control(enable=true, zones=["rear_left"])` |
| "关闭副驾空调" | `control(enable=false, zones=["front_right"])` |
| "全车空调打开" | `control(enable=true, zones=["front_left", "front_right", "rear_left", "rear_middle", "rear_right"])` |

---

### 2. set_temperature - 设置温度
**功能**：设置指定区域的温度。如果目标区域空调未开启，会自动开启。

**参数**：
- `value` (number): **必填**，目标温度，范围 16.0-30.0，默认 24.0
- `zones` (array): **可选**，目标区域列表
  - 默认：所有已开启的区域，如果没有开启的则默认前排左区

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "温度调到23度" | `set_temperature(value=23)` |
| "前排温度调到24度" | `set_temperature(value=24, zones=["front_left", "front_right"])` |
| "后排温度调到25度" | `set_temperature(value=25, zones=["rear_left", "rear_middle", "rear_right"])` |
| "副驾调到22度" | `set_temperature(value=22, zones=["front_right"])` |
| "全车温度调到23度" | `set_temperature(value=23, zones=["front_left", "front_right", "rear_left", "rear_middle", "rear_right"])` |

---

### 3. adjust_fan - 调节风量
**功能**：调节指定区域的风量档位。如果目标区域空调未开启，会自动开启。

**参数**：
- `level` (integer): **必填**，风量档位 0-7，默认 3
  - 0: 关闭
  - 1-7: 档位递增
- `zones` (array): **可选**，目标区域列表
  - 默认：所有已开启的区域

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "风量调到3档" | `adjust_fan(level=3)` |
| "风量调大一档"（当前2档）| `adjust_fan(level=3)` |
| "后排风量调大" | `adjust_fan(level=5, zones=["rear_left", "rear_middle", "rear_right"])` |
| "副驾风量调到2档" | `adjust_fan(level=2, zones=["front_right"])` |

---

### 4. set_mode - 设置模式
**功能**：设置空调工作模式和风向。如果所有区域都关闭，会自动开启前排。

**参数**：
- `mode` (string): **可选**，工作模式，默认 `"auto"`
  - 可选值: `cool`(制冷), `heat`(制热), `fan_only`(仅通风), `defrost`(前挡除霜), `defrost_feet`(除霜+脚部), `auto`(自动)
- `direction` (string): **可选**，出风方向，默认 `"auto"`
  - 可选值: `face`(面部), `foot`(脚部), `defrost`(前挡玻璃), `face_foot`(面部+脚部), `auto`(自动)
- `intensity` (string): **可选**，强度，默认 `"normal"`
- `recirculation` (boolean): **可选**，内循环，默认 `false`

**示例**：
| 用户指令 | 调用参数 |
|---------|---------|
| "切换到制冷模式" | `set_mode(mode="cool")` |
| "打开除霜" | `set_mode(mode="defrost")` |
| "风向调到脚部" | `set_mode(direction="foot")` |
| "打开内循环" | `set_mode(recirculation=true)` |

---


## 状态追踪

执行后自动更新 state.json 中对应区域的值：

```json
{
  "air_conditioner": {
    "control": {
      "front_left": true,
      "front_right": false,
      "rear_left": true,
      "rear_middle": false,
      "rear_right": false
    },
    "set_temperature": {
      "front_left": {"value": 22.0, "unit": "celsius"},
      "front_right": {"value": 22.0, "unit": "celsius"},
      "rear_left": {"value": 24.0, "unit": "celsius"},
      "rear_middle": {"value": 22.0, "unit": "celsius"},
      "rear_right": {"value": 22.0, "unit": "celsius"}
    },
    "adjust_fan": {
      "front_left": {"level": 2},
      "front_right": {"level": 2},
      "rear_left": {"level": 3},
      "rear_middle": {"level": 2},
      "rear_right": {"level": 2}
    },
    "set_mode": {
      "mode": "cool",
      "direction": "auto",
      "intensity": "normal",
      "recirculation": false
    }
  }
}
```
