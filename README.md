# GUI Agent Lite

<p align="center">
  <b>截图 → VLM 分析 → 操控屏幕 → 完成任务</b><br>
  一个轻量级、跨平台的桌面 GUI 自动化 Agent<br>
  Screenshot → VLM → Control → Done — A lightweight, cross-platform desktop automation agent
</p>

---

## 💡 这是什么 / What is this

GUI Agent Lite 是一个基于**视觉语言模型 (VLM)** 的桌面自动化工具。它会：
1. 📸 截取当前屏幕
2. 🤖 发送给 VLM（如 Kimi、GPT-4o）分析
3. 🎯 模型返回 "在坐标 [x, y] 双击"
4. 🖱️ Agent 执行鼠标/键盘操作
5. 🔄 再次截图，循环直到任务完成

不需要写代码、不需要配置流程 —— **用自然语言告诉它你要做什么就行**。

GUI Agent Lite is a desktop automation agent powered by **Vision Language Models**. Just tell it what to do in natural language, and it will iteratively screenshot, analyze, and control your screen to complete the task.

---

## ✨ 特性 / Features

- 🖥️ **浮窗交互** — 右下角小窗口，始终置顶，不挡工作区
- 🤖 **VLM 驱动** — 支持任意 OpenAI 兼容 API（Kimi、GPT-4o、UI-TARS 等）
- 🌍 **跨平台** — macOS (cliclick + AppleScript) / Windows (pyautogui)，自动适配
- 🖱️ **可靠键鼠操控** — 针对 macOS 15.4+ 做了专项适配，解决 pyautogui 失效问题
- 💾 **多配置管理** — 保存/切换/删除多套 API 配置，一键切换模型
- 📸 **截图存档** — 每次任务自动创建文件夹，保存全部截图，方便调试
- 🧠 **记忆系统** — 学习成功的操作经验，下次遇到类似任务更高效
- 📐 **Grounding 测试工具** — 独立工具，框选取坐标，验证模型视觉定位精度
- 🌓 **深色/浅色主题** — 适配系统风格
- ⚡ **流式输出** — 实时显示模型思考过程

---

## 🚀 快速开始 / Quick Start

### macOS

```bash
# 1. 安装系统依赖
brew install cliclick

# 2. 安装 Python 依赖 (建议用 conda/venv)
pip install -r requirements.txt

# 3. 授予辅助功能权限 ⚠️ 必须
#    系统设置 → 隐私与安全性 → 辅助功能 → 添加终端 → 开启

# 4. 启动
python run.py
```

### Windows

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 启动 (Windows 无需额外系统依赖)
python run.py
```

> 启动后点击 ⚙ 配置 API，然后输入任务，点 ▶ 开始。

---

## 🎛️ 配置 / Configuration

支持**多套 API 配置**，一键切换模型：

1. 点 ⚙ 打开配置管理器
2. 填写配置名称（如 "Kimi"、"GPT-4o"、"UI-TARS"）
3. 填入 API Key、Base URL、Model
4. 💾 保存为新配置
5. 主界面下拉菜单随时切换

配置保存在 `api_configs.json`（不会被 git 追踪）。也支持从 `.env` 读取初始配置。

### 推荐模型 / Recommended Models

| 模型 | 视觉定位 | 速度 | 推荐场景 |
|------|:------:|:----:|----------|
| **Kimi (moonshot-v1-*-vision)** | ⭐⭐⭐⭐⭐ | 快 | 首选，Grounding 能力强 |
| **GPT-4o** | ⭐⭐⭐⭐⭐ | 中等 | 复杂任务，理解力强 |
| **Qwen2.5-VL 72B** | ⭐⭐⭐⭐ | 中等 | 开源方案首选 |
| **UI-TARS 7B** | ⭐⭐ | 快 | 本地部署，简单任务 |

---

## 📐 Grounding 测试工具 / Grounding Test Tool

```bash
python ground_test.py
```

- 📂 打开或粘贴截图（Cmd+V）
- 🖱️ 在图片上拖拽框选目标区域
- 📋 一键复制归一化坐标 `[0.xxxx, 0.xxxx]`

> 用途：截图 → 框选文件夹图标 → 得到模型应该输出的坐标 → 对比模型实际输出 → 验证 Grounding 精度

---

## 🏗️ 架构 / Architecture

```
┌──────────────┐     ┌──────────────┐     ┌──────────────┐
│   tkinter    │     │   VLM API    │     │   OS Layer   │
│   浮窗 UI    │ ←→  │  OpenAI 兼容  │ ←→  │  鼠标/键盘    │
│              │     │              │     │              │
│ ・任务输入    │     │ ・分析截图    │     │ macOS:       │
│ ・思考展示    │     │ ・返回JSON    │     │   cliclick   │
│ ・配置管理    │     │   {action,   │     │   AppleScript│
│              │     │    start_    │     │   pbcopy     │
│              │     │    point}    │     │              │
│              │     │              │     │ Windows:     │
│              │     │              │     │   pyautogui  │
└──────────────┘     └──────────────┘     └──────────────┘
```

### 工作流程 / Workflow

```
任务: "打开桌面上的 test 文件夹"
  │
  ├─ Step 1: 📸 截图 → 🤖 "桌面可见，test 在坐标 (429, 328)"
  │           🖱️ 双击 (429, 328)
  │
  ├─ Step 2: 📸 截图 → 🤖 "文件夹已打开，任务完成"
  │           ✅ finished
  │
  └─ 完成!
```

---

## 📁 项目结构 / Project Structure

```
gui-agent-lite/
├── run.py                  # 启动入口
├── gui_agent_modern.py     # 主应用 (~1600 行)
├── ground_test.py          # Grounding 坐标测试工具
├── agent_memory.py         # 记忆系统 (经验学习)
├── requirements.txt        # Python 依赖
├── api_configs.json        # API 多配置存储
├── gui_agent_memory.json   # 任务记忆数据
├── screenshots/            # 任务截图存档
├── .env / .env.example     # 环境变量配置
└── README.md
```

---

## 🎮 支持的动作 / Supported Actions

| 动作 | JSON 格式 | 说明 |
|------|-----------|------|
| click | `{"action": "click", "start_point": [0.5, 0.4]}` | 鼠标左键单击 |
| left_double | `{"action": "left_double", "start_point": [0.3, 0.3]}` | 双击打开 |
| right_single | `{"action": "right_single", "start_point": [0.5, 0.4]}` | 右键菜单 |
| type | `{"action": "type", "content": "库里"}` | 输入文本 |
| hotkey | `{"action": "hotkey", "key": "enter"}` | 快捷键 |
| scroll | `{"action": "scroll", "direction": "down"}` | 滚动 |
| drag | `{"action": "drag", "start_point": [0,0], "end_point": [1,1]}` | 拖拽 |
| wait | `{"action": "wait"}` | 等待 5 秒 |
| finished | `{"action": "finished"}` | 任务完成 |
| call_user | `{"action": "call_user"}` | 需要用户介入 |

坐标支持两种格式：归一化 `[0.0, 0.0]` ~ `[1.0, 1.0]`，或绝对像素 `[429, 328]`。

---

## ⚙️ 平台适配细节 / Platform Details

| 操作 | macOS | Windows |
|------|-------|---------|
| 鼠标移动/点击 | cliclick `m:x,y` `c:x,y` | pyautogui |
| 双击 | cliclick 单击 + Cmd+O | pyautogui |
| 键盘输入 | pbcopy + Cmd+V | pyautogui |
| 快捷键 | AppleScript `key code` | pyautogui |
| 截图 | pyautogui | pyautogui |
| 线程安全 | subprocess (跨线程安全) | 主线程 |

> macOS 15.4+ 封杀了 pyautogui 依赖的 `CGEventPost(kCGHIDEventTap)`，本项目已用 cliclick (`kCGSessionEventTap`) + AppleScript 替代。

---

## ⚠️ 权限 / Permissions

### macOS

```
系统设置 → 隐私与安全性 → 辅助功能 → 添加终端/Terminal → 开启
```

启动后会自动检测权限，没授权会提示并禁用开始按钮。

### Windows

无需额外权限，pyautogui 开箱即用。

---

## 🔧 故障排除 / Troubleshooting

| 症状 | 可能原因 | 解决 |
|------|----------|------|
| 鼠标不动 | macOS 辅助功能权限未授予 | 系统设置 → 辅助功能 → 添加终端 |
| 双击不生效 | cliclick 时序问题 | 已改用单击+Cmd+O，重启试试 |
| API 404 | 模型服务挂了 | 检查服务端是否在运行，点 🔗 测试连接 |
| 坐标总是偏 | 模型 Grounding 不准 | 用 `ground_test.py` 对比预期vs实际坐标 |
| 按钮颜色不对 | macOS Aqua 接管 tk.Button | 已修复为 Label |

---

## 📄 License

MIT
