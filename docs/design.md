# Design System

<!-- impeccable:design-schema 1 -->

## World

精密汽车仪表舱（Precision Instrument Cabin）。浅色铝质座舱壳 + 深色玻璃仪表岛。拒绝 SaaS 卡片墙、淡色圆角「友好」按钮、AI 紫/霓虹光晕。

## Color strategy

Restrained。中性铝灰为主，石墨为墨，一点车漆红只用于主操作与车速强调。

| Token | Value | Role |
|---|---|---|
| `--bg` | `#ECECEF` | 舱壁 |
| `--bg-elevated` | `#F7F7F8` | 抬起面 |
| `--bg-chat` | `#F4F4F6` | 对话区 |
| `--ink` | `#121316` | 主文字 |
| `--ink-2` | `#5A5E66` | 次级 |
| `--ink-3` | `#8B909A` | 弱化 |
| `--line` | `#D8D9DE` | 分割 |
| `--accent` | `#B91C1C` | 主操作 / 强调（克制） |
| `--cluster` | `#0C0D10` | 仪表岛底 |
| `--cluster-face` | `#14161B` | 表盘面 |
| `--phosphor` | `#E8EAED` | 表盘读数 |
| `--ok` | `#2F6B4F` | 成功（深绿，非薄荷绿） |
| `--warn` | `#A15C12` | 警告 |

## Typography

- UI：`Noto Sans SC` 单一家族
- 仪表数字：`Rajdhani` + `tabular-nums`（测速/电量）
- 禁止展示衬线抢戏；标题靠字重与字距，不靠装饰字体

## Layout

- 驾驶页左右 50/50 保留
- 右侧自上而下：深色仪表岛（主视觉）→ 空间化五区气候座舱图 → 状态带（媒体/导航/ADAS）→ 次级舱控矩阵
- 禁止同构「标题+卡片列表」无限堆叠

## Controls

- 主按钮：石墨实底、8–10px 圆角、白字；禁用发灰而非半透明乱闪
- 次按钮：细线框，无填充
- 禁止：大圆角胶囊主按钮、薄荷绿底、彩色描边光晕
- 座位切换：小型分段控件，选中态用石墨底而非高饱和色块

## Motion

- 仪表：车速针 / 电量弧连续插值（spring），非跳变
- 状态变更：150–250ms ease-out；气候区点亮用 opacity + 轻微 scale
- 禁止整页入场 stagger 表演

## Depth

- 仪表岛：内凹表盘 + 外环金属感边（细高光边，非发光光晕）
- 浅色区：单层轻阴影或发丝线，二选一

## Direction contract (drive surface)

THESIS: 右侧是「正在运转的仪表舱」，不是设置列表。  
OWN-WORLD: 铝灰壳 + 深色玻璃岛 + 石墨控件 + 一点车漆红。  
STORY: 用户一眼看到车速/电量/气候空间关系，再说给小特听。  
FIRST VIEWPORT: 左对话；右顶仪表岛占视觉权重，其下座舱平面图。  
FORM: grounded#3 精密仪表舱；staging 借用登机牌式「状态带就地更新」；seed `6f995f2a`。
