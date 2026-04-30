# Twilio AI 语音通话

## 阶段1：最小可用版

### 架构
- Twilio 外呼你手机 → ConversationRelay WebSocket → LLM 回复文字 → Twilio TTS 播放
- 备用方案：Gather+Say 模式（不需要 WebSocket，但体验差一些）

### 文件结构
```
twilio-voice-ai/
├── app.py              # 主程序（HTTP + WebSocket）
├── requirements.txt    # Python 依赖
├── Dockerfile          # Docker 部署
├── .env.example        # 环境变量模板
└── README.md           # 本文件
```

### 部署步骤

1. 复制 .env.example 为 .env，填入实际值
2. 部署到 ClawCloud Run（或任何有公网HTTPS的服务器）
3. 确保服务器同时暴露 HTTP(5000) 和 WebSocket(8765) 端口
4. 调用 POST /outbound-call 发起外呼

### API

- `GET /` — 健康检查
- `POST /outbound-call` — 发起外呼（可选参数 `{"to": "+86xxx"}`）
- `POST /twiml` — Twilio 接通后的 TwiML 指令（ConversationRelay 模式）
- `POST /twiml-fallback` — 备用 TwiML（Gather+Say 模式）
- `POST /handle-speech` — 处理语音识别结果（备用模式）
- `POST /call-status` — 通话状态回调

### 两种模式

**ConversationRelay 模式（推荐）：**
- Twilio 自动做 STT + TTS
- WebSocket 通信，只需处理文字
- 体验好，延迟低
- 需要服务器支持 WSS

**Gather+Say 备用模式：**
- 传统 HTTP 回调模式
- 每次用户说完话 → 服务器处理 → 返回 TwiML
- 不需要 WebSocket
- 体验差（每轮都有明显停顿）

### 注意事项
- ConversationRelay 可能需要 Twilio 账号升级才能使用
- 如果 ConversationRelay 不可用，把 /twiml 路由改为指向 /twiml-fallback
- 试用账号只能打已验证的号码（需要先在 Twilio Console 验证你的手机号）
