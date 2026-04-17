<div align="center">

# AgenticHR

### AI 驱动的开源招聘助手

**从 500 份简历到 5 场面试 —— 全自动化**

从 Boss直聘 自动采集简历 → AI 智能筛选评估 → 一键安排面试 → 自动创建腾讯会议 → 飞书通知全员

[![License: MIT](https://img.shields.io/badge/License-MIT-green.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/Python-3.11+-blue.svg)](https://python.org)
[![Vue 3](https://img.shields.io/badge/Vue-3-brightgreen.svg)](https://vuejs.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688.svg)](https://fastapi.tiangolo.com)

[快速开始](#-快速开始) · [功能介绍](#-功能亮点) · [截图预览](#-截图预览) · [技术架构](#-技术架构)

</div>

---

## 为什么需要 AgenticHR？

HR 团队每天淹没在重复劳动中：手动复制简历、逐份比对条件、协调面试时间、创建会议链接、挨个发通知……

**AgenticHR 把整条招聘流水线自动化了。**

| 以前（手动） | 现在（AgenticHR） |
|:---|:---|
| 在 Boss直聘 一个个复制候选人信息 | Edge 扩展一键批量采集 + PDF 简历自动下载 |
| 逐份阅读简历，凭经验判断是否合适 | AI 自动打分排名，给出优势/风险分析 |
| 微信问面试官"你明天几点有空？" | 自动读取飞书日历，智能避开冲突 |
| 手动创建腾讯会议、复制链接、分别转发 | 一个按钮 —— 会议自动创建，双方自动收到通知 |
| 用 Excel 跟踪招聘进度 | 工作台实时看板，数据一目了然 |

**关键差异：完全免费、开源、自托管、数据不出企业。**

---

## ✨ 功能亮点

### 📋 简历自动采集
- **Edge 扩展**深度集成 Boss直聘 —— 批量采集候选人信息 + PDF 简历
- 自动求简历功能（对新打招呼的候选人自动发送求简历请求）
- 手机号/邮箱自动去重，智能合并多来源数据

### 🤖 AI 智能筛选
- 配置岗位硬性要求（学历、年限、技能、薪资范围）
- AI 综合评估：打分 + 优势分析 + 风险提示 + 录用建议
- 支持智谱 GLM-4 或任意 OpenAI 兼容 API
- PDF 简历视觉解析（GLM-4V 图片模式）

### 📅 面试自动化
- 飞书日历忙闲实时查询，智能避开面试官已有日程
- 重复安排检测、过去时间拦截、冲突预警
- **腾讯会议自动创建** —— 多账号池，并行面试自动分配不同主持人

### 🔔 全渠道通知
- **飞书消息**：候选人摘要 + PDF 简历附件发送给面试官
- **飞书日历**：自动创建日历事件，包含会议链接和参会人
- **候选人通知模板**：HR 一键复制发给候选人
- 每条通知独立追踪发送状态

### 🛡️ 防呆设计
- 全局输入校验（手机号、邮箱、薪资范围、时间范围）
- 危险操作需输入"确认清空"才能执行
- 外键保护 —— 有面试的面试官/岗位无法删除
- 网络断连横幅提醒、重复发送检测

### 👥 多用户隔离
- 登录注册系统（JWT 认证）
- 每个 HR 看到的简历、岗位、面试完全独立
- 面试官资源共享（同一个面试官可被不同 HR 安排）

---

## 📸 截图预览

<table>
  <tr>
    <td align="center"><b>工作台</b><br>数据概览 + 系统状态 + 快速开始引导</td>
    <td align="center"><b>面试安排</b><br>候选人详情 + 面试官 + 时间 + 会议链接</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/dashboard.png" width="480"></td>
    <td><img src="docs/screenshots/interviews.png" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>岗位管理</b><br>硬性条件配置 + 一键筛选 + AI 评估</td>
    <td align="center"><b>面试官管理</b><br>飞书 Open ID 自动查询 + 日程同步</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/jobs.png" width="480"></td>
    <td><img src="docs/screenshots/interviewers.png" width="480"></td>
  </tr>
  <tr>
    <td align="center"><b>设置</b><br>AI / Boss直聘 / 飞书 配置状态一览</td>
    <td align="center"><b>登录</b><br>多用户系统，数据隔离</td>
  </tr>
  <tr>
    <td><img src="docs/screenshots/settings.png" width="480"></td>
    <td><img src="docs/screenshots/login.png" width="480"></td>
  </tr>
</table>

---

## 🏗️ 技术架构

```
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│  Edge 扩展     │────▶│  FastAPI 后端     │────▶│  SQLite 数据库   │
│  (Boss直聘采集)  │     │  (Python 3.11+)  │     │  (单文件,WAL模式)│
└─────────────────┘     └────────┬─────────┘     └─────────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ▼            ▼            ▼
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │  飞书API  │ │ 腾讯会议  │ │  AI 大模型│
              │  消息/日历 │ │ 自动创建  │ │  评估/解析│
              └──────────┘ └──────────┘ └──────────┘

┌─────────────────────────────────────────────────┐
│          Vue 3 + Element Plus 前端              │
│  工作台 │ 简历库 │ 岗位 │ 面试 │ 通知 │ 设置   │
└─────────────────────────────────────────────────┘
```

| 层级 | 技术栈 |
|:---|:---|
| **后端** | Python 3.11+、FastAPI、SQLAlchemy、SQLite (WAL) |
| **前端** | Vue 3 (Composition API)、Element Plus |
| **浏览器扩展** | Manifest V3（Edge/Chromium 系列浏览器通用） |
| **集成服务** | 飞书 Open API、腾讯会议 (Playwright)、智谱 GLM / OpenAI 兼容 |

---

## 🚀 快速开始

### 方式一：Windows 一键运行（推荐，无需任何环境）

1. 从 [Releases](https://github.com/liboze2026/AgenticHR/releases) 下载 `招聘助手-v1.0-Windows.zip`
2. 解压到任意位置
3. 双击 `招聘助手.exe`
4. 浏览器自动打开，注册账号即可使用

### 方式二：源码运行（开发者）

```bash
# 1. 克隆项目
git clone https://github.com/liboze2026/AgenticHR.git
cd AgenticHR

# 2. 创建虚拟环境
python -m venv .venv
.venv\Scripts\activate        # Windows
# source .venv/bin/activate   # macOS/Linux

# 3. 安装依赖
pip install -r requirements.txt
pip install bcrypt PyJWT       # 认证依赖
playwright install chromium    # 腾讯会议自动化（可选）

# 4. 配置
cp .env.example .env
# 编辑 .env 填入飞书密钥、AI密钥等

# 5. 启动
python launcher.py
# 浏览器自动打开 http://127.0.0.1:8000
```

### 安装 Edge 扩展（采集 Boss直聘 简历）

1. 打开 Edge（Windows 自带） → 地址栏输入 `edge://extensions`
2. 打开左下角 **开发人员模式**
3. 点击 **加载解压缩的扩展** → 选择 `edge_extension/` 文件夹
4. 打开 Boss直聘 → 点击扩展图标 → 登录 → 开始采集

---

## 📁 项目结构

```
AgenticHR/
├── app/                          # 后端
│   ├── main.py                   # FastAPI 入口 + JWT 中间件
│   ├── config.py                 # 配置管理 (pydantic-settings)
│   ├── database.py               # 数据库 + 自动迁移
│   ├── adapters/                  # 外部服务适配器
│   │   ├── feishu.py             # 飞书 Open API（消息/日历/通讯录）
│   │   ├── feishu_ws.py          # 飞书 WebSocket（机器人消息）
│   │   ├── tencent_meeting_web.py # 腾讯会议浏览器自动化
│   │   ├── ai_provider.py        # AI 大模型 (OpenAI 兼容)
│   │   └── email_sender.py       # 邮件 SMTP
│   └── modules/                   # 业务模块
│       ├── auth/                  # 登录注册 + JWT
│       ├── resume/                # 简历管理 + PDF 解析 + AI 解析
│       ├── screening/             # 岗位管理 + 硬性条件筛选
│       ├── ai_evaluation/         # AI 评估打分
│       ├── scheduling/            # 面试官 + 面试安排
│       ├── meeting/               # 腾讯会议账号池
│       ├── notification/          # 多渠道通知
│       └── feishu_bot/            # 飞书机器人事件处理
├── frontend/                      # Vue 3 前端
│   └── src/views/                 # 7 个页面
├── edge_extension/                # Boss直聘 Edge 扩展
├── launcher.py                    # 一键启动器
├── build_release.py               # Windows 打包脚本
└── .env.example                   # 配置模板
```

---

## ⚙️ 配置说明

| 变量 | 必填 | 说明 |
|:---|:---|:---|
| `FEISHU_APP_ID` | 通知功能需要 | 飞书应用 ID |
| `FEISHU_APP_SECRET` | 通知功能需要 | 飞书应用密钥 |
| `AI_ENABLED` | 否 | 启用 AI 功能 (`true`/`false`) |
| `AI_API_KEY` | AI 功能需要 | 大模型 API Key |
| `AI_BASE_URL` | AI 功能需要 | API 地址（默认智谱） |
| `AI_MODEL` | AI 功能需要 | 模型名称（默认 `glm-4-flash`） |
| `TENCENT_MEETING_ACCOUNTS` | 会议功能需要 | 腾讯会议账号标签，逗号分隔 |
| `SMTP_HOST` | 邮件功能需要 | SMTP 服务器 |
| `SMTP_USER` / `SMTP_PASSWORD` | 邮件功能需要 | SMTP 凭证 |

> 不配置的功能会自动跳过，不影响其他功能使用。

---

## 🗺️ Roadmap

- [x] Boss直聘 Edge 扩展自动采集
- [x] AI 简历评估与打分
- [x] 腾讯会议多账号自动创建
- [x] 飞书消息 + 日历通知
- [x] 多用户登录与数据隔离
- [x] Windows 一键安装包 (.exe)
- [ ] 招聘数据看板与漏斗分析
- [ ] 面试评价/面评系统
- [ ] 人才库管理与二次激活
- [ ] Offer 管理流程
- [ ] 多渠道简历采集（猎聘、智联等）
- [ ] AI 面试能力

---

## 🤝 参与贡献

欢迎提交 Issue 和 Pull Request！

---

## 📄 License

[MIT License](LICENSE)

---

<div align="center">

**用 [Claude Code](https://claude.ai/code) 构建** · **如果对你有帮助，请给个 Star ⭐**

</div>
