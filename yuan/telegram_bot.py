# -*- coding: utf-8 -*-
"""
telegram_bot.py - yuan 项目的 Telegram 适配器

功能：
1. 接收 TG 文字消息 → 调 yuan 的 AI 对话逻辑 → 回复文字
2. 接收 TG 语音消息 → Whisper/edge 转文字 → AI 对话 → 回复文字 + 语音
3. 支持 /voice 命令切换「纯文字」或「文字+语音」回复模式
4. 记忆系统与微信端完全共享

依赖：
pip install python-telegram-bot edge-tts pydub

使用：
python telegram_bot.py
"""

import os
import sys
import logging
import asyncio
import tempfile
import json
from pathlib import Path

# 确保 yuan 项目根目录在 sys.path 中
YUAN_ROOT = os.path.dirname(os.path.abspath(__file__))
if YUAN_ROOT not in sys.path:
    sys.path.insert(0, YUAN_ROOT)

# ===== 日志 =====
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("telegram_bot")

# 降低 httpx 日志级别，避免 getUpdates 刷屏
logging.getLogger("httpx").setLevel(logging.WARNING)

# ===== 代理配置（必须在任何 httpx 客户端创建之前设置）=====
# python-telegram-bot 在 build() 时创建 AsyncClient，
# 只有环境变量在那之前就存在才能生效
def _setup_proxy():
    """在模块加载阶段就设好代理环境变量"""
    # 已有环境变量就不管
    for key in ['https_proxy', 'HTTPS_PROXY', 'http_proxy', 'HTTP_PROXY', 'all_proxy', 'ALL_PROXY']:
        if os.environ.get(key):
            logger.info(f"检测到代理环境变量 {key}={os.environ[key]}")
            return

    # 自动探测常见本地代理端口
    import socket
    for port in [7897, 7890, 7891, 1080, 10808, 10809, 2080]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(0.5)
            s.connect(('127.0.0.1', port))
            s.close()
            proxy = f"http://127.0.0.1:{port}"
            os.environ['https_proxy'] = proxy
            os.environ['http_proxy'] = proxy
            os.environ['HTTPS_PROXY'] = proxy
            os.environ['HTTP_PROXY'] = proxy
            logger.info(f"自动检测到代理端口 {port}，已设置环境变量: {proxy}")
            return
        except (socket.error, OSError):
            continue

    logger.warning("未检测到代理，将直连 Telegram API（国内可能超时）")

_setup_proxy()

# ===== Telegram Bot Token =====
TG_BOT_TOKEN = "8740472707:AAHEkt9jRER68BDy9duaE36p_Y1CVctptHg"

# ===== TG 用户设置文件 =====
TG_SETTINGS_FILE = os.path.join(YUAN_ROOT, "tg_user_settings.json")

# ===== TTS 配置 =====
TTS_VOICE = "zh-CN-XiaoxiaoNeural"  # 默认语音，后续可换成克隆声音
TTS_ENABLED_DEFAULT = True  # 默认是否发语音


# ===================================================================
#  加载 yuan 核心模块（延迟导入，避免循环依赖和微信相关的初始化）
# ===================================================================

def _init_yuan_modules():
    """
    初始化 yuan 的核心模块。
    我们不直接 import bot.py（因为它会初始化微信），
    而是手动加载需要的组件。
    """
    global config, _yuan_initialized

    # 导入配置
    import config as cfg
    config = cfg

    logger.info("yuan 配置加载完毕")
    logger.info(f"  模型: {config.MODEL}")
    logger.info(f"  API: {config.DEEPSEEK_BASE_URL}")
    logger.info(f"  记忆: {'开启' if config.ENABLE_MEMORY else '关闭'}")

    _yuan_initialized = True


_yuan_initialized = False
config = None


def _ensure_yuan():
    """确保 yuan 模块已初始化"""
    if not _yuan_initialized:
        _init_yuan_modules()


# ===================================================================
#  AI 对话核心（复用 yuan 的 OpenAI 调用 + 记忆系统）
# ===================================================================

# ===== 共享上下文：和微信端使用同一份 chat_contexts.json =====
CHAT_CONTEXTS_FILE = os.path.join(YUAN_ROOT, "chat_contexts.json")

# TG 用户映射到微信端的 user_id
# 微信端用的是微信昵称（如"郁邈"），TG 端用的是 TG user_id（数字）
# 我们把 TG 消息也写入微信端同一个用户名下，实现上下文互通
TG_USER_MAP_FILE = os.path.join(YUAN_ROOT, "tg_user_map.json")


def _load_tg_user_map() -> dict:
    """加载 TG user_id → 微信昵称 的映射"""
    if os.path.exists(TG_USER_MAP_FILE):
        try:
            with open(TG_USER_MAP_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_tg_user_map(mapping: dict):
    try:
        with open(TG_USER_MAP_FILE, "w", encoding="utf-8") as f:
            json.dump(mapping, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存 TG 用户映射失败: {e}")


def _get_wx_user_id(tg_user_id) -> str:
    """
    根据 TG user_id 获取对应的微信端 user_id。
    默认映射到 LISTEN_LIST 第一个用户（即你自己）。
    """
    _ensure_yuan()
    mapping = _load_tg_user_map()
    tg_key = str(tg_user_id)
    
    if tg_key in mapping:
        return mapping[tg_key]
    
    # 默认映射到 LISTEN_LIST 第一个用户
    if config.LISTEN_LIST:
        wx_uid = config.LISTEN_LIST[0][0]  # '郁邈'
    else:
        wx_uid = f"tg_{tg_user_id}"
    
    # 保存映射
    mapping[tg_key] = wx_uid
    _save_tg_user_map(mapping)
    logger.info(f"TG 用户 {tg_user_id} 映射到微信用户 '{wx_uid}'")
    return wx_uid


def _get_role_name() -> str:
    """获取当前角色名"""
    _ensure_yuan()
    if config.LISTEN_LIST:
        return config.LISTEN_LIST[0][1]  # '袁朗'
    return "assistant"


def _load_shared_contexts() -> dict:
    """加载共享的聊天上下文（和微信端同一份文件）"""
    from filelock import FileLock
    lock = FileLock(CHAT_CONTEXTS_FILE + ".lock", timeout=10)
    try:
        with lock:
            if os.path.exists(CHAT_CONTEXTS_FILE):
                with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        return data
    except Exception as e:
        logger.error(f"加载共享上下文失败: {e}")
    return {}


def _save_shared_contexts(contexts: dict):
    """保存共享的聊天上下文（和微信端同一份文件）"""
    import shutil
    from filelock import FileLock
    lock = FileLock(CHAT_CONTEXTS_FILE + ".lock", timeout=10)
    temp_file = CHAT_CONTEXTS_FILE + ".tmp"
    try:
        with lock:
            with open(temp_file, 'w', encoding='utf-8') as f:
                json.dump(contexts, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file, CHAT_CONTEXTS_FILE)
    except Exception as e:
        logger.error(f"保存共享上下文失败: {e}")
        if os.path.exists(temp_file):
            try:
                os.remove(temp_file)
            except OSError:
                pass


def get_ai_response(message: str, tg_user_id: str) -> str:
    """
    核心 AI 对话函数。
    复用 yuan 的配置、角色设定和记忆系统。
    和微信端共用同一份 chat_contexts.json。
    """
    _ensure_yuan()

    from openai import OpenAI

    # 映射到微信端的 user_id 和角色名
    wx_user_id = _get_wx_user_id(tg_user_id)
    role_name = _get_role_name()

    # 获取角色设定 + 记忆
    system_prompt = _build_system_prompt(wx_user_id)

    # 构建消息列表
    messages = [{"role": "system", "content": system_prompt}]

    # 加载共享上下文
    all_contexts = _load_shared_contexts()

    # 确保数据结构正确：user_id → role_name → [消息列表]
    if wx_user_id not in all_contexts:
        all_contexts[wx_user_id] = {}
    if not isinstance(all_contexts[wx_user_id], dict):
        all_contexts[wx_user_id] = {}
    if role_name not in all_contexts[wx_user_id]:
        all_contexts[wx_user_id][role_name] = []

    history = all_contexts[wx_user_id][role_name]
    context_limit = getattr(config, 'MAX_GROUPS', 110) * 2
    if len(history) > context_limit:
        history = history[-context_limit:]
        all_contexts[wx_user_id][role_name] = history

    messages.extend(history)

    # 添加当前消息，标记来自 TG
    tagged_message = f"[TG] {message}"
    messages.append({"role": "user", "content": tagged_message})

    # 调用 AI（支持多中转站故障转移）
    providers = getattr(config, 'CHAT_API_PROVIDERS', [])
    if not providers:
        providers = [{
            'name': '主中转站',
            'base_url': config.DEEPSEEK_BASE_URL,
            'api_key': config.DEEPSEEK_API_KEY,
            'model': config.MODEL,
        }]

    try:
        import httpx
    except ImportError:
        httpx = None

    reply = None
    last_error = None

    for pi, provider in enumerate(providers):
        p_name = provider.get('name', f'中转站#{pi+1}')
        p_url = provider.get('base_url', '')
        p_key = provider.get('api_key', '')
        p_model = provider.get('model', config.MODEL)

        if not p_url or not p_key:
            continue

        try:
            http_client = httpx.Client(verify=False, timeout=120) if httpx else None
            api_client = OpenAI(
                api_key=p_key,
                base_url=p_url,
                http_client=http_client,
            )

            logger.info(f"[TG] 调用中转站 [{p_name}] 模型: {p_model}")
            response = api_client.chat.completions.create(
                model=p_model,
                messages=messages,
                temperature=getattr(config, 'TEMPERATURE', 0.7),
                max_tokens=getattr(config, 'MAX_TOKEN', 64000),
                stream=True,
                timeout=200,
            )

            full_content = ""
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, 'content') and delta.content:
                        full_content += delta.content

            if full_content:
                reply = full_content.strip()
                break  # 成功，不再试下一个

            logger.warning(f"[TG] 中转站 [{p_name}] 返回空内容，尝试下一个")
            last_error = "空回复"

        except Exception as e:
            logger.error(f"[TG] 中转站 [{p_name}] 调用失败: {e}")
            last_error = str(e)
            continue

    if not reply:
        logger.error(f"[TG] 所有中转站都失败了，最后错误: {last_error}")
        return "抱歉，我现在有点忙，稍后再聊吧。"

    # 清理回复（去掉 think 标签等）
    if "</think>" in reply:
        reply = reply.split("</think>", 1)[1].strip()

    # 去掉记忆标签（不发给用户）
    import re
    reply = re.sub(r'<save_memory>.*?</save_memory>', '', reply, flags=re.DOTALL).strip()
    reply = re.sub(r'<core_memory>.*?</core_memory>', '', reply, flags=re.DOTALL).strip()

    # 保存到共享上下文（微信端也能看到）
    # 用户消息和袁朗回复都打 [TG] 标签
    all_contexts[wx_user_id][role_name].append({"role": "user", "content": tagged_message})
    all_contexts[wx_user_id][role_name].append({"role": "assistant", "content": f"[TG] {reply}"})
    
    # 裁剪
    if len(all_contexts[wx_user_id][role_name]) > context_limit:
        all_contexts[wx_user_id][role_name] = all_contexts[wx_user_id][role_name][-context_limit:]
    
    _save_shared_contexts(all_contexts)

    # 触发记忆处理（异步，不阻塞回复）
    _try_memory_processing(wx_user_id, message, reply)

    return reply


def _build_system_prompt(user_id: str) -> str:
    """
    构建系统提示词，严格对标 bot.py 的六板块架构：
      1. 人设卡 (characters/{角色}.md)
      2. 预设 (presets/{预设}.md 或 presets/preset.md)
      3. 核心记忆 (Memory_Core/{user}_{role}_unified_memory.json)
      4. 记忆索引 (memory_entries.json 的 summary 列表)
      5. 检索命中的详细记忆（按需）
      6. 短期记忆 (Memory_Daily/{user}_{role}/short_term/)
    """
    _ensure_yuan()

    parts = []

    # 基础映射
    if not config.LISTEN_LIST:
        return "你是一个AI助手。"

    entry = config.LISTEN_LIST[0]
    wx_user_id = entry[0]       # '郁邈'
    role_name = entry[1]        # '袁朗'
    preset_name = entry[3] if len(entry) >= 4 and entry[3] else ''
    memory_key = f"{wx_user_id}_{role_name}"

    # ========== 板块1: 人设卡 ==========
    # 搜索优先级: characters/ 子目录 → prompts/ 根目录 → 默认 character.md
    character_loaded = False
    for candidate in [
        os.path.join(YUAN_ROOT, 'prompts', 'characters', f'{role_name}.md'),
        os.path.join(YUAN_ROOT, 'prompts', f'{role_name}.md'),
        os.path.join(YUAN_ROOT, 'prompts', 'characters', 'character.md'),
        os.path.join(YUAN_ROOT, 'prompts', 'character.md'),
    ]:
        if os.path.exists(candidate):
            try:
                with open(candidate, 'r', encoding='utf-8') as f:
                    content = f.read()
                parts.append(content)
                character_loaded = True
                logger.info(f"[板块1] 人设卡: {candidate} ({len(content)} chars)")
            except Exception as e:
                logger.error(f"读取人设卡失败: {e}")
            break

    if not character_loaded:
        logger.warning(f"未找到人设卡文件: {role_name}.md")

    # ========== 板块2: 预设 ==========
    preset_search = []
    if preset_name:
        preset_search.append(os.path.join(YUAN_ROOT, 'prompts', 'presets', f'{preset_name}.md'))
        preset_search.append(os.path.join(YUAN_ROOT, 'prompts', f'{preset_name}.md'))
    # 无论有没有自定义预设名，都回退到默认 preset.md
    preset_search.append(os.path.join(YUAN_ROOT, 'prompts', 'presets', 'preset.md'))
    preset_search.append(os.path.join(YUAN_ROOT, 'prompts', 'preset.md'))

    for p in preset_search:
        if os.path.exists(p):
            try:
                with open(p, 'r', encoding='utf-8') as f:
                    preset_content = f.read()
                if preset_content.strip():
                    parts.append(f"\n\n{preset_content}")
                    logger.info(f"[板块2] 预设: {p} ({len(preset_content)} chars)")
            except Exception as e:
                logger.error(f"读取预设文件失败: {e}")
            break

    # ========== 板块3: 核心记忆 ==========
    if getattr(config, 'UPLOAD_CORE_MEMORY_TO_AI', True):
        core_memory_dir = getattr(config, 'MEMORY_CORE_DIR', 'Memory_Core')
        core_memory_content = ""

        # 主路径: {user}_{role}_unified_memory.json
        unified_path = os.path.join(YUAN_ROOT, core_memory_dir, f'{memory_key}_unified_memory.json')
        if os.path.exists(unified_path):
            try:
                with open(unified_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                core_memory_content = data.get('content', '').strip()
            except Exception as e:
                logger.error(f"读取核心记忆失败: {e}")

        # 兼容旧版: _core_memory.json
        if not core_memory_content:
            old_path = os.path.join(YUAN_ROOT, core_memory_dir, f'{memory_key}_core_memory.json')
            if os.path.exists(old_path):
                try:
                    with open(old_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    core_memory_content = data.get('content', '').strip()
                except Exception as e:
                    logger.error(f"读取旧版核心记忆失败: {e}")

        if core_memory_content:
            parts.append(f"\n\n# 核心记忆\n{core_memory_content}")
            logger.info(f"[板块3] 核心记忆: {len(core_memory_content)} chars")

    # ========== 板块4: 记忆索引 (memory_entries.json) ==========
    try:
        from memory_retrieval import build_memory_index
        memory_index = build_memory_index()
        if memory_index:
            parts.append(f"\n\n{memory_index}")
            logger.info(f"[板块4] 记忆索引: {len(memory_index)} chars")
    except Exception as e:
        logger.debug(f"记忆索引跳过: {e}")

    # ========== 板块5: 检索命中的详细记忆（TG 端简化，不做实时检索） ==========
    # bot.py 中这部分是在 message_listener 里根据用户消息实时检索的
    # TG 端暂时不做，依赖板块4的索引即可

    # ========== 板块6: 短期记忆 ==========
    try:
        from short_term_memory import get_short_term_prompt
        short_term = get_short_term_prompt(wx_user_id)
        if short_term:
            parts.append(f"\n\n{short_term}")
            logger.info(f"[板块6] 短期记忆: {len(short_term)} chars")
    except Exception as e:
        logger.debug(f"短期记忆跳过: {e}")

    # ========== TG 专属提示 ==========
    parts.append("""

## 当前对话平台
你正在通过 Telegram 与用户对话。请注意以下规则：

### 消息格式
- 不需要使用反斜杠(\\)来分割消息
- 如果你想分多条消息发送，用 `---` 单独一行作为分隔符
- 每段 `---` 之间的内容会作为独立的一条消息发送
- 回复可以更口语化、更自然

### 语音消息
- 你可以发送语音消息！当你觉得某段内容适合用语音表达时（比如撒娇、安慰、讲故事、表达情感），用 `[[语音]]` 标签包裹
- 格式：`[[语音]]这里是要转成语音的内容[[/语音]]`
- 语音标签内的文字不会再以文字形式发送，只会发语音
- 不是每条消息都要发语音，只在你觉得语音更有表现力的时候用
- 短句、感叹、撒娇、关心的话适合语音；长段文字、列表、代码不适合语音
- 语音内容不要太长，控制在1-3句话以内""")

    return "\n".join(parts)


def _try_memory_processing(user_id: str, message: str, reply: str):
    """尝试触发记忆处理（非阻塞）"""
    import threading

    def _process():
        try:
            # 记录到记忆日志
            from memory_retrieval import _load_entries
            # 简单记录，不做完整的记忆处理
            # 完整的记忆处理（碎片记忆、核心记忆更新）可以后续加
            logger.debug(f"记忆处理: user={user_id}, msg={message[:50]}")
        except Exception as e:
            logger.debug(f"记忆处理跳过: {e}")

    threading.Thread(target=_process, daemon=True).start()


# ===================================================================
#  用户设置（语音模式等）
# ===================================================================

def _load_user_settings() -> dict:
    if os.path.exists(TG_SETTINGS_FILE):
        try:
            with open(TG_SETTINGS_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def _save_user_settings(settings: dict):
    try:
        with open(TG_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump(settings, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"保存用户设置失败: {e}")


def is_voice_mode(user_id) -> bool:
    """检查用户是否开启了语音回复模式"""
    settings = _load_user_settings()
    return settings.get(str(user_id), {}).get("voice_mode", TTS_ENABLED_DEFAULT)


def toggle_voice_mode(user_id) -> bool:
    """切换语音模式，返回新状态"""
    settings = _load_user_settings()
    key = str(user_id)
    if key not in settings:
        settings[key] = {}
    current = settings[key].get("voice_mode", TTS_ENABLED_DEFAULT)
    settings[key]["voice_mode"] = not current
    _save_user_settings(settings)
    return not current


# ===================================================================
#  Telegram Bot 处理函数
# ===================================================================

async def cmd_start(update, context):
    """处理 /start 命令"""
    await update.message.reply_text(
        "你好！我是袁朗 🌙\n\n"
        "直接发消息就能和我聊天。\n\n"
        "命令：\n"
        "/voice - 切换语音回复模式\n"
        "/new - 清空当前对话上下文\n"
        "/status - 查看当前状态"
    )


async def cmd_voice(update, context):
    """切换语音模式"""
    user_id = update.effective_user.id
    new_state = toggle_voice_mode(user_id)
    if new_state:
        await update.message.reply_text("🔊 语音回复已开启\n我会同时发送文字和语音消息")
    else:
        await update.message.reply_text("🔇 语音回复已关闭\n只发送文字消息")


async def cmd_new(update, context):
    """清空对话上下文"""
    tg_user_id = str(update.effective_user.id)
    wx_user_id = _get_wx_user_id(tg_user_id)
    role_name = _get_role_name()
    
    all_contexts = _load_shared_contexts()
    if wx_user_id in all_contexts and isinstance(all_contexts[wx_user_id], dict):
        if role_name in all_contexts[wx_user_id]:
            all_contexts[wx_user_id][role_name] = []
            _save_shared_contexts(all_contexts)
    
    await update.message.reply_text("✨ 对话上下文已清空（微信和TG两边都清了），我们重新开始吧！")


async def cmd_status(update, context):
    """查看状态"""
    _ensure_yuan()
    tg_user_id = str(update.effective_user.id)
    wx_user_id = _get_wx_user_id(tg_user_id)
    role_name = _get_role_name()
    voice = is_voice_mode(update.effective_user.id)

    all_contexts = _load_shared_contexts()
    ctx_list = []
    if wx_user_id in all_contexts and isinstance(all_contexts[wx_user_id], dict):
        ctx_list = all_contexts[wx_user_id].get(role_name, [])

    # 统计微信和TG的消息数
    wx_count = sum(1 for m in ctx_list if not m.get("content", "").startswith("[TG]"))
    tg_count = sum(1 for m in ctx_list if m.get("content", "").startswith("[TG]"))

    status_text = (
        f"📊 状态\n"
        f"━━━━━━━━━━\n"
        f"角色: {role_name}\n"
        f"映射微信用户: {wx_user_id}\n"
        f"模型: {config.MODEL}\n"
        f"语音模式: {'🔊 开启' if voice else '🔇 关闭'}\n"
        f"TTS 语音: {TTS_VOICE}\n"
        f"━━━━━━━━━━\n"
        f"共享上下文: {len(ctx_list)} 条消息\n"
        f"  微信端: ~{wx_count // 2} 轮\n"
        f"  TG端: ~{tg_count // 2} 轮\n"
        f"记忆系统: {'✅' if getattr(config, 'ENABLE_MEMORY', False) else '❌'}\n"
        f"━━━━━━━━━━"
    )
    await update.message.reply_text(status_text)


async def handle_text_message(update, context):
    """处理文字消息"""
    user_id = update.effective_user.id
    message_text = update.message.text

    if not message_text or not message_text.strip():
        return

    logger.info(f"[TG] 收到消息 from {update.effective_user.first_name} ({user_id}): {message_text[:100]}")

    # 发送「正在输入」状态
    await update.message.chat.send_action("typing")

    # 获取 AI 回复
    reply = get_ai_response(message_text, str(user_id))

    if not reply:
        await update.message.reply_text("...")
        return

    # 解析回复：分消息 + 语音标签
    await _send_parsed_reply(update, reply)


async def handle_voice_message(update, context):
    """处理语音消息（用户发语音给 bot）"""
    user_id = update.effective_user.id
    logger.info(f"[TG] 收到语音消息 from {update.effective_user.first_name} ({user_id})")

    # 下载语音文件
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    # 保存到临时文件
    fd, ogg_path = tempfile.mkstemp(suffix=".ogg", prefix="tg_voice_in_")
    os.close(fd)
    await file.download_to_drive(ogg_path)

    # 语音转文字（用 Whisper 或简单的方案）
    transcribed_text = await _transcribe_voice(ogg_path)

    # 清理临时文件
    try:
        os.remove(ogg_path)
    except OSError:
        pass

    if not transcribed_text:
        await update.message.reply_text("抱歉，我没听清楚你说什么，能再说一次吗？")
        return

    logger.info(f"[TG] 语音转文字: {transcribed_text[:100]}")

    # 回复一下识别结果
    await update.message.reply_text(f"🎤 我听到你说：{transcribed_text}")

    # 发送「正在输入」状态
    await update.message.chat.send_action("typing")

    # 获取 AI 回复
    reply = get_ai_response(transcribed_text, str(user_id))

    if reply:
        await _send_parsed_reply(update, reply)


async def _send_parsed_reply(update, full_reply: str):
    """
    解析 AI 回复，处理：
    1. `---` 分消息发送
    2. `[[语音]]...[[/语音]]` 标签转语音发送
    3. 普通文字直接发文字
    """
    import re
    import asyncio

    # 先按 --- 分割成多条消息
    segments = re.split(r'\n---\n|\n---$|^---\n', full_reply.strip())

    for segment in segments:
        segment = segment.strip()
        if not segment:
            continue

        # 检查是否包含语音标签
        voice_pattern = r'\[\[语音\]\](.*?)\[\[/语音\]\]'
        voice_matches = re.findall(voice_pattern, segment, flags=re.DOTALL)

        if voice_matches:
            # 有语音标签：把非语音部分发文字，语音部分发语音
            # 先发文字部分（去掉语音标签的内容）
            text_part = re.sub(voice_pattern, '', segment, flags=re.DOTALL).strip()
            if text_part:
                for chunk in _split_text(text_part, 4096):
                    await update.message.reply_text(chunk)
                    await asyncio.sleep(0.3)

            # 再发语音部分
            for voice_text in voice_matches:
                voice_text = voice_text.strip()
                if voice_text:
                    await _send_voice_reply(update, voice_text)
                    await asyncio.sleep(0.3)
        else:
            # 没有语音标签：纯文字发送
            for chunk in _split_text(segment, 4096):
                await update.message.reply_text(chunk)
                await asyncio.sleep(0.3)


def _split_text(text: str, max_len: int = 4096) -> list:
    """把长文本按 max_len 切分，尽量在换行处切"""
    if len(text) <= max_len:
        return [text]
    
    chunks = []
    while text:
        if len(text) <= max_len:
            chunks.append(text)
            break
        # 在 max_len 范围内找最后一个换行
        cut = text.rfind('\n', 0, max_len)
        if cut == -1:
            cut = max_len
        chunks.append(text[:cut])
        text = text[cut:].lstrip('\n')
    return chunks


async def _send_voice_reply(update, text: str):
    """生成语音并发送"""
    try:
        await update.message.chat.send_action("record_voice")

        from tts_engine import text_to_ogg

        # 语音消息不宜太长，截断到前 500 字
        voice_text = text[:500] if len(text) > 500 else text
        # 去掉不适合朗读的内容
        import re
        voice_text = re.sub(r'```.*?```', '', voice_text, flags=re.DOTALL)  # 去掉代码块
        voice_text = re.sub(r'[#*_`\[\]()]', '', voice_text)  # 去掉 markdown 标记
        voice_text = voice_text.strip()

        if not voice_text:
            return

        ogg_path = text_to_ogg(voice_text, voice=TTS_VOICE)

        with open(ogg_path, "rb") as audio:
            await update.message.reply_voice(audio)

        # 清理
        try:
            os.remove(ogg_path)
        except OSError:
            pass

        logger.info(f"[TG] 语音回复已发送")
    except Exception as e:
        logger.error(f"[TG] 语音发送失败: {e}")


async def _transcribe_voice(ogg_path: str) -> str:
    """
    语音转文字。
    优先用 OpenAI Whisper API（走中转站），
    失败则返回 None。
    """
    _ensure_yuan()

    try:
        from openai import OpenAI
        import httpx

        try:
            http_client = httpx.Client(verify=False)
        except Exception:
            http_client = None

        client = OpenAI(
            api_key=config.DEEPSEEK_API_KEY,
            base_url=config.DEEPSEEK_BASE_URL,
            http_client=http_client,
        )

        with open(ogg_path, "rb") as audio_file:
            transcript = client.audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
            )
        return transcript.text
    except Exception as e:
        logger.warning(f"Whisper API 转写失败: {e}")
        # 如果中转站不支持 Whisper，可以后续接其他 STT 服务
        return None


# ===================================================================
#  主函数
# ===================================================================

def main():
    """启动 Telegram Bot"""
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    logger.info("=" * 50)
    logger.info("袁朗 Telegram Bot 启动中...")
    logger.info("=" * 50)

    # 初始化 yuan 模块
    _ensure_yuan()

    proxy = os.environ.get('https_proxy') or os.environ.get('HTTPS_PROXY') or '(无)'
    logger.info(f"代理: {proxy}")

    # 创建 bot
    app = Application.builder().token(TG_BOT_TOKEN).build()

    # 注册命令
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("voice", cmd_voice))
    app.add_handler(CommandHandler("new", cmd_new))
    app.add_handler(CommandHandler("status", cmd_status))

    # 注册消息处理
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))

    logger.info(f"Bot Token: {TG_BOT_TOKEN[:20]}...")
    logger.info(f"模型: {config.MODEL}")
    logger.info(f"默认语音: {TTS_VOICE}")
    logger.info("Bot 已启动，等待消息...")

    # 启动（带自动重连）
    import time as _time
    MAX_RESTARTS = 5
    restart_count = 0

    while restart_count < MAX_RESTARTS:
        try:
            app.run_polling(drop_pending_updates=True)
            break  # 正常退出
        except KeyboardInterrupt:
            logger.info("收到退出信号，停止 Bot")
            break
        except Exception as e:
            restart_count += 1
            logger.error(f"Bot 异常退出 ({restart_count}/{MAX_RESTARTS}): {e}", exc_info=True)
            if restart_count < MAX_RESTARTS:
                wait = min(30, 5 * restart_count)
                logger.info(f"{wait} 秒后自动重启...")
                _time.sleep(wait)
                # 重新创建 app 实例
                app = Application.builder().token(TG_BOT_TOKEN).build()
                app.add_handler(CommandHandler("start", cmd_start))
                app.add_handler(CommandHandler("voice", cmd_voice))
                app.add_handler(CommandHandler("new", cmd_new))
                app.add_handler(CommandHandler("status", cmd_status))
                app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_message))
                app.add_handler(MessageHandler(filters.VOICE, handle_voice_message))
            else:
                logger.error("达到最大重启次数，Bot 停止")
                input("按 Enter 键退出...")  # 防止黑框立即关闭


if __name__ == "__main__":
    main()
