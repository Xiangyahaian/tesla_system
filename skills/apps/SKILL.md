# Apps Skill - 第三方应用生态域

---
name: apps
description: 管理第三方应用的启动和关闭，仅支持已安装的应用列表中的应用
metadata:
  functions:
    - name: launch_app
      description: 启动或关闭指定的第三方应用（仅限已安装应用列表中的App）
---

## 已安装应用列表

系统仅支持以下应用，**不在列表中的应用将返回"没有安装这个软件"**。

| 应用名称 | 别名/简称 |
|---------|----------|
| 网易云音乐 | 网易云 |
| QQ | qq |
| 微信 | wechat |
| 拼多多 | pdd、拼夕夕 |
| 高德地图 | 高德 |
| 腾讯地图 | - |
| 爱奇艺视频 | 爱奇艺 |
| 邮箱 | 邮件、email |
| 腾讯视频 | - |
| 飞书 | lark |
| 支付宝 | - |
| 美团 | - |
| 携程 | - |
| 淘宝 | taobao |
| 腾讯会议 | 会议 |
| 钉钉 | dingtalk |
| QQ音乐 | - |
| 百度 | - |

## 函数详细说明

### 1. launch_app - 应用启动/关闭
**功能**：启动或关闭指定的第三方应用

**注意**：仅支持上述"已安装应用列表"中的应用，其他应用将返回"没有安装这个软件"

**参数**：
- `state_file` (string): 状态文件路径（系统自动传入）
- `app_name` (string): 应用名称，默认 ""
- `action` (string): 动作，默认 "open"
  - 可选值: "open"(打开), "close"(关闭)

**示例**：
- "打开拼多多" → launch_app(app_name="拼多多", action="open")
- "关闭微信" → launch_app(app_name="微信", action="close")
- "启动网易云音乐" → launch_app(app_name="网易云音乐", action="open")
