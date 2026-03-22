# stt.py — 语音识别模块（GLM-ASR 首选 + Groq Whisper 降级）

import os
import re
import time
import tempfile
import requests
import logging

from utils import is_whisper_hallucination

logger = logging.getLogger(__name__)

# 浏览器伪装 User-Agent
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/131.0.0.0 Safari/537.36"
)

# ── 智谱 GLM-ASR 配置 ──
_ZHIPU_API_URL = "https://open.bigmodel.cn/api/paas/v4/audio/transcriptions"

# ── Groq Whisper 配置 ──
_GROQ_API_URL = "https://api.groq.com/openai/v1/audio/transcriptions"

# ── 阿里 DashScope Fun-ASR 配置（非流式同步） ──
_DASHSCOPE_ASR_URL = "https://dashscope.aliyuncs.com/api/v1/services/audio/asr/transcription"


def _clean_glm_tags(text: str) -> str:
    """清理 GLM-ASR 返回文本中的特殊标签（情感、事件等）"""
    # 移除 <|Speech|> <|/Speech|> <|NEUTRAL|> 等标签
    text = re.sub(r'<\|/?[A-Za-z_0-9]+\|>', '', text)
    # 合并多余空格
    text = re.sub(r'\s{2,}', ' ', text)
    return text.strip()


def _recognize_glm(tmp_path: str) -> dict | None:
    """
    使用智谱 GLM-ASR 进行语音识别。
    返回 dict 或 None（表示该引擎不可用，应降级）。
    """
    api_key = os.environ.get("ZHIPU_API_KEY", "").strip()
    if not api_key:
        return None  # 未配置，降级

    start_time = time.time()

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    try:
        with open(tmp_path, "rb") as f:
            files = {
                "file": ("audio.webm", f, "audio/webm"),
            }
            data = {
                "model": "glm-asr",
            }

            resp = requests.post(
                _ZHIPU_API_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=30,
            )

        elapsed = round(time.time() - start_time, 2)

        if resp.status_code != 200:
            logger.error("GLM-ASR HTTP %d: %s", resp.status_code, resp.text[:300])
            return None  # 降级到下一个引擎

        try:
            result = resp.json()
        except Exception:
            logger.error("GLM-ASR 返回了无效的 JSON")
            return None

        # GLM-ASR 返回格式: {"text": "识别结果", ...}
        text = result.get("text", "").strip()

        # 清理特殊标签
        text = _clean_glm_tags(text)

        # 幻觉过滤
        if is_whisper_hallucination(text):
            return {"text": "", "time": elapsed, "engine": "glm-asr"}

        return {"text": text, "time": elapsed, "engine": "glm-asr"}

    except requests.exceptions.Timeout:
        logger.error("GLM-ASR 超时")
        return None
    except requests.exceptions.ConnectionError:
        logger.error("GLM-ASR 连接失败")
        return None
    except Exception as e:
        logger.error("GLM-ASR 异常: %s", e)
        return None


def _recognize_dashscope(tmp_path: str) -> dict | None:
    """
    使用阿里 DashScope Fun-ASR 非流式同步识别。
    Fun-ASR 的 Recognition.call() 需要 dashscope SDK，
    这里用纯 REST 方式调用实时识别的 WebSocket 不方便，
    所以走录音文件异步接口——但它需要公网 URL。
    
    对于 HF Space 部署场景，音频文件没有公网 URL，
    所以这个引擎暂时不启用，留作未来扩展。
    """
    return None  # 暂不启用


def _recognize_groq(tmp_path: str) -> dict | None:
    """
    使用 Groq Whisper 进行语音识别（降级方案）。
    """
    api_key = os.environ.get("GROQ_API_KEY", "").strip()
    if not api_key:
        return None

    start_time = time.time()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "User-Agent": _USER_AGENT,
    }

    try:
        with open(tmp_path, "rb") as f:
            files = {
                "file": ("audio.webm", f, "audio/webm"),
            }
            data = {
                "model": "whisper-large-v3-turbo",
                "language": "zh",
                "prompt": "以下是一段中文对话，请使用正确的标点符号。",
                "response_format": "json",
            }

            resp = requests.post(
                _GROQ_API_URL,
                headers=headers,
                files=files,
                data=data,
                timeout=30,
            )

        elapsed = round(time.time() - start_time, 2)

        if resp.status_code != 200:
            try:
                err_body = resp.json()
                err_msg = err_body.get("error", {}).get("message", resp.text)
            except Exception:
                err_msg = resp.text
            return {"error": f"Groq API 错误 ({resp.status_code}): {err_msg}"}

        try:
            result = resp.json()
        except Exception:
            return {"error": "Groq API 返回了无效的 JSON"}

        text = result.get("text", "").strip()

        if is_whisper_hallucination(text):
            return {"text": "", "time": elapsed, "engine": "groq-whisper"}

        return {"text": text, "time": elapsed, "engine": "groq-whisper"}

    except requests.exceptions.Timeout:
        return {"error": "语音识别超时，请重试"}
    except requests.exceptions.ConnectionError:
        return {"error": "无法连接语音识别服务"}
    except Exception as e:
        return {"error": f"语音识别异常: {str(e)}"}


def recognize(audio_file):
    """
    语音识别入口。按优先级尝试：GLM-ASR → Groq Whisper。

    参数:
        audio_file: Flask request.files 中的文件对象

    返回:
        dict — 成功: { text, time, engine }
               失败: { error } 或 { text: "", message: "录音太短" }
    """
    tmp_path = None
    try:
        # 1. 保存到临时文件
        fd, tmp_path = tempfile.mkstemp(suffix=".webm")
        os.close(fd)
        audio_file.save(tmp_path)

        # 2. 检查文件大小
        file_size = os.path.getsize(tmp_path)
        if file_size < 1000:
            return {"text": "", "message": "录音太短"}

        # 3. 按优先级尝试各引擎
        engines = [
            ("GLM-ASR", _recognize_glm),
            ("Groq-Whisper", _recognize_groq),
        ]

        for name, engine_fn in engines:
            result = engine_fn(tmp_path)
            if result is not None:
                logger.info("语音识别使用引擎: %s", name)
                return result

        # 4. 所有引擎都不可用
        return {"error": "语音识别未配置（需设置 ZHIPU_API_KEY 或 GROQ_API_KEY）"}

    except Exception as e:
        return {"error": f"语音识别异常: {str(e)}"}
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
