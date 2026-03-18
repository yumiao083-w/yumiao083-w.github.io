# -*- coding: utf-8 -*-
"""
tts_engine.py - TTS 语音合成引擎（多引擎版）

支持的引擎：
  - minimax: MiniMax T2A V2（支持克隆声音，推荐）
  - edge:    edge-tts（免费，微软预设音色）

配置方式：
  在 config.py 中设置 TTS_ENGINE / TTS_MINIMAX_* / TTS_EDGE_VOICE

依赖：
  - edge-tts: pip install edge-tts
  - minimax:  pip install requests（内置）
  - 转 ogg:   ffmpeg

用法：
  from tts_engine import text_to_ogg, text_to_mp3
  ogg_path = text_to_ogg("你好")   # 自动使用 config 中配置的引擎
"""

import asyncio
import os
import sys
import tempfile
import subprocess
import logging
import json
import time
import base64

logger = logging.getLogger(__name__)

# ===== yuan 项目路径 =====
YUAN_ROOT = os.path.dirname(os.path.abspath(__file__))
if YUAN_ROOT not in sys.path:
    sys.path.insert(0, YUAN_ROOT)


# =====================================================================
#  配置读取（从 config.py 动态加载，支持热更新）
# =====================================================================

def _get_config(key, default=None):
    """从 config.py 读取配置，支持热加载后的变化"""
    try:
        import config as cfg
        return getattr(cfg, key, default)
    except Exception:
        return default


def get_engine():
    """获取当前 TTS 引擎名称"""
    return _get_config('TTS_ENGINE', 'minimax')


# =====================================================================
#  引擎：MiniMax T2A V2
# =====================================================================

def _minimax_generate(text: str, output_path: str, fmt: str = "mp3"):
    """
    调用 MiniMax T2A V2 API 生成音频
    
    参数:
        text: 要合成的文本
        output_path: 输出文件路径
        fmt: 输出格式 "mp3" 或 "wav"
    """
    import requests

    api_key = _get_config('TTS_MINIMAX_API_KEY', '')
    group_id = _get_config('TTS_MINIMAX_GROUP_ID', '')
    voice_id = _get_config('TTS_MINIMAX_VOICE_ID', 'yuanlang')
    model = _get_config('TTS_MINIMAX_MODEL', 'speech-02-hd')
    speed = _get_config('TTS_MINIMAX_SPEED', 1.0)
    vol = _get_config('TTS_MINIMAX_VOL', 1.0)
    pitch = _get_config('TTS_MINIMAX_PITCH', 0)
    api_url = _get_config('TTS_MINIMAX_API_URL', 'https://api.minimax.chat')

    if not api_key or not group_id:
        raise ValueError("MiniMax TTS 未配置：请在 config.py 中设置 TTS_MINIMAX_API_KEY 和 TTS_MINIMAX_GROUP_ID")

    url = f"{api_url}/v1/t2a_v2?GroupId={group_id}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": model,
        "text": text,
        "voice_setting": {
            "voice_id": voice_id,
            "speed": speed,
            "vol": vol,
            "pitch": pitch,
        },
        "audio_setting": {
            "sample_rate": 32000,
            "format": fmt,
        },
    }

    logger.info(f"[TTS] MiniMax 请求: model={model}, voice={voice_id}, text={text[:80]}...")

    try:
        # MiniMax 是国内服务，绕过代理直连（避免代理断连导致长文本失败）
        session = requests.Session()
        session.trust_env = False  # 忽略环境变量中的代理设置
        resp = session.post(url, headers=headers, json=payload, timeout=60)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        raise RuntimeError("MiniMax TTS API 超时（60秒）")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"MiniMax TTS API 请求失败: {e}")

    status_code = data.get("base_resp", {}).get("status_code", -1)
    status_msg = data.get("base_resp", {}).get("status_msg", "")

    if status_code != 0:
        raise RuntimeError(f"MiniMax TTS 错误 [{status_code}]: {status_msg}")

    audio_hex = data.get("data", {}).get("audio", "")
    if not audio_hex:
        raise RuntimeError("MiniMax TTS 返回空音频")

    # MiniMax T2A V2 返回的 audio 字段是 hex 编码（不是 base64）
    try:
        audio_bytes = bytes.fromhex(audio_hex)
    except ValueError:
        # 兼容：如果哪天改成 base64 了
        audio_bytes = base64.b64decode(audio_hex)
    with open(output_path, "wb") as f:
        f.write(audio_bytes)

    logger.info(f"[TTS] MiniMax 生成完毕: {output_path} ({len(audio_bytes)} bytes)")
    return output_path


# =====================================================================
#  引擎：edge-tts
# =====================================================================

async def _edge_tts_generate(text: str, output_path: str, voice: str = "zh-CN-XiaoxiaoNeural"):
    """用 edge-tts 生成 mp3"""
    import edge_tts
    tts = edge_tts.Communicate(text, voice)
    await tts.save(output_path)


def _edge_generate(text: str, output_path: str):
    """edge-tts 同步包装"""
    voice = _get_config('TTS_EDGE_VOICE', 'zh-CN-XiaoxiaoNeural')

    # 兼容在已有事件循环（如 telegram bot）中调用
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None

    if loop and loop.is_running():
        import concurrent.futures
        with concurrent.futures.ThreadPoolExecutor() as pool:
            pool.submit(lambda: asyncio.run(_edge_tts_generate(text, output_path, voice))).result()
    else:
        asyncio.run(_edge_tts_generate(text, output_path, voice))

    logger.info(f"[TTS] edge-tts 生成完毕: {output_path} ({os.path.getsize(output_path)} bytes)")


# =====================================================================
#  统一接口
# =====================================================================

def text_to_mp3(text: str, output_path: str = None, voice: str = None) -> str:
    """
    文本 → mp3 文件
    
    自动使用 config.py 中配置的引擎。
    voice 参数仅在 edge-tts 引擎下生效（兼容旧调用）。
    返回 mp3 文件路径。
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".mp3", prefix="tts_")
        os.close(fd)

    engine = get_engine()

    if engine == "minimax":
        try:
            _minimax_generate(text, output_path, fmt="mp3")
        except Exception as e:
            logger.error(f"[TTS] MiniMax 失败，回退到 edge-tts: {e}")
            _edge_generate(text, output_path)
    elif engine == "edge":
        if voice:
            # 兼容旧接口：直接传 voice 参数
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(lambda: asyncio.run(_edge_tts_generate(text, output_path, voice))).result()
            else:
                asyncio.run(_edge_tts_generate(text, output_path, voice))
        else:
            _edge_generate(text, output_path)
    else:
        logger.warning(f"[TTS] 未知引擎 '{engine}'，使用 edge-tts")
        _edge_generate(text, output_path)

    return output_path


def text_to_ogg(text: str, output_path: str = None, voice: str = None) -> str:
    """
    文本 → ogg 文件（Telegram 语音条格式）
    MiniMax 引擎：API 输出 wav → ffmpeg 转 ogg (opus)
    edge-tts 引擎：输出 mp3 → ffmpeg 转 ogg (opus)
    返回 ogg 文件路径。
    """
    if output_path is None:
        fd, output_path = tempfile.mkstemp(suffix=".ogg", prefix="tts_")
        os.close(fd)

    engine = get_engine()

    # MiniMax 用 wav 作中间格式（标准 PCM 头，ffmpeg 100% 兼容）
    # edge-tts 用 mp3（它原生输出就是标准 mp3）
    if engine == "minimax":
        intermediate_ext = ".wav"
        intermediate_path = output_path.replace(".ogg", ".wav")
        try:
            _minimax_generate(text, intermediate_path, fmt="wav")
        except Exception as e:
            logger.error(f"[TTS] MiniMax 失败，回退到 edge-tts: {e}")
            intermediate_ext = ".mp3"
            intermediate_path = output_path.replace(".ogg", ".mp3")
            _edge_generate(text, intermediate_path)
    else:
        intermediate_ext = ".mp3"
        intermediate_path = output_path.replace(".ogg", ".mp3")
        if voice:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                loop = None
            if loop and loop.is_running():
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(lambda: asyncio.run(
                        _edge_tts_generate(text, intermediate_path, voice)
                    )).result()
            else:
                asyncio.run(_edge_tts_generate(text, intermediate_path, voice))
        else:
            _edge_generate(text, intermediate_path)

    # 中间文件 → ogg (opus)，Telegram 要求 ogg opus 格式
    cmd = [
        "ffmpeg", "-y",
        "-i", intermediate_path,
        "-c:a", "libopus",
        "-b:a", "64k",
        "-vbr", "on",
        "-compression_level", "10",
        "-application", "voip",
        output_path
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"ffmpeg 转换 ogg 失败: {result.stderr[-500:]}")
        # fallback: 直接用中间文件（Windows 下 rename 需要先删目标）
        try:
            if os.path.exists(output_path):
                os.remove(output_path)
            os.rename(intermediate_path, output_path)
        except OSError as e:
            logger.error(f"fallback rename 也失败: {e}")
            # 最后手段：直接复制
            import shutil
            shutil.copy2(intermediate_path, output_path)
        return output_path

    # 清理中间文件
    try:
        os.remove(intermediate_path)
    except OSError:
        pass

    logger.info(f"[TTS] ogg 生成完毕: {output_path} ({os.path.getsize(output_path)} bytes)")
    return output_path


# =====================================================================
#  可用音色列表（供前端/命令使用）
# =====================================================================

# edge-tts 中文语音
CHINESE_VOICES = {
    "晓晓": "zh-CN-XiaoxiaoNeural",      # 女声，温柔
    "晓伊": "zh-CN-XiaoyiNeural",        # 女声，活泼
    "云扬": "zh-CN-YunyangNeural",       # 男声，新闻播报
    "云希": "zh-CN-YunxiNeural",         # 男声，年轻
    "云健": "zh-CN-YunjianNeural",       # 男声，沉稳
    "晓萱": "zh-CN-XiaoxuanNeural",      # 女声，可爱
    "晓辰": "zh-CN-XiaochenNeural",      # 女声，成熟
    "晓涵": "zh-CN-XiaohanNeural",       # 女声，感性
    "晓梦": "zh-CN-XiaomengNeural",      # 女声，甜美
    "晓墨": "zh-CN-XiaomoNeural",        # 女声，知性
    "晓秋": "zh-CN-XiaoqiuNeural",       # 女声
    "晓睿": "zh-CN-XiaoruiNeural",       # 女声
    "晓双": "zh-CN-XiaoshuangNeural",    # 女声，儿童
    "晓颜": "zh-CN-XiaoyanNeural",       # 女声
    "晓悠": "zh-CN-XiaoyouNeural",       # 女声，儿童
    "晓甄": "zh-CN-XiaozhenNeural",      # 女声
    "云枫": "zh-CN-YunfengNeural",       # 男声
    "云皓": "zh-CN-YunhaoNeural",        # 男声
    "云夏": "zh-CN-YunxiaNeural",        # 男声，少年
    "云野": "zh-CN-YunyeNeural",         # 男声
    "云泽": "zh-CN-YunzeNeural",         # 男声
}

DEFAULT_VOICE = "zh-CN-XiaoxiaoNeural"


def get_voice_id(name_or_id: str) -> str:
    """根据中文名或 voice id 返回 edge-tts voice id"""
    if name_or_id in CHINESE_VOICES:
        return CHINESE_VOICES[name_or_id]
    if name_or_id.startswith("zh-"):
        return name_or_id
    return DEFAULT_VOICE


def get_available_engines() -> list:
    """返回可用引擎列表及当前选中的引擎"""
    current = get_engine()
    engines = [
        {
            "id": "minimax",
            "name": "MiniMax 克隆声音",
            "desc": "支持声音克隆，中文效果最佳",
            "configured": bool(_get_config('TTS_MINIMAX_API_KEY')),
            "active": current == "minimax",
        },
        {
            "id": "edge",
            "name": "Edge TTS (微软)",
            "desc": "免费，多种预设音色",
            "configured": True,  # edge-tts 不需要配置
            "active": current == "edge",
        },
    ]
    return engines


# =====================================================================
#  测试
# =====================================================================

if __name__ == "__main__":
    print("=" * 50)
    print("TTS 引擎测试")
    print("=" * 50)

    engine = get_engine()
    print(f"当前引擎: {engine}")

    test_text = "你好，我是袁朗，很高兴认识你。今天天气不错。"

    print(f"\n测试 text_to_mp3...")
    mp3 = text_to_mp3(test_text)
    print(f"  mp3: {mp3} ({os.path.getsize(mp3)} bytes)")

    print(f"\n测试 text_to_ogg...")
    ogg = text_to_ogg(test_text)
    print(f"  ogg: {ogg} ({os.path.getsize(ogg)} bytes)")

    print(f"\n可用引擎:")
    for e in get_available_engines():
        mark = "✅" if e["active"] else "  "
        cfg = "已配置" if e["configured"] else "未配置"
        print(f"  {mark} {e['id']}: {e['name']} ({cfg})")
