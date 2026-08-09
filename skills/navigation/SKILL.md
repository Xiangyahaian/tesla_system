# Navigation Skill - 导航与出行路线域

---
name: navigation
description: 提供路线规划、导航控制、交通信息查询等功能
metadata:
  functions:
    - name: navigate_to
      description: 导航到指定目的地
    - name: query_traffic
      description: 查询前方或目的地的交通状况
---

## 函数详细说明

### 1. navigate_to - 开始导航
**功能**：导航到指定的目的地

**参数**：
- `position` (string): 目的地名称或地址
  - 如: "天安门", "北京西站", "某某酒店"

**示例**：
- "导航去天安门" → navigate_to(position="天安门")
- "带我去北京西站" → navigate_to(position="北京西站")
- "导航到附近的加油站" → 需先search_poi再navigate_to

---

### 2. query_traffic - 路况查询
**功能**：查询前方或目的地的交通状况

**参数**：
- `destination` (string): 目的地名称或地址，可选
- `keyword` (string): 查询类型，默认 "ahead"
  - 可选值: "ahead"(前方), "destination"(到目的地), "alternative"(备选路线)

**示例**：
- "前面堵不堵" → query_traffic(keyword="ahead")
- "到目的地还要多久" → query_traffic(keyword="destination")
- "到西站的交通状况如何" → query_traffic(destination="西站", keyword="destination")
- "有没有其他路线" → query_traffic(keyword="alternative")
