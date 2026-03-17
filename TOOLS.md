# TOOLS.md - Local Notes

Skills define _how_ tools work. This file is for _your_ specifics — the stuff that's unique to your setup.

## What Goes Here

Things like:

- Camera names and locations
- SSH hosts and aliases
- Preferred voices for TTS
- Speaker/room names
- Device nicknames
- Anything environment-specific

## Examples

```markdown
### Cameras

- living-room → Main area, 180° wide angle
- front-door → Entrance, motion-triggered

### SSH

- home-server → 192.168.1.100, user: admin

### TTS

- Preferred voice: "Nova" (warm, slightly British)
- Default speaker: Kitchen HomePod
```

## Why Separate?

Skills are shared. Your setup is yours. Keeping them apart means you can update skills without losing your notes, and share skills without leaking your infrastructure.

## ⚠️ 容器重启恢复

容器重启后，npm 全局工具（agent-browser、mcporter、clawhub、gh）、Chromium 浏览器引擎、系统依赖库、ClawHub 技能都会丢失。

**恢复方法**（任何会话都可以执行，不限网页端）：
```bash
bash /home/node/.openclaw/workspace/setup/restore.sh
```
脚本约 2-3 分钟自动完成所有恢复。脚本存在持久化的 workspace 目录，不会被重启清除。

**判断是否需要恢复**：如果 `which agent-browser` 找不到，说明需要跑恢复脚本。

## 已安装的全局工具

路径都在 `~/.npm-global/bin/`（已通过 `tools.exec.pathPrepend` 配置到 PATH）

| 工具 | 用途 |
|------|------|
| `agent-browser` | 浏览器自动化 CLI |
| `mcporter` | MCP 服务器连接 |
| `clawhub` | 技能搜索安装（已登录 @yumiao083-w） |
| `gh` | GitHub CLI |

## ClawHub

- 已登录账号: @yumiao083-w
- Token: `clh_7mdwKoqdW6rmlidgVQMCGQwMiCetglcCmfwut2eRJx4`
- 安装技能: `clawhub install <name> --dir /app/skills --no-input`
- 搜索间隔 10s+ 避免限速

### Tavily

- API Key: `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`
- Endpoint: `https://api.tavily.com/search`
- Free tier: 1,000 searches/month

### Telegram

- Bot: 袁朗 (@yuanlang_love_bot)
- Bot Token: 8411509133:AAH1zsVwHwLkzQLYvON0AbGAoGeFg3tI56M
- 用途: yuan 项目语音聊天 + 跨平台记忆共享
- 用户 TG 账号: 虚拟号注册，已开 2FA，通过 Telegram X 登录

### Discord

- 服务器: 郁邈的小家 (ID: 1479437425146069052)
- 常规频道 (ID: 1479437426744103056)
- 用户: fhwndif / W (ID: 1395950823355322388)
- Bot: 小O (ID: 1479436588042682390)

### GitHub

- 仓库: yumiao083-w/yumiao083-w.github.io
- Pages 站点: https://yumiao083-w.github.io
- 认证: PAT token 已配置在 git remote URL 中（ghp_ 开头）
- 用户名: yumiao083-w
- 分支: main

---

Add whatever helps you do your job. This is your cheat sheet.
