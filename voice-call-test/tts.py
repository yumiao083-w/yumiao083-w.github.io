# tts.py — MiniMax TTS 语音合成模块

import os
import re
import requests
import logging

logger = logging.getLogger(__name__)

DEFAULT_VOICE_ID = "male-qn-qingse"
DEFAULT_MODEL = "speech-02-hd"

# 匹配语气词标签 (laughs) (hmm) (sighs) 等
_VOICE_TAG_RE = re.compile(r"\([a-zA-Z\s\-]+\)")
# 匹配停顿标签 <#0.5#> <#1.2#>
_PAUSE_TAG_RE = re.compile(r"<#[\d.]+#>")


def _clean_for_tts(text: str) -> str:
    """清理文本中的语气标签和停顿标签，只保留要朗读的内容。"""
    text = _VOICE_TAG_RE.sub("", text)
    text = _PAUSE_TAG_RE.sub("", text)
    text = re.sub(r"\s{2,}", " ", text)
    return text.strip()


def synthesize(text, api_key=None, voice_id=None, group_id=None, model=None):
    """
    将文本合成为 MP3 语音。

    参数:
        text:     要合成的文字
        api_key:  MiniMax API Key，默认从环境变量 MINIMAX_API_KEY 读取
        voice_id: 音色 ID，默认从环境变量 MINIMAX_VOICE_ID 读取
        group_id: Group ID，默认从环境变量 MINIMAX_GROUP_ID 读取
        model:    TTS 模型名，默认从环境变量 MINIMAX_TTS_MODEL 读取

    返回:
        mp3 bytes — 合成成功时返回音频二进制数据
        None      — 输入文本为纯标点/空白时返回 None

    异常:
        ValueError  — 参数缺失（如 API Key 未提供）
        Exception   — API 调用失败或返回错误
    """

    # ── 参数处理 ──
    if not text or not isinstance(text, str):
        raise ValueError("text 参数不能为空")

    # 清理语气标签和停顿标签
    text = _clean_for_tts(text)

    # 过滤纯标点/空白
    stripped = re.sub(r'[^\w]', '', text, flags=re.UNICODE)
    if not stripped:
        logger.debug("文本为纯标点或空白，跳过合成: %r", text)
        return None

    if api_key is None:
        api_key = os.environ.get("MINIMAX_API_KEY")
    if not api_key:
        raise ValueError(
            "未提供 api_key，且环境变量 MINIMAX_API_KEY 未设置"
        )

    if group_id is None:
        group_id = os.environ.get("MINIMAX_GROUP_ID", "")
    if not group_id:
        raise ValueError(
            "未提供 group_id，且环境变量 MINIMAX_GROUP_ID 未设置"
        )

    if voice_id is None:
        voice_id = os.environ.get("MINIMAX_VOICE_ID", DEFAULT_VOICE_ID)

    if model is None:
        model = os.environ.get("MINIMAX_TTS_MODEL", DEFAULT_MODEL)

    # ── 构造请求 ──
    api_url = f"https://api.minimax.chat/v1/t2a_v2?GroupId={group_id}"

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    payload = {
        "model": model,
        "text": text,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": 1.0,
            "vol": 1.0,
            "pitch": 0,
        },
        "audio_setting": {
            "format": "mp3",
            "sample_rate": 32000,
        },
    }

    # ── 发送请求 ──
    logger.info("MiniMax TTS: model=%s, voice=%s, group=%s, len=%d",
                model, voice_id, group_id, len(text))
    try:
        resp = requests.post(
            api_url,
            headers=headers,
            json=payload,
            timeout=30,
        )
    except requests.exceptions.Timeout:
        raise Exception("MiniMax TTS 请求超时（30s）")
    except requests.exceptions.ConnectionError as e:
        raise Exception(f"MiniMax TTS 连接失败: {e}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"MiniMax TTS 请求异常: {e}")

    # ── HTTP 状态码检查 ──
    if resp.status_code != 200:
        raise Exception(
            f"MiniMax TTS HTTP 错误: {resp.status_code} — {resp.text[:500]}"
        )

    # ── 解析响应 JSON ──
    try:
        result = resp.json()
    except ValueError:
        raise Exception(
            f"MiniMax TTS 返回非 JSON 响应: {resp.text[:500]}"
        )

    # ── 业务状态码检查 ──
    base_resp = result.get("base_resp", {})
    status_code = base_resp.get("status_code")
    status_msg = base_resp.get("status_msg", "未知错误")

    if status_code != 0:
        raise Exception(
            f"MiniMax TTS 业务错误 (code={status_code}): {status_msg}"
        )

    # ── 提取音频数据 ──
    data = result.get("data")
    if not data:
        raise Exception("MiniMax TTS 响应中缺少 data 字段")

    audio_hex = data.get("audio")
    if not audio_hex:
        raise Exception("MiniMax TTS 响应中缺少 data.audio 字段")

    try:
        audio_bytes = bytes.fromhex(audio_hex)
    except ValueError as e:
        raise Exception(f"MiniMax TTS 音频 hex 解码失败: {e}")

    if len(audio_bytes) == 0:
        raise Exception("MiniMax TTS 返回的音频数据为空")

    logger.info("TTS 合成成功，音频大小=%d bytes", len(audio_bytes))
    return audio_bytes
