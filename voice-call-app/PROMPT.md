# uni-app 语音通话项目 — 待完成文件提示词

## 项目背景
将现有的 Flask Web 语音通话应用转为 uni-app 项目（打包 Android APK）。后端不变，只重写前端。

## 已完成文件
项目在 `/home/node/.openclaw/workspace/voice-call-app/`，以下文件已写好：
- manifest.json, pages.json, App.vue, main.js, uni.scss
- utils/api.js（所有 API 封装，含 SSE 流式对话、STT 上传、TTS 音频）
- utils/audio.js（Recorder 录音类 + AudioPlayer 播放队列类）
- utils/storage.js（本地存储封装 + KEYS 常量）
- pages/login/login.vue（登录页，完成）

## 还差2个文件

### 文件 1: pages/index/index.vue
主页，自定义底部 Tab 栏（不用原生 tabBar），三个视图 v-if 切换：

**Tab 1 - 最近通话：**
- 大标题"最近通话"，通话记录列表
- 每项：圆形头像+首字、名字、最后一句话、时间、时长
- 点击弹出详情弹窗（消息气泡回放、记忆总结、删除）

**Tab 2 - 拨号：**
- 居中角色名 + 提示 + 绿色圆形拨号按钮
- 点击跳转 `/pages/call/call?token=xxx`

**Tab 3 - 我的：**
- iOS 风格设置卡片列表（#1C1C1E 圆角卡片）
- 子页面用 v-if 覆盖层：个人信息、通话记忆、API配置（LLM/TTS 内置/自定义切换）、上下文设置、通话页面设置
- 余额+充值、统计、版本号

**API 引用：**
```javascript
import { getCallHistory, deleteCallHistory, getBuiltinModels, getModels, getBalance, redeemCard, getMemorySummaries, generateMemory, deleteMemory, updateMemory, setAutoMemory } from '../../utils/api.js';
import { get, set, KEYS } from '../../utils/storage.js';
```

**UI：** 黑色背景 #000，卡片 #1C1C1E，输入框 #2C2C2E，文字白色，次要 #8E8E93，高亮 #0A84FF

---

### 文件 2: pages/call/call.vue
通话页，核心循环：录音 → STT → Chat(SSE) → TTS → 播放 → 继续录音

**布局：**
```
┌──────────────────────┐
│ ← 返回        ⚙设置  │
│      角色名          │
│    通话状态/计时      │
│   [用户说的话]       │
│   [AI说的话]         │
│ [文字输入框]         │
│ 🎤  📹  📞  🔊     │
│ 静音 视频 挂断 免提   │
└──────────────────────┘
```

**功能：**
- 录音：用 Recorder 类（from utils/audio.js）
- STT：submitSTT(token, filePath)
- 流式对话：streamChat(token, messages, options, {onDelta, onComplete, onError})
- TTS 播放：submitTTS 获取音频 → AudioPlayer 队列播放
- 按句切分（。！？.!?\n），每句送 TTS
- 控制按钮：静音、视频（预留）、挂断、免提
- 通话计时实时更新
- 文字输入模式
- 挂断时保存通话记录（saveCallHistory）
- 设置弹窗（从底部滑出）

**API 引用：**
```javascript
import { submitSTT, submitTTS, streamChat, saveCallHistory, generateMemory } from '../../utils/api.js';
import { Recorder, AudioPlayer } from '../../utils/audio.js';
import { get, set, KEYS } from '../../utils/storage.js';
```

**UI：** 黑色通话界面，绿色拨号 #34C759，红色挂断 #FF3B30，控制按钮圆形 rgba(255,255,255,0.15)

---

## 现有后端 API 参考（完整）
后端地址：https://yolanda083-voice-call-test.hf.space

- POST /api/chat — SSE 流式对话，body: {token, messages:[{role,content}], stream:true, model?, custom_api?, custom_prompt?, filter_rules?, max_history?}
- POST /api/stt — 上传音频文件，form: audio=文件, token=xxx
- POST /api/tts — 语音合成，body: {token, text, voice_id?, model?, custom_tts?}，返回音频 arraybuffer
- GET /api/call-history?token=xxx — 返回 {calls:[{id, messages, duration, created_at, memory}]}
- POST /api/call-history — body: {token, messages, duration}
- DELETE /api/call-history — body: {token, call_id}
- GET /api/builtin-models — 返回 {models:["model1","model2"]}
- GET /api/models?base_url=xxx&api_key=xxx — 获取自定义模型列表
- GET /api/account/balance?token=xxx — 返回 {balance_yuan: 0.00}
- POST /api/account/redeem-card?token=xxx — body: {code}
- GET /api/memory/summaries?token=xxx — 返回 {summaries:[{id, text, created_at}]}
- POST /api/memory/generate — body: {token, call_id, messages}
- DELETE /api/memory/summaries — body: {token, id}
- PUT /api/memory/summaries — body: {token, id, text}
- POST /api/memory/auto-setting — body: {token, enabled}

## 原始 Web 版前端代码参考
原始项目在 `/home/node/.openclaw/workspace/voice-call-open/`：
- static/call.js — 通话核心逻辑（约2000行），录音/STT/SSE/TTS 完整实现
- static/login.js — 登录逻辑
- static/setup.js — 设置页逻辑
- templates/ios/call.html — 通话页 HTML+CSS
- templates/ios/login.html — 登录页 HTML+CSS

请参考这些文件的业务逻辑来实现 uni-app 版本。
