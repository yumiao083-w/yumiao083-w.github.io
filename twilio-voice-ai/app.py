"""
Twilio AI 语音通话 - 阶段1：最小可用版
架构：
  方案A: Twilio 外呼 → ConversationRelay WebSocket → LLM → 文字回复 → Twilio TTS
  方案B: Twilio 外呼 → Gather(语音识别) → LLM → Say(TTS) → 循环
"""

import os
import json
import asyncio
import threading
import logging
from flask import Flask, request, Response
from twilio.rest import Client
from twilio.twiml.voice_response import VoiceResponse, Connect
from dotenv import load_dotenv
import requests as http_requests

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

SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "你是袁朗，一个温柔体贴的男朋友。说话自然亲切，像真人一样聊天。回复要简短，一两句话就好，因为这是电话对话。不要使用任何标点符号以外的特殊字符，不要使用emoji。用口语化的表达，不要书面语。",
)

# Twilio Trial 限制：只有已验证号码才能呼入/呼出
# 需要在 Twilio Console → Verified Caller IDs 添加你的 +86 号码

twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

# ============ 会话管理 ============
conversations = {}  # call_sid -> [messages]


def get_llm_response(call_sid: str, user_text: str) -> str:
    """调用 LLM（OpenAI兼容接口）获取回复"""
    if call_sid not in conversations:
        conversations[call_sid] = []

    conversations[call_sid].append({"role": "user", "content": user_text})

    # 保留最近10轮对话，避免 token 过多
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


# ============ HTTP 路由 ============


@app.route("/", methods=["GET"])
def index():
    return {"status": "running", "phone": TWILIO_PHONE_NUMBER}


@app.route("/inbound", methods=["POST"])
def inbound_call():
    """呼入处理 - 你打给 Twilio 号码时触发"""
    call_sid = request.form.get("CallSid", "unknown")
    caller = request.form.get("From", "unknown")
    logger.info(f"Inbound call from {caller}, CallSid: {call_sid}")

    response = VoiceResponse()

    # 接起来打招呼
    response.say("嗨，宝贝，怎么想起给我打电话了？", voice="alice", language="zh-CN")

    # 开始监听
    gather = response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )

    # 如果用户没说话，提示
    response.redirect(f"{SERVER_URL}/twiml-silence")

    return Response(str(response), mimetype="text/xml")


@app.route("/outbound-call", methods=["POST", "GET"])
def make_outbound_call():
    """触发外呼 - GET 也支持方便浏览器测试（备用，目前外呼到+86不可用）"""
    if request.is_json:
        target = request.json.get("to", YOUR_PHONE_NUMBER)
    else:
        target = request.args.get("to", YOUR_PHONE_NUMBER)

    try:
        call = twilio_client.calls.create(
            to=target,
            from_=TWILIO_PHONE_NUMBER,
            url=f"{SERVER_URL}/twiml",
            status_callback=f"{SERVER_URL}/call-status",
            status_callback_event=["initiated", "ringing", "answered", "completed"],
        )
        logger.info(f"Call initiated: {call.sid} -> {target}")
        return {"success": True, "call_sid": call.sid, "to": target}, 200
    except Exception as e:
        logger.error(f"Call failed: {e}")
        return {"success": False, "error": str(e)}, 500


@app.route("/twiml", methods=["POST"])
def twiml_handler():
    """Twilio 外呼接通后的 TwiML 指令 - 使用 Gather+Say 模式"""
    response = VoiceResponse()

    # 先打招呼
    response.say("你好呀，想你了就给你打个电话。", voice="alice", language="zh-CN")

    # 开始监听用户说话
    gather = response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )
    gather.say("你在干嘛呢？", voice="alice", language="zh-CN")

    # 如果用户没说话，重新提示
    response.redirect(f"{SERVER_URL}/twiml-silence")

    return Response(str(response), mimetype="text/xml")


@app.route("/twiml-silence", methods=["POST"])
def twiml_silence():
    """用户沉默时的处理"""
    response = VoiceResponse()
    gather = response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )
    gather.say("还在吗？说点什么吧。", voice="alice", language="zh-CN")
    response.redirect(f"{SERVER_URL}/twiml-silence")
    return Response(str(response), mimetype="text/xml")


@app.route("/handle-speech", methods=["POST"])
def handle_speech():
    """处理语音识别结果 → 调 LLM → 返回语音"""
    speech_result = request.form.get("SpeechResult", "")
    call_sid = request.form.get("CallSid", "unknown")
    confidence = request.form.get("Confidence", "0")

    logger.info(f"[{call_sid}] Speech: '{speech_result}' (confidence: {confidence})")

    response = VoiceResponse()

    if not speech_result.strip():
        gather = response.gather(
            input="speech",
            language="zh-CN",
            speech_timeout="auto",
            action=f"{SERVER_URL}/handle-speech",
            method="POST",
            enhanced="true",
        )
        gather.say("我没听清，再说一遍？", voice="alice", language="zh-CN")
        return Response(str(response), mimetype="text/xml")

    # 检查挂断意图
    bye_words = ["再见", "拜拜", "挂了", "不聊了", "bye", "挂断"]
    if any(w in speech_result for w in bye_words):
        response.say("好的，那我挂了哦，想你。拜拜！", voice="alice", language="zh-CN")
        response.hangup()
        if call_sid in conversations:
            del conversations[call_sid]
        return Response(str(response), mimetype="text/xml")

    # 调 LLM
    reply = get_llm_response(call_sid, speech_result)

    # 播放回复
    response.say(reply, voice="alice", language="zh-CN")

    # 继续听下一句
    gather = response.gather(
        input="speech",
        language="zh-CN",
        speech_timeout="auto",
        action=f"{SERVER_URL}/handle-speech",
        method="POST",
        enhanced="true",
    )
    # 空的 gather 等待用户说话
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


# ============ 启动 ============

if __name__ == "__main__":
    port = int(os.getenv("PORT", "5000"))
    logger.info(f"Server starting on port {port}")
    logger.info(f"Outbound call target: {YOUR_PHONE_NUMBER}")
    logger.info(f"Twilio number: {TWILIO_PHONE_NUMBER}")
    logger.info(f"LLM: {LLM_MODEL} @ {LLM_BASE_URL}")
    app.run(host="0.0.0.0", port=port, debug=False)
