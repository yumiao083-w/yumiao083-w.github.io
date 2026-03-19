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
    """获取聊天中转站列表"""
    providers = _cfg('CHAT_API_PROVIDERS', [])
    if providers:
        return providers
    # 兼容旧版单中转站配置
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
    system_prompt = _build_voice_system_prompt()
    logger.info(f"[VoiceCall] [1/4] system prompt 构建完成，长度: {len(system_prompt)} 字符 ({time.time()-t_prompt:.1f}s)")

    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-20:])  # 最近 20 轮
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


def _build_voice_system_prompt():
    """构建语音通话专用的系统提示词（复用 bot.py 五板块架构 + 语音通话指令）"""

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

    # ========== 语音通话专用指令 ==========
    voice_instruction = """

# 语音通话模式
你现在处于实时语音通话模式。请遵守以下规则：
1. 回复要简短自然，像真人打电话一样说话
2. 每次回复控制在1-3句话，不要长篇大论
3. 不要使用 markdown 格式、括号动作描写、emoji、星号
4. 用口语化的表达，可以有语气词（嗯、啊、哈、嘿）
5. 不要说"作为AI"之类的话
6. 如果对方只是简短回应（嗯、好、哦），不用每次都长篇回复"""
    prompt_parts.append(voice_instruction)

    return "".join(prompt_parts)


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
        logger.info("[VoiceCall] flask-sock 已加载，WebSocket 可用")
    except ImportError:
        HAS_FLASK_SOCK = False
        logger.warning("[VoiceCall] flask-sock 未安装，将使用 HTTP 轮询模式")

    @app.route('/voice')
    def voice_page():
        return render_template('panel_voice.html')

    if HAS_FLASK_SOCK:
        # ── WebSocket 模式 ──
        @sock.route('/ws/voice')
        def voice_ws(ws):
            """WebSocket 语音通话"""
            history = []
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

            logger.info("[VoiceCall] WebSocket 连接关闭")

    else:
        # ── HTTP 轮询模式（降级方案）──
        from flask import Response
        import queue

        _sessions = {}  # session_id → { history, queue }
        _sessions_lock = threading.Lock()

        @app.route('/api/voice/chat', methods=['POST'])
        def voice_chat_http():
            """HTTP SSE 模式：POST 文字，返回 SSE 流"""
            from flask import request
            req = request.get_json()
            if not req:
                return jsonify({'error': '空请求'}), 400

            user_text = req.get('text', '').strip()
            session_id = req.get('session_id', 'default')
            if not user_text:
                return jsonify({'error': '空消息'}), 400

            with _sessions_lock:
                if session_id not in _sessions:
                    _sessions[session_id] = {'history': [], 'queue': queue.Queue()}
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
