# Hardware Skill - 车辆硬控与声光电视觉域

---
name: hardware
description: 控制车窗、灯光、屏幕、后备箱、车门锁等车辆硬件（不包含音量控制，音量由media skill管理）
metadata:
  functions:
    - name: control_window
      description: 控制车窗的开合程度
    - name: control_lighting
      description: 控制车内氛围灯和照明灯的亮度
    - name: control_display
      description: 控制屏幕（中控屏、仪表盘、HUD）的亮度
    - name: trunk_control
      description: 控制后备箱的开启和关闭
    - name: door_lock
      description: 控制车门锁的锁定和解锁
---

## 函数详细说明

### 1. control_window - 车窗控制
**功能**：控制四个车窗的开合程度（百分比）

**参数**：
- `position` (string): 车窗位置，默认 "front_left"（主驾/左前）
  - 可选值: "front_left"(左前/主驾), "front_right"(右前/副驾), "rear_left"(左后), "rear_right"(右后), "all"(全部)
- `percent` (number/string): 开合程度 0-100，默认 50
  - 0 = 完全关闭，100 = 完全打开
  - 支持相对调整: "高一点"(当前+20), "低一点"(当前-20)

**初始状态**：全部车窗关闭 (0)

**示例**：
- "打开车窗" → control_window(percent=50)
- "把左前窗打开到80%" → control_window(position="front_left", percent=80)
- "副驾车窗关小一点" → control_window(position="front_right", percent="低一点")

---

### 2. control_lighting - 灯光控制
**功能**：控制氛围灯和照明灯的亮度

**参数**：
- `target` (string): 灯光目标，默认 "lighting"（照明灯）
  - 可选值: "lighting"(照明灯), "ambient"(氛围灯)
- `brightness` (number): 亮度 0-100，默认 50
  - 0 = 关闭，100 = 最亮

**初始状态**：照明灯0（关闭），氛围灯0（关闭）

**示例**：
- "打开车内灯" → control_lighting(brightness=50)
- "氛围灯调到30%" → control_lighting(target="ambient", brightness=30)
- "把灯关掉" → control_lighting(brightness=0)

---

### 3. control_display - 屏幕显示控制
**功能**：控制中控屏、仪表盘、HUD的亮度

**参数**：
- `target` (string): 显示目标，默认 "center_screen"（中控屏）
  - 可选值: "center_screen"(中控屏), "instrument"(仪表盘), "hud"(HUD), "all"(全部)
- `brightness` (number): 亮度 0-100，默认 50

**初始状态**：中控屏50，仪表盘50，HUD50

**示例**：
- "屏幕调亮一点" → control_display(brightness=70)
- "仪表盘亮度调到30" → control_display(target="instrument", brightness=30)
- "关掉HUD" → control_display(target="hud", brightness=0)

---

### 4. trunk_control - 后备箱控制
**功能**：控制后备箱的开启和关闭

**参数**：
- `action` (string): 动作，默认 "open"
  - 可选值: "open"(打开), "close"(关闭)

**初始状态**：关闭 (false)

**示例**：
- "打开后备箱" → trunk_control(action="open")
- "关闭后备箱" → trunk_control(action="close")

---

### 5. door_lock - 车门锁控制
**功能**：控制四个车门锁的锁定和解锁

**参数**：
- `position` (string): 车门位置，默认 "front_left"（主驾/左前）
  - 可选值: "front_left"(左前/主驾), "front_right"(右前/副驾), "rear_left"(左后), "rear_right"(右后), "all"(全部)
- `action` (string): 动作，默认 "lock"
  - 可选值: "lock"(上锁), "unlock"(解锁)

**初始状态**：全部车门上锁 (lock)

**示例**：
- "解锁" → door_lock(action="unlock")
- "锁上全部车门" → door_lock(position="all", action="lock")
- "解锁副驾车门" → door_lock(position="front_right", action="unlock")
