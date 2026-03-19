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

    providers = _get_chat_providers()
    temperature = _cfg('TEMPERATURE', 1.0)
    max_token = _cfg('MAX_TOKEN', 4000)

    # 构建 messages
    system_prompt = _build_voice_system_prompt()
    messages = [{"role": "system", "content": system_prompt}]
    messages.extend(history[-20:])  # 最近 20 轮
    messages.append({"role": "user", "content": user_text})

    splitter = SentenceSplitter()
    full_reply = ""
    sentence_idx = 0

    for provider in providers:
        try:
            client = OpenAI(
                api_key=provider.get('api_key', ''),
                base_url=provider.get('base_url', ''),
            )
            model = provider.get('model', '')
            p_name = provider.get('name', '未命名')

            logger.info(f"[VoiceCall] 调用 [{p_name}] model={model}")

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

            # 处理剩余文本
            for sentence in splitter.flush():
                _send_sentence_audio(sentence, sentence_idx, ws_send)
                sentence_idx += 1

            # 发送完成信号
            ws_send(json.dumps({
                "type": "done",
                "full_text": full_reply,
            }))
            return full_reply

        except Exception as e:
            logger.error(f"[VoiceCall] 中转站 [{p_name}] 失败: {e}")
            continue

    # 所有中转站都失败
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
        return

    try:
        logger.info(f"[VoiceCall] TTS 第{idx}句: {sentence[:40]}...")
        audio_bytes = _tts_to_mp3(sentence)
        audio_b64 = base64.b64encode(audio_bytes).decode('utf-8')

        ws_send(json.dumps({
            "type": "audio",
            "index": idx,
            "text": sentence,
            "audio": audio_b64,
            "format": "mp3",
        }))
    except Exception as e:
        logger.error(f"[VoiceCall] TTS 第{idx}句失败: {e}")
        ws_send(json.dumps({
            "type": "tts_error",
            "index": idx,
            "text": sentence,
            "message": str(e),
        }))


def _build_voice_system_prompt():
    """构建语音通话专用的系统提示词（简短版）"""
    # 读取角色人设
    char_prompt = ""
    try:
        char_files = [
            os.path.join(YUAN_ROOT, 'prompts', 'characters', '袁朗.md'),
            os.path.join(YUAN_ROOT, 'prompts', '袁朗.md'),
        ]
        for fp in char_files:
            if os.path.exists(fp):
                with open(fp, 'r', encoding='utf-8') as f:
                    char_prompt = f.read()
                break
    except Exception:
        pass

    voice_instruction = """你现在处于实时语音通话模式。请遵守以下规则：
1. 回复要简短自然，像真人打电话一样说话
2. 每次回复控制在1-3句话，不要长篇大论
3. 不要使用 markdown 格式、括号动作描写、emoji
4. 用口语化的表达，可以有语气词（嗯、啊、哈）
5. 不要说"作为AI"之类的话"""

    if char_prompt:
        return f"{char_prompt}\n\n{voice_instruction}"
    return voice_instruction


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
