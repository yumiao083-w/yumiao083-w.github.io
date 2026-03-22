# -*- coding: utf-8 -*-
"""
voice_call.py - 实时语音通话后端

架构：
  浏览器 ──WebSocket──→ Flask 后端
  1. 浏览器通过 Web Speech API 识别语音，发送文字
  2. 后端流式调 LLM，按句子切分
  3. 每句调 MiniMax TTS 生成音频
  4. 音频 base64 推回浏览器播放

依赖：
  pip install flask-sock openai
"""

import os
import sys
import json
import time
import base64
import tempfile
import logging
import re
import threading

logger = logging.getLogger(__name__)

YUAN_ROOT = os.path.dirname(os.path.abspath(__file__))
if YUAN_ROOT not in sys.path:
    sys.path.insert(0, YUAN_ROOT)


# =====================================================================
#  配置读取
# =====================================================================

def _cfg(key, default=None):
    try:
        cfg = sys.modules.get('config')
        if cfg is None:
            import config as cfg
        return getattr(cfg, key, default)
    except Exception:
        return default


def _get_chat_providers():
    """获取语音通话用的 API 中转站（优先独立配置，留空则用主聊天 API）"""
    # 优先使用语音通话独立 API
    voice_url = _cfg('VOICE_API_BASE_URL', '')
    voice_key = _cfg('VOICE_API_KEY', '')
    voice_model = _cfg('VOICE_API_MODEL', '')
    if voice_url and voice_key and voice_model:
        return [{
            'name': '语音通话专用',
            'base_url': voice_url,
            'api_key': voice_key,
            'model': voice_model,
        }]

    # 降级到主聊天 API
    providers = _cfg('CHAT_API_PROVIDERS', [])
    if providers:
        return providers
    return [{
        'name': '默认',
        'base_url': _cfg('DEEPSEEK_BASE_URL', ''),
        'api_key': _cfg('DEEPSEEK_API_KEY', ''),
        'model': _cfg('MODEL', ''),
    }]


# =====================================================================
#  句子切分器
# =====================================================================

class SentenceSplitter:
    """流式文本 → 完整句子切分"""

    # 中文标点 + 英文标点 + 换行
    SPLIT_RE = re.compile(r'([。！？!?\n])')

    def __init__(self):
        self._buf = ""

    def feed(self, text: str):
        """喂入增量文本，yield 切好的句子"""
        self._buf += text
        while True:
            m = self.SPLIT_RE.search(self._buf)
            if not m:
                break
            end = m.end()
            sentence = self._buf[:end].strip()
            self._buf = self._buf[end:]
            if sentence:
                yield sentence

    def flush(self):
        """结束时把剩余内容作为最后一句"""
        rest = self._buf.strip()
        self._buf = ""
        if rest:
            yield rest


# 伪装浏览器请求头（公益站防滥用检测）
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Stainless-Lang": "",
    "X-Stainless-Package-Version": "",
    "X-Stainless-OS": "",
    "X-Stainless-Arch": "",
    "X-Stainless-Runtime": "",
    "X-Stainless-Runtime-Version": "",
}


# =====================================================================
#  Whisper 幻觉过滤
# =====================================================================

# Whisper 在静音/噪声输入时常见的幻觉文本关键词
_HALLUCINATION_KEYWORDS = [
    '请不吝点赞', '订阅', '转发', '打赏', '支持明镜', '点点栏目',
    '感谢收看', '感谢观看', '感谢聆听', '谢谢收看', '谢谢观看',
    '字幕制作', '字幕提供', '字幕由', 'Amara.org',
    '下期再见', '我们下期', '下次再见', '下集再见',
    '请订阅', '别忘了订阅', '记得订阅', '点击订阅',
    '喜欢的话', '喜欢就点', '一键三连',
    'Thank you for watching', 'Please subscribe',
    'thanks for watching', 'like and subscribe',
    'Subtitles by', 'Translation by',
    '小铃铛', '开启小铃铛', '通知铃铛',
    '谢谢大家', '谢谢你们', '谢谢各位',
]

# 纯重复字符的模式（如 "啊啊啊啊啊"）
_REPEAT_RE = re.compile(r'^(.)\1{4,}$')

def _is_whisper_hallucination(text: str) -> bool:
    """检测 Whisper 幻觉文本"""
    if not text:
        return True

    # 检查关键词
    for kw in _HALLUCINATION_KEYWORDS:
        if kw in text:
            return True

    # 纯重复字符
    clean = text.replace(' ', '').replace('，', '').replace('。', '')
    if _REPEAT_RE.match(clean):
        return True

    # 文本太短且只有标点/空格
    stripped = re.sub(r'[^\w]', '', text)
    if len(stripped) < 2:
        return True

    return False


# =====================================================================
#  TTS 合成
# =====================================================================

def _tts_to_mp3(text: str) -> bytes:
    """文字 → mp3 bytes"""
    from tts_engine import text_to_mp3
    fd, tmp = tempfile.mkstemp(suffix=".mp3", prefix="vc_tts_")
    os.close(fd)
    try:
        text_to_mp3(text, tmp)
        with open(tmp, "rb") as f:
            return f.read()
    finally:
        try:
            os.unlink(tmp)
        except Exception:
            pass


# =====================================================================
#  LLM 流式调用 + 分句 TTS
# =====================================================================

def stream_chat_and_tts(user_text: str, history: list, ws_send):
    """
    流式调 LLM，分句 TTS，通过 ws_send 推音频给前端。

    ws_send(json_str): 发送 JSON 到 WebSocket
    history: [{"role": "user"/"assistant", "content": "..."}]
    """
    from openai import OpenAI

    t_start = time.time()
    providers = _get_chat_providers()
    temperature = _cfg('TEMPERATURE', 1.0)
    max_token = _cfg('MAX_TOKEN', 4000)

    logger.info(f"[VoiceCall] ====== 新一轮对话 ======")
    logger.info(f"[VoiceCall] 用户输入: {user_text}")
    logger.info(f"[VoiceCall] 历史轮数: {len(history)}")

    # 通知前端：已收到用户文字
    ws_send(json.dumps({
        "type": "user_confirmed",
        "text": user_text,
    }))

    # 构建 messages
    logger.info(f"[VoiceCall] [1/4] 构建 system prompt...")
    t_prompt = time.time()
    system_prompt = _build_voice_system_prompt(user_text)
    logger.info(f"[VoiceCall] [1/4] system prompt 构建完成，长度: {len(system_prompt)} 字符 ({time.time()-t_prompt:.1f}s)")

    messages = [{"role": "system", "content": system_prompt}]

    # 如果开启了共享微信上下文，注入微信聊天历史
    if _cfg('VOICE_SHARE_WECHAT_CONTEXT', False):
        wechat_context = _get_wechat_context()
        if wechat_context:
            messages.extend(wechat_context)
            logger.info(f"[VoiceCall] 注入微信上下文: {len(wechat_context)} 条")

    # 通话历史（无限制）
    messages.extend(history)
    messages.append({"role": "user", "content": user_text})

    # 通知前端：开始调用 LLM
    ws_send(json.dumps({
        "type": "status",
        "step": "llm_start",
        "message": "正在思考...",
    }))

    splitter = SentenceSplitter()
    full_reply = ""
    sentence_idx = 0
    first_token_time = None

    for provider in providers:
        try:
            client = OpenAI(
                api_key=provider.get('api_key', ''),
                base_url=provider.get('base_url', ''),
                default_headers=_BROWSER_HEADERS,
            )
            model = provider.get('model', '')
            p_name = provider.get('name', '未命名')

            logger.info(f"[VoiceCall] [2/4] 调用 LLM [{p_name}] model={model}")
            t_llm = time.time()

            response = client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
                max_tokens=max_token,
                stream=True,
                timeout=30,
            )

            for chunk in response:
                if chunk.choices and chunk.choices[0].delta:
                    delta_text = chunk.choices[0].delta.content or ""
                    if not delta_text:
                        continue

                    if first_token_time is None:
                        first_token_time = time.time()
                        logger.info(f"[VoiceCall] [2/4] 首 token 到达，延迟: {first_token_time-t_llm:.2f}s")
                        ws_send(json.dumps({
                            "type": "status",
                            "step": "llm_streaming",
                            "message": "正在回复...",
                        }))

                    full_reply += delta_text

                    # 发送实时文字（前端显示打字效果）
                    ws_send(json.dumps({
                        "type": "text_delta",
                        "text": delta_text,
                    }))

                    # 切句 → TTS
                    for sentence in splitter.feed(delta_text):
                        _send_sentence_audio(sentence, sentence_idx, ws_send)
                        sentence_idx += 1

            t_llm_done = time.time()
            logger.info(f"[VoiceCall] [2/4] LLM 生成完毕，总耗时: {t_llm_done-t_llm:.2f}s，回复长度: {len(full_reply)}")
            logger.info(f"[VoiceCall] [2/4] AI 回复全文: {full_reply[:200]}{'...' if len(full_reply)>200 else ''}")

            # 处理剩余文本
            for sentence in splitter.flush():
                _send_sentence_audio(sentence, sentence_idx, ws_send)
                sentence_idx += 1

            # 发送完成信号
            t_total = time.time() - t_start
            logger.info(f"[VoiceCall] [4/4] 本轮完成，共 {sentence_idx} 句 TTS，总耗时: {t_total:.2f}s")
            ws_send(json.dumps({
                "type": "done",
                "full_text": full_reply,
                "stats": {
                    "total_time": round(t_total, 2),
                    "first_token_time": round(first_token_time - t_llm, 2) if first_token_time else None,
                    "llm_time": round(t_llm_done - t_llm, 2),
                    "sentences": sentence_idx,
                },
            }))
            return full_reply

        except Exception as e:
            logger.error(f"[VoiceCall] [2/4] 中转站 [{p_name}] 失败: {e}", exc_info=True)
            ws_send(json.dumps({
                "type": "status",
                "step": "llm_retry",
                "message": f"中转站 {p_name} 失败，尝试下一个...",
            }))
            continue

    # 所有中转站都失败
    logger.error(f"[VoiceCall] 所有中转站均失败！")
    ws_send(json.dumps({
        "type": "error",
        "message": "所有 API 中转站均不可用",
    }))
    return ""


def _send_sentence_audio(sentence: str, idx: int, ws_send):
    """一句话 → TTS → 推给前端"""
    # 过滤纯标点
    clean = re.sub(r'[^\w\s]', '', sentence).strip()
    if not clean:
        logger.debug(f"[VoiceCall] [3/4] 跳过纯标点句: {sentence}")
        return

    try:
        t_tts = time.time()
        logger.info(f"[VoiceCall] [3/4] TTS 第{idx}句开始: 「{sentence[:50]}{'...' if len(sentence)>50 else ''}」")

        ws_send(json.dumps({
            "type": "status",
            "step": "tts",
            "message": f"语音合成中... ({idx+1})",
        }))

        audio_bytes = _tts_to_mp3(sentence)
        tts_time = time.time() - t_tts
        logger.info(f"[VoiceCall] [3/4] TTS 第{idx}句完成: {len(audio_bytes)} bytes, 耗时: {tts_time:.2f}s")

        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        ws_send(json.dumps({
            "type": "audio",
            "index": idx,
            "text": sentence,
            "audio": audio_b64,
            "format": "mp3",
        }))
    except Exception as e:
        logger.error(f"[VoiceCall] [3/4] TTS 第{idx}句失败: {e}", exc_info=True)
        ws_send(json.dumps({
            "type": "tts_error",
            "index": idx,
            "text": sentence,
            "message": str(e),
        }))


def _build_voice_system_prompt(current_message=""):
    """构建语音通话专用的系统提示词（复用 bot.py 五板块架构 + 语音通话指令）"""

    # 如果配置了自定义提示词文件，优先使用（给朋友体验用，不含私人记忆）
    custom_file = _cfg('VOICE_CUSTOM_PROMPT_FILE', '')
    if custom_file:
        custom_path = os.path.join(YUAN_ROOT, custom_file)
        if os.path.exists(custom_path):
            try:
                with open(custom_path, 'r', encoding='utf-8') as f:
                    custom_prompt = f.read()
                logger.info(f"[VoiceCall] 使用自定义提示词: {custom_file}")
                return custom_prompt + _voice_instruction()
            except Exception as e:
                logger.error(f"[VoiceCall] 读取自定义提示词失败: {e}")

    # 默认：完整五板块架构
    # 从 config 读取用户和角色信息
    listen_list = _cfg('LISTEN_LIST', [])
    if listen_list:
        user_id = listen_list[0][0]       # 默认第一个用户
        role_name = listen_list[0][1]     # 角色名
        preset_name = listen_list[0][3] if len(listen_list[0]) >= 4 else ''
    else:
        user_id = '郁邈'
        role_name = '袁朗'
        preset_name = ''

    prompt_parts = []

    # ========== 板块1: 人设卡 ==========
    char_content = _read_prompt_file(role_name, 'characters')
    if char_content:
        prompt_parts.append(char_content)

    # ========== 板块2: 预设 ==========
    preset_content = None
    if preset_name:
        preset_content = _read_prompt_file(preset_name, 'presets')
    if not preset_content:
        preset_content = _read_prompt_file('preset', 'presets')
    if preset_content:
        prompt_parts.append(f"\n\n{preset_content}")

    # ========== 板块3: 核心记忆 ==========
    core_memory = _read_core_memory(user_id, role_name)
    if core_memory:
        prompt_parts.append(f"\n\n# 核心记忆\n{core_memory}")

    # ========== 板块4: 记忆索引 ==========
    memory_index = _read_memory_index()
    if memory_index:
        prompt_parts.append(f"\n\n{memory_index}")

    # ========== 板块5: 短期记忆 ==========
    short_term = _read_short_term_memory(user_id)
    if short_term:
        prompt_parts.append(f"\n\n{short_term}")

    # ========== 板块6: 世界书（可选） ==========
    if _cfg('VOICE_ENABLE_WORLD_INFO', False):
        world_info = _read_world_info(user_id, role_name, current_message)
        if world_info:
            prompt_parts.append(f"\n\n{world_info}")
            logger.debug(f"[VoiceCall] 世界书已注入，长度: {len(world_info)}")

    # ========== 板块7: 检索记忆（可选） ==========
    if _cfg('VOICE_ENABLE_MEMORY_RETRIEVAL', True):
        retrieved = _retrieve_memories(current_message)
        if retrieved:
            prompt_parts.append(f"\n\n{retrieved}")
            logger.debug(f"[VoiceCall] 检索记忆已注入，长度: {len(retrieved)}")

    # ========== 语音通话专用指令 ==========
    prompt_parts.append(_voice_instruction())

    return "".join(prompt_parts)


def _voice_instruction():
    """语音通话模式的固定指令"""
    return """

# 语音通话模式
你现在处于实时语音通话模式。请遵守以下规则：
1. 回复要简短自然，像真人打电话一样说话
2. 每次回复控制在1-3句话，不要长篇大论
3. 不要使用 markdown 格式、括号动作描写、emoji、星号
4. 用口语化的表达，可以有语气词
5. 不要说"作为AI"之类的话
6. 如果对方只是简短回应（嗯、好、哦），不用每次都长篇回复

### 语气词与停顿
你可以在回复中插入语气词和停顿，让语音更自然、更有活人感：
- 停顿标签：用 <#x#> 标记停顿时长（x是秒数），如：你好 <#0.5#> 怎么样
- 可用的语气词标签（用逗号分割，禁止使用未列出的）：
  (laughs),(chuckle),(coughs),(clear-throat),(groans),(breath),(pant),(inhale),(exhale),(gasps),(sniffs),(sighs),(snorts),(burps),(lip-smacking),(humming),(hissing),(emm),(sneezes)
- 语气词和停顿要自然地融入说话内容，不要每句都加
- 示例：
  (chuckle)今天玩得开心吗？
  记得要多穿衣服，(sniffs) <#0.3#> 连我都感冒了。
  (sighs)算了 <#0.3#> 不说了。"""


def _read_prompt_file(name, subdir):
    """读取 prompts/ 下的 md 文件"""
    search_paths = [
        os.path.join(YUAN_ROOT, 'prompts', subdir, f'{name}.md'),
        os.path.join(YUAN_ROOT, 'prompts', f'{name}.md'),
    ]
    for fp in search_paths:
        if os.path.exists(fp):
            try:
                with open(fp, 'r', encoding='utf-8') as f:
                    return f.read()
            except Exception:
                pass
    return None


def _read_core_memory(user_id, role_name):
    """读取核心记忆"""
    upload = _cfg('UPLOAD_CORE_MEMORY_TO_AI', True)
    if not upload:
        return None

    core_dir = _cfg('MEMORY_CORE_DIR', 'Memory_Core')
    # 生成 memory_key（与 bot.py 一致）
    memory_key = f"{user_id}_{role_name}"

    try:
        # 优先读 unified_memory
        unified = os.path.join(YUAN_ROOT, core_dir, f'{memory_key}_unified_memory.json')
        if os.path.exists(unified):
            with open(unified, 'r', encoding='utf-8') as f:
                data = json.load(f)
                content = data.get("content", "").strip()
                if content:
                    return content

        # 兼容旧版 core_memory
        old_core = os.path.join(YUAN_ROOT, core_dir, f'{memory_key}_core_memory.json')
        if os.path.exists(old_core):
            with open(old_core, 'r', encoding='utf-8') as f:
                data = json.load(f)
                return data.get("content", "").strip()
    except Exception as e:
        logger.error(f"[VoiceCall] 读取核心记忆失败: {e}")
    return None


def _read_memory_index():
    """读取记忆索引"""
    try:
        sys.path.insert(0, YUAN_ROOT)
        from memory_retrieval import build_memory_index
        return build_memory_index()
    except Exception as e:
        logger.debug(f"[VoiceCall] 记忆索引不可用: {e}")
    return None


def _read_short_term_memory(user_id):
    """读取短期记忆"""
    try:
        sys.path.insert(0, YUAN_ROOT)
        from short_term_memory import get_short_term_prompt
        return get_short_term_prompt(user_id)
    except Exception as e:
        logger.debug(f"[VoiceCall] 短期记忆不可用: {e}")
    return None


def _read_world_info(user_id, role_name, current_message=""):
    """读取世界书"""
    try:
        sys.path.insert(0, YUAN_ROOT)
        from world_info import get_world_info_prompt
        text = get_world_info_prompt(
            user_id=user_id,
            chat_history=[],
            current_message=current_message,
            user_name=user_id,
            char_name=role_name,
        )
        return text if text else None
    except Exception as e:
        logger.debug(f"[VoiceCall] 世界书不可用: {e}")
    return None


def _retrieve_memories(current_message):
    """检索记忆（LLM 精筛）"""
    if not current_message:
        return None
    try:
        sys.path.insert(0, YUAN_ROOT)
        from memory_retrieval import retrieve_relevant_memories, format_retrieved_memories
        memories = retrieve_relevant_memories(current_message)
        if memories:
            return format_retrieved_memories(memories)
    except Exception as e:
        logger.debug(f"[VoiceCall] 检索记忆不可用: {e}")
    return None


def _get_wechat_context():
    """获取微信聊天上下文"""
    try:
        listen_list = _cfg('LISTEN_LIST', [])
        if not listen_list:
            return []
        user_id = listen_list[0][0]
        role_name = listen_list[0][1]

        ctx_file = os.path.join(YUAN_ROOT, 'chat_contexts.json')
        if not os.path.exists(ctx_file):
            return []

        with open(ctx_file, 'r', encoding='utf-8') as f:
            all_ctx = json.load(f)

        user_data = all_ctx.get(user_id, {})
        if isinstance(user_data, dict):
            messages = user_data.get(role_name, [])
        elif isinstance(user_data, list):
            messages = user_data
        else:
            return []

        # 取最近 10 轮微信上下文（避免太长）
        return messages[-20:] if messages else []
    except Exception as e:
        logger.debug(f"[VoiceCall] 微信上下文不可用: {e}")
    return []


def save_call_log(history, call_start_time, call_duration):
    """保存通话记录"""
    try:
        log_dir = os.path.join(YUAN_ROOT, _cfg('VOICE_CALL_LOG_DIR', 'Voice_Logs'))
        os.makedirs(log_dir, exist_ok=True)

        from datetime import datetime
        dt = datetime.fromtimestamp(call_start_time)
        filename = dt.strftime('%Y-%m-%d_%H-%M-%S') + '.json'
        filepath = os.path.join(log_dir, filename)

        log_data = {
            'start_time': dt.isoformat(),
            'duration_seconds': call_duration,
            'rounds': len([m for m in history if m['role'] == 'user']),
            'messages': history,
        }

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(log_data, f, ensure_ascii=False, indent=2)

        logger.info(f"[VoiceCall] 通话记录已保存: {filepath}")
        return filepath
    except Exception as e:
        logger.error(f"[VoiceCall] 保存通话记录失败: {e}")
        return None


# =====================================================================
#  Flask 路由注册
# =====================================================================

def register_voice_routes(app):
    """注册语音通话相关路由到 Flask app"""
    from flask import render_template

    try:
        from flask_sock import Sock
        sock = Sock(app)
        HAS_FLASK_SOCK = True
        print("[VoiceCall] ✅ flask-sock 已加载，WebSocket 可用")
    except ImportError:
        HAS_FLASK_SOCK = False
        print("[VoiceCall] ⚠️ flask-sock 未安装，将使用 HTTP SSE 模式")

    @app.route('/voice')
    def voice_page():
        return render_template('panel_voice.html')

    @app.route('/api/voice/settings')
    def voice_settings():
        """获取语音通话配置"""
        from flask import jsonify
        return jsonify({
            'VOICE_SHARE_WECHAT_CONTEXT': _cfg('VOICE_SHARE_WECHAT_CONTEXT', False),
            'VOICE_ENABLE_WORLD_INFO': _cfg('VOICE_ENABLE_WORLD_INFO', False),
            'VOICE_ENABLE_MEMORY_RETRIEVAL': _cfg('VOICE_ENABLE_MEMORY_RETRIEVAL', True),
        })

    @app.route('/api/voice/logs')
    def voice_logs():
        """获取通话记录列表"""
        from flask import jsonify
        log_dir = os.path.join(YUAN_ROOT, _cfg('VOICE_CALL_LOG_DIR', 'Voice_Logs'))
        if not os.path.exists(log_dir):
            return jsonify({'logs': []})

        logs = []
        for f in sorted(os.listdir(log_dir), reverse=True):
            if f.endswith('.json'):
                filepath = os.path.join(log_dir, f)
                try:
                    with open(filepath, 'r', encoding='utf-8') as fh:
                        data = json.load(fh)
                    logs.append({
                        'filename': f,
                        'start_time': data.get('start_time', ''),
                        'duration_seconds': data.get('duration_seconds', 0),
                        'rounds': data.get('rounds', 0),
                    })
                except Exception:
                    pass
        return jsonify({'logs': logs})

    @app.route('/api/voice/log/<filename>')
    def voice_log_detail(filename):
        """获取单条通话记录详情"""
        from flask import jsonify
        if '/' in filename or '\\' in filename or '..' in filename:
            return jsonify({'error': '非法文件名'}), 400
        log_dir = os.path.join(YUAN_ROOT, _cfg('VOICE_CALL_LOG_DIR', 'Voice_Logs'))
        filepath = os.path.join(log_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': '记录不存在'}), 404
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            return jsonify(data)
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/voice/log/<filename>', methods=['PUT'])
    def voice_log_update(filename):
        """编辑通话记录"""
        from flask import request, jsonify
        if '/' in filename or '\\' in filename or '..' in filename:
            return jsonify({'error': '非法文件名'}), 400
        log_dir = os.path.join(YUAN_ROOT, _cfg('VOICE_CALL_LOG_DIR', 'Voice_Logs'))
        filepath = os.path.join(log_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': '记录不存在'}), 404
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                data = json.load(f)
            req = request.get_json()
            if req and 'messages' in req:
                data['messages'] = req['messages']
                data['rounds'] = len([m for m in req['messages'] if m.get('role') == 'user'])
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            return jsonify({'status': 'saved'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    @app.route('/api/voice/log/<filename>', methods=['DELETE'])
    def voice_log_delete(filename):
        """删除通话记录"""
        from flask import jsonify
        if '/' in filename or '\\' in filename or '..' in filename:
            return jsonify({'error': '非法文件名'}), 400
        log_dir = os.path.join(YUAN_ROOT, _cfg('VOICE_CALL_LOG_DIR', 'Voice_Logs'))
        filepath = os.path.join(log_dir, filename)
        if not os.path.exists(filepath):
            return jsonify({'error': '记录不存在'}), 404
        try:
            os.remove(filepath)
            return jsonify({'status': 'deleted'})
        except Exception as e:
            return jsonify({'error': str(e)}), 500

    if HAS_FLASK_SOCK:
        # ── WebSocket 模式 ──
        @sock.route('/ws/voice')
        def voice_ws(ws):
            """WebSocket 语音通话"""
            history = []
            call_start = time.time()
            logger.info("[VoiceCall] WebSocket 连接建立")

            while True:
                try:
                    raw = ws.receive(timeout=300)  # 5分钟超时
                    if raw is None:
                        break
                    msg = json.loads(raw)
                except Exception:
                    break

                msg_type = msg.get("type", "")

                if msg_type == "chat":
                    user_text = msg.get("text", "").strip()
                    if not user_text:
                        continue

                    history.append({"role": "user", "content": user_text})

                    reply = stream_chat_and_tts(
                        user_text, history,
                        ws_send=lambda data: ws.send(data)
                    )
                    if reply:
                        history.append({"role": "assistant", "content": reply})

                elif msg_type == "ping":
                    ws.send(json.dumps({"type": "pong"}))

                elif msg_type == "end":
                    break

            # 通话结束，保存记录
            if history:
                duration = time.time() - call_start
                save_call_log(history, call_start, round(duration))
            logger.info("[VoiceCall] WebSocket 连接关闭")

    # ── 语音识别 API（Groq Whisper 优先，降级中转站）──
    @app.route('/api/voice/recognize', methods=['POST'])
    def voice_recognize():
        """接收浏览器录音，调 Whisper API 转文字"""
        from flask import request, jsonify
        import requests as http_requests

        if 'audio' not in request.files:
            return jsonify({'error': '没有音频文件'}), 400

        audio_file = request.files['audio']
        if not audio_file.filename:
            return jsonify({'error': '空文件'}), 400

        t_start = time.time()
        logger.info(f"[VoiceCall] [STT] 收到录音: {audio_file.filename}, "
                     f"content_type={audio_file.content_type}")

        # 保存临时文件
        fd, tmp_path = tempfile.mkstemp(suffix=".webm", prefix="vc_stt_")
        os.close(fd)
        try:
            audio_file.save(tmp_path)
            file_size = os.path.getsize(tmp_path)
            logger.info(f"[VoiceCall] [STT] 录音保存: {tmp_path}, {file_size} bytes")

            if file_size < 1000:
                logger.warning(f"[VoiceCall] [STT] 录音太短 ({file_size} bytes)，跳过")
                return jsonify({'text': '', 'message': '录音太短'})

            # ===== GLM-ASR 首选（中文识别最好） =====
            zhipu_key = getattr(config, 'ZHIPU_API_KEY', '') if 'config' in dir() else ''
            if not zhipu_key:
                try:
                    import config as _cfg
                    zhipu_key = getattr(_cfg, 'ZHIPU_API_KEY', '')
                except Exception:
                    zhipu_key = os.environ.get('ZHIPU_API_KEY', '')

            if zhipu_key:
                try:
                    import re as _re
                    glm_url = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"
                    with open(tmp_path, 'rb') as f:
                        resp = http_requests.post(
                            glm_url,
                            headers={"Authorization": f"Bearer {zhipu_key}"},
                            files={"file": ("audio.webm", f, "audio/webm")},
                            data={"model": "glm-asr"},
                            timeout=30,
                        )
                    if resp.status_code == 200:
                        result = resp.json()
                        text = result.get('text', '').strip()
                        text = _re.sub(r'<\|/?[A-Za-z_0-9]+\|>', '', text).strip()
                        if text and len(text) > 1 and not _is_whisper_hallucination(text):
                            stt_time = time.time() - t_start
                            logger.info(f"[VoiceCall] [STT] [GLM-ASR] 识别成功: 「{text}」 ({stt_time:.2f}s)")
                            return jsonify({'text': text, 'time': round(stt_time, 2), 'engine': 'GLM-ASR'})
                        elif text and _is_whisper_hallucination(text):
                            logger.info(f"[VoiceCall] [STT] [GLM-ASR] 过滤幻觉: 「{text}」")
                            return jsonify({'text': '', 'message': '静音或噪声'})
                        else:
                            logger.info("[VoiceCall] [STT] [GLM-ASR] 返回空，降级 Whisper")
                    else:
                        logger.warning(f"[VoiceCall] [STT] [GLM-ASR] HTTP {resp.status_code}: {resp.text[:200]}")
                except Exception as e:
                    logger.warning(f"[VoiceCall] [STT] [GLM-ASR] 异常: {e}")

            # Whisper 引擎列表：Groq 优先，降级到中转站
            whisper_engines = [
                {
                    'name': 'Groq',
                    'url': 'https://api.groq.com/openai/v1/audio/transcriptions',
                    'api_key': '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',
                    'model': 'whisper-large-v3-turbo',
                },
            ]
            # 追加中转站作为降级
            for p in _get_chat_providers():
                whisper_engines.append({
                    'name': f"中转站({p.get('name', '')})",
                    'url': f"{p.get('base_url', '').rstrip('/')}/audio/transcriptions",
                    'api_key': p.get('api_key', ''),
                    'model': 'whisper-1',
                })

            last_error = None
            for engine in whisper_engines:
                e_name = engine['name']
                logger.info(f"[VoiceCall] [STT] 尝试 [{e_name}] {engine['url']}")

                try:
                    with open(tmp_path, 'rb') as f:
                        resp = http_requests.post(
                            engine['url'],
                            headers={
                                "Authorization": f"Bearer {engine['api_key']}",
                                "User-Agent": _BROWSER_HEADERS["User-Agent"],
                            },
                            files={"file": ("audio.webm", f, "audio/webm")},
                            data={
                                "model": engine['model'],
                                "prompt": "以下是一段对话，请使用正确的标点符号。",
                                "response_format": "json",
                            },
                            timeout=30,
                        )

                    if resp.status_code == 200:
                        result = resp.json()
                        text = result.get('text', '').strip()

                        # 过滤 Whisper 幻觉（静音时模型脑补的垃圾文本）
                        if _is_whisper_hallucination(text):
                            logger.info(f"[VoiceCall] [STT] [{e_name}] 过滤幻觉文本: 「{text}」")
                            return jsonify({'text': '', 'message': '静音或噪声'})

                        stt_time = time.time() - t_start
                        logger.info(f"[VoiceCall] [STT] [{e_name}] 识别成功: 「{text}」 ({stt_time:.2f}s)")
                        return jsonify({'text': text, 'time': round(stt_time, 2), 'engine': e_name})
                    else:
                        last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                        logger.warning(f"[VoiceCall] [STT] [{e_name}] 失败: {last_error}")
                        continue

                except Exception as e:
                    last_error = str(e)
                    logger.error(f"[VoiceCall] [STT] [{e_name}] 异常: {e}")
                    continue

            error_msg = f"语音识别失败: {last_error}"
            logger.error(f"[VoiceCall] [STT] 所有引擎均失败")
            return jsonify({'error': error_msg}), 500

        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    # ── HTTP SSE 模式（始终注册，作为 WebSocket 的降级方案）──
    from flask import Response
    import queue

    _sessions = {}  # session_id → { history, queue }
    _sessions_lock = threading.Lock()

    @app.route('/api/voice/chat', methods=['POST'])
    def voice_chat_http():
        """HTTP SSE 模式：POST 文字，返回 SSE 流"""
        from flask import request, jsonify
        req = request.get_json()
        if not req:
            return jsonify({'error': '空请求'}), 400

        user_text = req.get('text', '').strip()
        session_id = req.get('session_id', 'default')
        if not user_text:
            return jsonify({'error': '空消息'}), 400

        with _sessions_lock:
            if session_id not in _sessions:
                _sessions[session_id] = {'history': [], 'queue': queue.Queue(), 'start_time': time.time()}
            sess = _sessions[session_id]

        sess['history'].append({"role": "user", "content": user_text})
        result_queue = queue.Queue()

        def do_chat():
            reply = stream_chat_and_tts(
                user_text, sess['history'],
                ws_send=lambda data: result_queue.put(data)
            )
            if reply:
                sess['history'].append({"role": "assistant", "content": reply})
            result_queue.put(None)  # 结束信号

        threading.Thread(target=do_chat, daemon=True).start()

        def generate():
            while True:
                item = result_queue.get()
                if item is None:
                    yield "data: [DONE]\n\n"
                    break
                yield f"data: {item}\n\n"

        return Response(generate(), mimetype='text/event-stream')

    @app.route('/api/voice/end', methods=['POST'])
    def voice_end():
        """结束通话，保存记录"""
        from flask import request, jsonify
        req = request.get_json() or {}
        session_id = req.get('session_id', 'default')

        with _sessions_lock:
            sess = _sessions.pop(session_id, None)

        if sess and sess.get('history'):
            start_time = sess.get('start_time', time.time())
            duration = time.time() - start_time
            filepath = save_call_log(sess['history'], start_time, round(duration))
            return jsonify({'status': 'saved', 'file': filepath, 'rounds': len(sess['history']) // 2})

        return jsonify({'status': 'no_history'})
