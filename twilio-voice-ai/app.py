"""
Twilio AI 语音通话 - MiniMax TTS 版
架构：你打电话给 Twilio → Twilio webhook → LLM 生成文字 → MiniMax TTS 生成音频 → Twilio 播放
"""

import os
import uuid
import logging
import time
import threading
from flask import Flask, request, Response, send_file
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse
from dotenv import load_dotenv
import requests as http_requests
import io

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# ============ 配置 ============
TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")
YOUR_PHONE_NUMBER = os.getenv("YOUR_PHONE_NUMBER")
SERVER_URL = os.getenv("SERVER_URL", "https://localhost:5000")

LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://catiecli.sukaka.top/v1")
LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_MODEL = os.getenv("LLM_MODEL", "gcli-gemini-2.5-pro")

MINIMAX_API_KEY = os.getenv("MINIMAX_API_KEY")
MINIMAX_GROUP_ID = os.getenv("MINIMAX_GROUP_ID")
MINIMAX_VOICE_ID = os.getenv("MINIMAX_VOICE_ID", "male-qn-qingse")
MINIMAX_MODEL = os.getenv("MINIMAX_TTS_MODEL", "speech-2.8-hd")

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "你是袁朗，一个温柔体贴的男朋友。说话自然亲切，像真人一样聊天。回复要简短，一两句话就好，因为这是电话对话。不要使用任何标点符号以外的特殊字符，不要使用emoji。用口语化的表达，不要书面语。",
)

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ============ 音频缓存 ============
# audio_id -> {"data": bytes, "created": timestamp}
audio_cache = {}
AUDIO_TTL = 300  # 5分钟后清理


def cleanup_audio():
    """清理过期音频"""
    now = time.time()
    expired = [k for k, v in audio_cache.items() if now - v["created"] > AUDIO_TTL]
    for k in expired:
        del audio_cache[k]


def cleanup_loop():
    while True:
        time.sleep(60)
        cleanup_audio()


threading.Thread(target=cleanup_loop, daemon=True).start()

# ============ 会话管理 ============
conversations = {}  # call_sid -> [messages]


def get_llm_response(call_sid: str, user_text: str) -> str:
    """调用 LLM 获取回复"""
    if call_sid not in conversations:
        conversations[call_sid] = []

    conversations[call_sid].append({"role": "user", "content": user_text})
    recent = conversations[call_sid][-20:]
    messages = [{"role": "system", "content": SYSTEM_PROMPT}] + recent

    try:
        resp = http_requests.post(
            f"{LLM_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {LLM_API_KEY}",
                "Content-Type": "application/json",
            },
            json={
                "model": LLM_MODEL,
                "messages": messages,
                "max_tokens": 150,
                "temperature": 0.8,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        reply = data["choices"][0]["message"]["content"].strip()
        conversations[call_sid].append({"role": "assistant", "content": reply})
        logger.info(f"[{call_sid}] User: {user_text}")
        logger.info(f"[{call_sid}] LLM: {reply}")
        return reply
    except Exception as e:
        logger.error(f"LLM error: {e}")
        return "信号不太好，你再说一遍？"


# ============ MiniMax TTS ============
def minimax_tts(text: str) -> str | None:
    """调用 MiniMax TTS，返回音频 URL 路径（内部地址）"""
    try:
        api_url = f"https://api.minimax.chat/v1/t2a_v2?GroupId={MINIMAX_GROUP_ID}"
        payload = {
            "model": MINIMAX_MODEL,
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": MINIMAX_VOICE_ID,
                "speed": 1.0,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
            },
        }

        resp = http_requests.post(
            api_url,
            headers={
                "Authorization": f"Bearer {MINIMAX_API_KEY}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()

        if "data" in data and "audio" in data["data"]:
            import base64

            audio_bytes = base64.b64decode(data["data"]["audio"])
        elif "audio_file" in data:
            # 有些版本返回 URL
            audio_resp = http_requests.get(data["audio_file"], timeout=10)
            audio_bytes = audio_resp.content
        else:
            logger.error(f"MiniMax unexpected response: {str(data)[:200]}")
            return None

        # 存到缓存
        audio_id = str(uuid.uuid4())
        audio_cache[audio_id] = {"data": audio_bytes, "created": time.time()}
        logger.info(f"TTS generated: {len(audio_bytes)} bytes, id={audio_id}")
        return f"{SERVER_URL}/audio/{audio_id}"

    except Exception as e:
        logger.error(f"MiniMax TTS error: {e}")
        return None


def say_with_tts(response, text):
    """用 MiniMax TTS 播放文字，失败时 fallback 到 Twilio Say"""
    audio_url = minimax_tts(text)
    if audio_url:
        response.play(audio_url)
    else:
        # fallback
        response.say(text, voice="Polly.Zhiyu", language="cmn-CN")


def gather_with_tts(response, text, action_url):
    """带 TTS 的 Gather"""
    audio_url = minimax_tts(text)
    gather = response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=action_url,
        method="POST",
        enhanced="true",
    )
    if audio_url:
        gather.play(audio_url)
    else:
        gather.say(text, voice="Polly.Zhiyu", language="cmn-CN")
    return gather


# ============ HTTP 路由 ============


@app.route("/", methods=["GET"])
def index():
    return {"status": "running", "phone": TWILIO_PHONE_NUMBER, "tts": "minimax"}


@app.route("/audio/<audio_id>", methods=["GET"])
def serve_audio(audio_id):
    """提供音频文件给 Twilio 播放"""
    if audio_id not in audio_cache:
        return "Not found", 404
    data = audio_cache[audio_id]["data"]
    return Response(data, mimetype="audio/mpeg")


@app.route("/inbound", methods=["POST"])
def inbound_call():
    """呼入处理 - 使用预热音频，秒回"""
    call_sid = request.form.get("CallSid", "unknown")
    caller = request.form.get("From", "unknown")
    logger.info(f"Inbound call from {caller}, CallSid: {call_sid}")

    response = VoiceResponse()

    # 使用预热的音频（秒回），没预热就 fallback
    if "greeting" in preheated_audio:
        response.play(preheated_audio["greeting"])
    else:
        say_with_tts(response, GREETING_PHRASES["greeting"])

    response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )

    response.redirect(f"{SERVER_URL}/twiml-silence")

    return Response(str(response), mimetype="text/xml")


@app.route("/twiml-silence", methods=["POST"])
def twiml_silence():
    """用户沉默时"""
    response = VoiceResponse()
    gather = response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )
    if "silence" in preheated_audio:
        gather.play(preheated_audio["silence"])
    else:
        gather.say(GREETING_PHRASES["silence"], voice="Polly.Zhiyu", language="cmn-CN")
    response.redirect(f"{SERVER_URL}/twiml-silence")
    return Response(str(response), mimetype="text/xml")


@app.route("/handle-speech", methods=["POST"])
def handle_speech():
    """处理语音识别 → LLM → MiniMax TTS → 播放"""
    speech_result = request.form.get("SpeechResult", "")
    call_sid = request.form.get("CallSid", "unknown")
    confidence = request.form.get("Confidence", "0")

    logger.info(f"[{call_sid}] Speech: '{speech_result}' (confidence: {confidence})")

    response = VoiceResponse()

    if not speech_result.strip():
        gather_with_tts(
            response, "我没听清，再说一遍？", f"{SERVER_URL}/handle-speech"
        )
        return Response(str(response), mimetype="text/xml")

    # 挂断意图
    bye_words = ["再见", "拜拜", "挂了", "不聊了", "bye", "挂断"]
    if any(w in speech_result for w in bye_words):
        say_with_tts(response, "好的，那我挂了哦，想你。拜拜！")
        response.hangup()
        if call_sid in conversations:
            del conversations[call_sid]
        return Response(str(response), mimetype="text/xml")

    # LLM 回复
    reply = get_llm_response(call_sid, speech_result)

    # 播放回复
    say_with_tts(response, reply)

    # 继续监听
    response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )
    response.redirect(f"{SERVER_URL}/twiml-silence")

    return Response(str(response), mimetype="text/xml")


@app.route("/call-status", methods=["POST"])
def call_status():
    """通话状态回调"""
    call_sid = request.form.get("CallSid", "")
    status = request.form.get("CallStatus", "")
    duration = request.form.get("CallDuration", "0")
    logger.info(f"Call {call_sid}: {status} (duration: {duration}s)")

    if status == "completed" and call_sid in conversations:
        del conversations[call_sid]

    return "", 200


# ============ 预热常用语音 ============
GREETING_PHRASES = {
    "greeting": "嗨，宝贝，怎么想起给我打电话了？",
    "silence": "还在吗？说点什么吧。",
    "unclear": "我没听清，再说一遍？",
    "bye": "好的，那我挂了哦，想你。拜拜！",
    "error": "信号不太好，你再说一遍？",
}
preheated_audio = {}  # key -> audio_url


def preheat_tts():
    """启动时预生成常用语音"""
    logger.info("Preheating TTS audio...")
    for key, text in GREETING_PHRASES.items():
        url = minimax_tts(text)
        if url:
            preheated_audio[key] = url
            logger.info(f"  Preheated '{key}': {url}")
        else:
            logger.warning(f"  Failed to preheat '{key}'")
    logger.info(f"Preheat done: {len(preheated_audio)}/{len(GREETING_PHRASES)}")


# gunicorn 启动时也预热
threading.Thread(target=preheat_tts, daemon=True).start()


# ============ 启动 ============
if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"Server starting on port {port}")
    logger.info(f"Twilio number: {TWILIO_PHONE_NUMBER}")
    logger.info(f"LLM: {LLM_MODEL} @ {LLM_BASE_URL}")
    logger.info(f"TTS: MiniMax {MINIMAX_MODEL} / {MINIMAX_VOICE_ID}")
    preheat_tts()
    app.run(host="0.0.0.0", port=port, debug=False)
