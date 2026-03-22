# app.py — 公开版语音通话 Flask 主应用
# 路由逻辑，业务代码在 llm.py/tts.py/stt.py/utils.py

import os
import json
import time
import base64
import hashlib
import logging
import threading
import queue as queue_mod
from flask import Flask, request, jsonify, Response, render_template, redirect, url_for

from utils import SentenceSplitter, VOICE_INSTRUCTION
from llm import stream_chat, fetch_models
from tts import synthesize as tts_synthesize
from stt import recognize as stt_recognize

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# 密钥管理
_used_keys: set = set()
_active_tokens: set = set()
_guest_tokens: set = set()  # 免密钥访客token，必须自带API

# 会话管理（内存，不持久化）
_sessions: dict = {}
_sessions_lock = threading.Lock()

# 内置提示词（从 prompt.md 读取）
_builtin_prompt = ""
_prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "prompt.md")
if os.path.exists(_prompt_path):
    with open(_prompt_path, "r", encoding="utf-8") as f:
        _builtin_prompt = f.read()


# =====================================================================
# 页面路由
# =====================================================================

@app.route("/")
def index():
    """登录页"""
    return render_template("login.html")


@app.route("/setup")
def setup():
    """设置页 — 需要有效 token"""
    token = request.args.get("token", "")
    if not token or token not in _active_tokens:
        return redirect("/")
    return render_template("setup.html")


@app.route("/call")
def call():
    """通话页 — 需要有效 token"""
    token = request.args.get("token", "")
    if not token or token not in _active_tokens:
        return redirect("/")
    return render_template("call.html")


# =====================================================================
# API 路由
# =====================================================================

@app.route("/api/auth", methods=["POST"])
def api_auth():
    """
    密钥验证，换取一次性 token。
    环境变量 PUBLIC_KEYS 存放逗号分隔的有效密钥。
    """
    data = request.get_json(force=True, silent=True) or {}
    key = (data.get("key") or "").strip()
    if not key:
        return jsonify({"error": "缺少密钥"}), 400

    valid_keys_raw = os.environ.get("PUBLIC_KEYS", "")
    valid_keys = {k.strip() for k in valid_keys_raw.split(",") if k.strip()}

    if key not in valid_keys:
        return jsonify({"error": "密钥无效"}), 403

    if key in _used_keys:
        return jsonify({"error": "该密钥已被使用"}), 403

    token = hashlib.sha256(f"{key}_{time.time()}".encode()).hexdigest()[:16]
    _used_keys.add(key)
    _active_tokens.add(token)

    return jsonify({"token": token})


@app.route("/api/guest-token", methods=["POST"])
def api_guest_token():
    """
    免密钥访客令牌：用户自带 LLM + TTS API，不消耗内置资源。
    """
    token = hashlib.sha256(f"guest_{time.time()}".encode()).hexdigest()[:16]
    _active_tokens.add(token)
    _guest_tokens.add(token)
    return jsonify({"token": token})


@app.route("/api/chat", methods=["POST"])
def api_chat():
    """
    流式聊天 + TTS，返回 SSE。
    body: { text, session_id, token, custom_api?, custom_tts?, custom_prompt? }
    """
    data = request.get_json(force=True, silent=True) or {}
    token = (data.get("token") or "").strip()
    if not token or token not in _active_tokens:
        return jsonify({"error": "未授权"}), 401

    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "缺少文本"}), 400

    session_id = data.get("session_id") or token
    custom_api = data.get("custom_api")       # dict | None
    custom_tts = data.get("custom_tts")       # dict | None

    # 访客 token 必须自带 API
    if token in _guest_tokens:
        if not custom_api or not custom_api.get("base_url") or not custom_api.get("api_key"):
            return jsonify({"error": "访客模式需要自备 LLM API（请在设置中填写 API 地址和 Key）"}), 400
        if not custom_tts or not custom_tts.get("api_key"):
            return jsonify({"error": "访客模式需要自备 TTS API（请在设置中填写 MiniMax API Key）"}), 400
    custom_prompt = data.get("custom_prompt")  # str | None
    req_model = data.get("model")             # str | None — 前端选择的模型

    # 构建 system prompt
    parts = []
    if _builtin_prompt:
        parts.append(_builtin_prompt)
    if custom_prompt:
        parts.append(custom_prompt)
    parts.append(VOICE_INSTRUCTION)
    system_prompt = "\n\n".join(parts)

    # 获取 / 创建 session history
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = []
        history = list(_sessions[session_id])  # shallow copy

    # 构建 messages
    messages = [{"role": "system", "content": system_prompt}] + history + [{"role": "user", "content": text}]

    q: queue_mod.Queue = queue_mod.Queue()

    def _worker():
        start_time = time.time()
        first_token_time = None
        full_text_parts: list[str] = []
        sentence_index = 0

        try:
            # 1. user confirmed
            q.put(json.dumps({"type": "user_confirmed", "text": text}, ensure_ascii=False))

            # 2. status
            q.put(json.dumps({"type": "status", "step": "llm_start", "message": "正在思考..."}, ensure_ascii=False))

            # 3. stream LLM
            stream_kwargs: dict = {"messages": messages}
            if custom_api:
                stream_kwargs["custom_api"] = custom_api
                if custom_api.get("model"):
                    stream_kwargs["model"] = custom_api["model"]
                elif req_model:
                    stream_kwargs["model"] = req_model
            elif req_model:
                stream_kwargs["model"] = req_model

            splitter = SentenceSplitter()

            def _do_tts(sentence: str, idx: int):
                """合成一句 TTS 并推到队列"""
                try:
                    tts_kwargs: dict = {"text": sentence}
                    if custom_tts:
                        if custom_tts.get("api_key"):
                            tts_kwargs["api_key"] = custom_tts["api_key"]
                        if custom_tts.get("voice_id"):
                            tts_kwargs["voice_id"] = custom_tts["voice_id"]
                        if custom_tts.get("group_id"):
                            tts_kwargs["group_id"] = custom_tts["group_id"]
                        if custom_tts.get("model"):
                            tts_kwargs["model"] = custom_tts["model"]
                    mp3_bytes = tts_synthesize(**tts_kwargs)
                    if mp3_bytes is None:
                        return  # 纯标点/空白，跳过
                    audio_b64 = base64.b64encode(mp3_bytes).decode("ascii")
                    q.put(json.dumps({
                        "type": "audio",
                        "index": idx,
                        "text": sentence,
                        "audio": audio_b64,
                        "format": "mp3",
                    }, ensure_ascii=False))
                except Exception as e:
                    logger.error("TTS error for sentence %d: %s", idx, e)

            # 4. iterate deltas
            for delta in stream_chat(**stream_kwargs):
                if first_token_time is None:
                    first_token_time = time.time() - start_time

                full_text_parts.append(delta)

                # push text delta
                q.put(json.dumps({"type": "text_delta", "text": delta}, ensure_ascii=False))

                # feed splitter
                sentences = splitter.feed(delta)
                for sent in sentences:
                    _do_tts(sent, sentence_index)
                    sentence_index += 1

            llm_end_time = time.time()
            llm_time = llm_end_time - start_time

            # 6. flush remaining text
            remaining = splitter.flush()
            for sent in remaining:
                _do_tts(sent, sentence_index)
                sentence_index += 1

            full_text = "".join(full_text_parts)
            total_time = time.time() - start_time

            # 7. done
            q.put(json.dumps({
                "type": "done",
                "full_text": full_text,
                "stats": {
                    "total_time": round(total_time, 3),
                    "first_token_time": round(first_token_time, 3) if first_token_time is not None else None,
                    "llm_time": round(llm_time, 3),
                    "sentences": sentence_index,
                },
            }, ensure_ascii=False))

            # 8. update session history
            with _sessions_lock:
                _sessions.setdefault(session_id, [])
                _sessions[session_id].append({"role": "user", "content": text})
                _sessions[session_id].append({"role": "assistant", "content": full_text})

        except Exception as exc:
            logger.exception("chat worker error")
            try:
                q.put(json.dumps({"type": "error", "message": str(exc)}, ensure_ascii=False))
            except Exception:
                pass
        finally:
            # 9. sentinel
            q.put(None)

    threading.Thread(target=_worker, daemon=True).start()

    def _generate():
        while True:
            item = q.get()
            if item is None:
                yield "data: [DONE]\n\n"
                break
            yield f"data: {item}\n\n"

    return Response(_generate(), mimetype="text/event-stream")


@app.route("/api/recognize", methods=["POST"])
def api_recognize():
    """语音识别"""
    if "audio" not in request.files:
        return jsonify({"error": "缺少音频文件"}), 400
    audio_file = request.files["audio"]
    try:
        result = stt_recognize(audio_file)
        return jsonify(result)
    except Exception as exc:
        logger.exception("STT error")
        return jsonify({"error": str(exc)}), 500


@app.route("/api/models", methods=["GET"])
def api_models():
    """获取可用模型列表"""
    base_url = request.args.get("base_url", "")
    api_key = request.args.get("api_key", "")
    if not base_url or not api_key:
        return jsonify({"error": "缺少 base_url 或 api_key"}), 400
    try:
        models = fetch_models(base_url, api_key)
        return jsonify({"models": models})
    except Exception as exc:
        logger.exception("fetch_models error")
        return jsonify({"error": str(exc)}), 500


@app.route('/api/builtin-models')
def builtin_models():
    """获取内置中转站的模型列表"""
    from llm import get_providers, fetch_models
    providers = get_providers()  # 不传 custom_api，获取内置中转站列表
    all_models = []
    seen = set()
    for p in providers:
        try:
            models = fetch_models(p['base_url'], p['api_key'])
            for m in models:
                if m not in seen:
                    seen.add(m)
                    all_models.append(m)
            if all_models:
                break  # 第一个能用的中转站就够了
        except Exception:
            continue
    return jsonify({'models': all_models})


# =====================================================================
# 启动
# =====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)
