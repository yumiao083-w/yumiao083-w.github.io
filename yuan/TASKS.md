# yuan 项目任务清单

> 基于公开版语音通话项目的优化，同步到 yuan 项目。
> 公开版地址：https://yolanda083-voice-call-test.hf.space
> 公开版代码：/home/node/.openclaw/workspace/voice-call-test/

---

## 一、语音通话同步优化

yuan 的语音通话代码在 `voice_call.py` + `templates/panel_voice.html`。
公开版已完成以下功能，需要同步移植：

### 1. 通话记忆系统（最重要）

**公开版实现：**
- 通话结束后生成两种内容：
  - **通话小结 (summary)**：袁朗口吻的一句话，挂断后展示
  - **记忆总结 (memory)**：袁朗第一人称日记风格 + 备忘录，注入下次通话 system prompt
- 记忆总结提示词（含人设）见公开版 `app.py` 的 `_generate_call_memory` 函数
- 历史记忆自动注入：每次通话自动加载最近 3 次记忆到 system prompt

**yuan 需要做的：**
- 在 `voice_call.py` 中新增 `_generate_call_memory` 函数
- `save_call_log` 时同时保存 memory 字段
- `_build_voice_system_prompt` 中加载历史通话记忆
- **关键：yuan 的记忆要写入主聊天记忆系统**，让微信聊天也能读取到语音通话的记忆
  - 通话记忆写入 `Memory_Core` 或 `memory_entries.json`
  - 格式参考现有记忆系统

### 2. 上下文保留

**公开版实现：**
- 用户消息带时间戳 `[2026/4/1 17:43:00]`
- 支持设置对话轮数 (max_history)
- 支持加载历史通话上下文

**yuan 需要做的：**
- `stream_chat_and_tts` 中给用户消息加时间戳
- 前端设置页加上下文轮数调整

### 3. 通话录音

**公开版实现：**
- 前端收集所有音频片段（用户录音 webm + AI TTS mp3）
- 后端 ffmpeg 拼接成完整 mp3
- 每段音频分别保存，支持逐条播放
- 打字输入的轮次插入静音段

**yuan 需要做的：**
- yuan 用的是 WebSocket，在 ws 的 `end` 消息中保存音频
- 前端收集音频的逻辑参考公开版 `call.js` 的 `audioSegments`
- 音频保存到 `Voice_Logs/` 目录

### 4. 历史通话界面

**公开版实现：**
- 底部 Tab 栏（最近 / 拨号 / 我的）
- 最近通话列表（苹果风格卡片）
- 详情弹窗（气泡对话 + 时间戳 + 逐条音频播放 + 编辑/删除）
- 记忆总结查看/编辑/重新生成

**yuan 已有的：**
- yuan 的 `panel_voice.html` 已经有类似的 Tab 栏和历史通话列表
- 已有 `showLogDetail`、`toggleLogEdit`、`saveLogEdit`、`deleteLog` 函数
- **需要新增**：逐条音频播放、记忆总结显示/编辑/生成

### 5. 文本显示修复

**公开版修复的 bug：**
- `cleanVoiceTags` 正则改为白名单，不误杀 `(UI)` 等正常文本
- `ThinkingFilter.flush()` 时发送 `text_delta` 给前端（修复漏尾句）
- TTS `_convert_pause_tags` 兼容 `<#1>` 和 `<#0.5#>` 两种格式
- 字幕显示开关（可隐藏通话字幕）

**yuan 需要做的：**
- `panel_voice.html` 中的 `cleanVoiceTags` 函数同步更新
- yuan 的 `tts_engine.py` 检查停顿标签处理

---

## 二、yuan Agent 化改造

### 目标
把 yuan 改造成类似 OpenClaw 的 agent 架构，支持 tools/skill/MCP。

### 规划

#### 阶段1：基础 Agent 框架
- 抽象出 tool 调用接口
- 定义 tool 注册/发现机制
- bot.py 中的 LLM 调用改为支持 function calling

#### 阶段2：内置 Tools
- **联网搜索**：Tavily API（key 已有：`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`）
- **收发邮件**：IMAP/SMTP 或 Gmail API
- **天气查询**：wttr.in 或 Open-Meteo
- **提醒/定时任务**：已有 `recurring_reminders.json`，强化为 tool

#### 阶段3：MCP 接入
- 接入 MCP 协议，支持外部 MCP server
- 美团外卖等可通过 MCP 或模拟点击实现

#### 阶段4：Skill 系统
- 类似 OpenClaw 的 SKILL.md 机制
- 可从 ClawHub 安装技能

### 技术参考
- OpenClaw 架构文档：`/app/docs/`
- MCP 协议：https://modelcontextprotocol.io/
- yuan 现有代码：`bot.py` 6500行，需要先精简

---

## 三、优先级

1. **通话记忆系统** — 最重要，直接影响用户体验
2. **文本显示修复** — bug 修复，快速同步
3. **历史通话界面增强** — 已有基础，加音频播放和记忆管理
4. **上下文保留** — 时间戳 + 轮数控制
5. **通话录音** — 功能完整但复杂度高
6. **Agent 化改造** — 最大工程，需要单独规划

---

## 四、Agent 化重构（2026-04-01 已完成 Phase 0-5）

> 详见 REFACTOR_PLAN.md 和 STRUCTURE.md

### 已完成
- [x] Tool 基类 + ToolRegistry
- [x] 10 个 Tool 迁移（联网搜索、拍一拍、引用回复、撤回、3套提醒、表情包、图片识别、URL抓取）
- [x] 2 个 Skill 迁移（记忆系统、管理命令）
- [x] 4 个 Core 模块（微信连接、消息队列、上下文、监控）
- [x] LLM 引擎（含 function calling 循环）
- [x] 新增 Tool：天气查询（wttr.in）、文件操作（读写/docx/xlsx/pdf）
- [x] 新增 Tool：MCP Bridge（桥接小红书/麦当劳等 MCP Server）
- [x] 新增 Tool：Tavily 联网搜索（替代旧联网搜索）
- [x] 工具记忆修复（tool_calls 结果存入上下文）
- [x] MCP 结果截断（防止 token 爆炸）
- [x] 前端：Tavily + MCP 配置面板（panel_api.html）
- 合计：31+ 个新文件

### 待做
- [ ] **bot.py 最终重写** — 在 Windows 上把新模块 import 进去，逐步删旧代码（7039→~800行）
- [ ] **实际功能测试** — 消息收发、提醒、记忆、管理命令逐个验证

---

## 五、新功能规划

### 5.1 外卖点餐
- **麦当劳 MCP**（最优先）：官方 API，https://open.mcd.cn/mcp/doc，需申请 Token
- **ADB 手机控制**（通用方案）：安卓模拟器 + ADB，可操控美团/饿了么/瑞幸等任何 App
- **参考项目**：foodpanda CLI（Playwright）、Ghost OS + 瑞幸、AutoGLM-Phone（智谱）
- 远期等更多平台出 MCP Server

### 5.2 ADB 手机控制 Tool
- 基于 ADB 协议，截屏/点击/滑动/打字/App管理
- 可用于外卖点单、签到、手机使用监控等
- 参考文档已保存（ADB_MCP_SETUP）

### 5.3 手机使用监控
- MacroDroid（安卓）检测 App 切换 → 发微信消息给 yuan
- yuan 记录使用时长，超时提醒
- 也可通过 ADB 方案实现（定时截屏+AI识别）

### 5.4 待接入的 Tool/MCP
- [ ] 发图片/文件 — wxauto 底层已支持，包装成 Tool
- [ ] 收发邮件 — IMAP/SMTP Tool
- [ ] 设置闹钟 — 扩展现有提醒 Tool
- [ ] 主动消息增强 — 定时触发 / AI 自选下次发消息时间
- [x] ~~联网搜索改造 — 改用 Tavily API 直接调用（key 已有）~~ ✅ 已完成
- [ ] 记忆同步 — 链接到 Notion/备忘录等外部平台
- [x] ~~小红书 MCP — 已有成熟方案~~ ✅ 已接入（回复评论有已知 bug，用 @用户名 一级评论替代）
- [x] ~~麦当劳 MCP~~ ✅ 已验证可用（注释状态，按需加载）
- [ ] ADB 手机控制 Tool
- [ ] 蓝牙设备控制 Tool
- [ ] 语音消息 Tool

---

## 六、参考文件对照

| 功能 | 公开版文件 | yuan 对应文件 |
|------|-----------|--------------|
| 后端主逻辑 | `app.py` | `voice_call.py` + `bot.py` |
| 前端 | `templates/ios/call.html` + `static/call.js` | `templates/panel_voice.html`（内联JS） |
| TTS | `tts.py` | `tts_engine.py` |
| STT | `stt.py` | `voice_call.py` 内的 STT 部分 |
| 工具函数 | `utils.py` | `voice_call.py` 内 |
| 提示词 | `prompt.md` + `app.py` 内 | `prompts/` 目录 |
| 记忆系统 | GitHub API 持久化 | `Memory_Core/` + `memory_entries.json` |
