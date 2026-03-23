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

# 过滤 werkzeug 日志中的敏感 URL 参数
class _SanitizeFilter(logging.Filter):
    def filter(self, record):
        if hasattr(record, 'msg') and isinstance(record.msg, str):
            import re
            # 脱敏 user_info, extra_prompt, topic, custom_llm, custom_tts 等参数
            record.msg = re.sub(
                r'(user_info|extra_prompt|topic|custom_llm|custom_tts|tts_api_key|custom_api)=[^&\s"]+',
                r'\1=[REDACTED]', record.msg
            )
        return True

logging.getLogger('werkzeug').addFilter(_SanitizeFilter())

app = Flask(__name__)

# 密钥管理（启动时从 GitHub 加载，管理面板热增删，变更自动同步到 GitHub）
_valid_keys: set = set()   # 当前有效密钥池
_used_keys: set = set()    # 已使用的密钥
_active_tokens: set = set()
_guest_tokens: dict = {}   # token → 创建时间戳
_token_times: dict = {}    # token → 创建时间戳（所有token）
_keys_lock = threading.Lock()

SESSION_TIMEOUT = 1800  # 30 分钟

# 口令兑换系统
_redeem_codes: dict = {}   # code → { daily_limit, today_count, today_date, key_length }
_redeem_ip_map: dict = {}  # IP → { date, count, token } — 每IP每天限领1次，重复返回原token
_redeem_lock = threading.Lock()

# ── GitHub 持久化（密钥 + 口令）──
_GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
_GITHUB_DATA_REPO = os.environ.get("GITHUB_DATA_REPO", "yumiao083-w/voice-call-data")
_GITHUB_DATA_API = f"https://api.github.com/repos/{_GITHUB_DATA_REPO}/contents"
_gh_shas: dict = {}  # filename → sha


def _gh_headers():
    return {
        "Authorization": f"token {_GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json",
    }


def _gh_get_file(filename):
    """从 GitHub 获取文件内容，返回 (content_str, sha) 或 (None, None)"""
    if not _GITHUB_TOKEN:
        return None, None
    import requests
    try:
        resp = requests.get(f"{_GITHUB_DATA_API}/{filename}",
                            headers=_gh_headers(), timeout=15)
        if resp.status_code == 200:
            data = resp.json()
            content = base64.b64decode(data["content"]).decode("utf-8")
            return content, data["sha"]
        return None, None
    except Exception as e:
        logger.error("GitHub 读取 %s 失败: %s", filename, e)
        return None, None


def _gh_put_file(filename, content_str, sha=None):
    """写文件到 GitHub"""
    if not _GITHUB_TOKEN:
        return
    import requests
    try:
        body = {
            "message": f"sync {filename}",
            "content": base64.b64encode(content_str.encode("utf-8")).decode("ascii"),
        }
        if sha:
            body["sha"] = sha
        resp = requests.put(f"{_GITHUB_DATA_API}/{filename}",
                            headers=_gh_headers(), json=body, timeout=15)
        if resp.status_code in (200, 201):
            logger.info("GitHub 同步 %s 成功", filename)
        else:
            logger.error("GitHub 同步 %s 失败: %d %s", filename,
                         resp.status_code, resp.text[:200])
    except Exception as e:
        logger.error("GitHub 同步 %s 异常: %s", filename, e)


def _save_keys_to_github():
    """异步保存密钥数据到 GitHub"""
    with _keys_lock:
        data = {
            "valid_keys": sorted(_valid_keys),
            "used_keys": sorted(_used_keys),
        }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    sha = _gh_shas.get("keys.json")

    def _do():
        _gh_put_file("keys.json", content, sha)
        _, new_sha = _gh_get_file("keys.json")
        if new_sha:
            _gh_shas["keys.json"] = new_sha

    threading.Thread(target=_do, daemon=True).start()


def _save_redeem_to_github():
    """异步保存口令数据到 GitHub"""
    with _redeem_lock:
        data = {}
        for code, info in _redeem_codes.items():
            data[code] = {
                "daily_limit": info["daily_limit"],
                "today_count": info["today_count"],
                "today_date": info["today_date"],
                "key_length": info.get("key_length", 8),
            }
    content = json.dumps(data, ensure_ascii=False, indent=2)
    sha = _gh_shas.get("redeem.json")

    def _do():
        _gh_put_file("redeem.json", content, sha)
        _, new_sha = _gh_get_file("redeem.json")
        if new_sha:
            _gh_shas["redeem.json"] = new_sha

    threading.Thread(target=_do, daemon=True).start()


def _load_keys_and_redeem():
    """启动时从 GitHub 加载密钥和口令（不再使用环境变量）"""
    global _valid_keys, _used_keys

    # 加载密钥
    content, sha = _gh_get_file("keys.json")
    if content:
        try:
            data = json.loads(content)
            _valid_keys = set(data.get("valid_keys", []))
            _used_keys = set(data.get("used_keys", []))
            _gh_shas["keys.json"] = sha
            logger.info("从 GitHub 加载密钥成功: %d 有效, %d 已用",
                        len(_valid_keys), len(_used_keys))
        except Exception as e:
            logger.error("解析 keys.json 失败: %s", e)
    else:
        logger.info("GitHub 无 keys.json，密钥池为空（请通过管理面板添加）")

    # 加载口令
    content, sha = _gh_get_file("redeem.json")
    if content:
        try:
            data = json.loads(content)
            with _redeem_lock:
                for code, info in data.items():
                    _redeem_codes[code] = {
                        "daily_limit": info.get("daily_limit", 10),
                        "today_count": info.get("today_count", 0),
                        "today_date": info.get("today_date", ""),
                        "key_length": info.get("key_length", 8),
                    }
            _gh_shas["redeem.json"] = sha
            logger.info("从 GitHub 加载口令成功: %d 个", len(_redeem_codes))
        except Exception as e:
            logger.error("解析 redeem.json 失败: %s", e)
    else:
        logger.info("GitHub 无 redeem.json，口令为空（请通过管理面板添加）")


# 启动时加载持久化数据
_load_keys_and_redeem()

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
    # 过期检查
    if token in _token_times and time.time() - _token_times[token] > SESSION_TIMEOUT:
        _active_tokens.discard(token)
        _token_times.pop(token, None)
        _guest_tokens.pop(token, None)
        return redirect("/")
    return render_template("setup.html")


@app.route("/call")
def call():
    """通话页 — 需要有效 token"""
    token = request.args.get("token", "")
    if not token or token not in _active_tokens:
        return redirect("/")
    # 过期检查
    if token in _token_times and time.time() - _token_times[token] > SESSION_TIMEOUT:
        _active_tokens.discard(token)
        _token_times.pop(token, None)
        _guest_tokens.pop(token, None)
        return redirect("/")
    return render_template("call.html")


@app.route("/tts-api")
def tts_api_page():
    """TTS API 用户自助页面"""
    return render_template("tts_api.html")


# =====================================================================
# API 路由
# =====================================================================

@app.route("/api/auth", methods=["POST"])
def api_auth():
    """密钥验证，换取一次性 token。"""
    data = request.get_json(force=True, silent=True) or {}
    key = (data.get("key") or "").strip()
    if not key:
        return jsonify({"error": "缺少密钥"}), 400

    with _keys_lock:
        if key not in _valid_keys:
            return jsonify({"error": "密钥无效"}), 403

        if key in _used_keys:
            return jsonify({"error": "该密钥已被使用"}), 403

        token = hashlib.sha256(f"{key}_{time.time()}".encode()).hexdigest()[:16]
        _used_keys.add(key)
        _active_tokens.add(token)
        _token_times[token] = time.time()

    _save_keys_to_github()
    return jsonify({"token": token})


@app.route("/api/guest-token", methods=["POST"])
def api_guest_token():
    """
    免密钥访客令牌：用户自带 LLM + TTS API，不消耗内置资源。
    """
    token = hashlib.sha256(f"guest_{time.time()}".encode()).hexdigest()[:16]
    _active_tokens.add(token)
    _guest_tokens[token] = time.time()
    _token_times[token] = time.time()
    return jsonify({"token": token})


@app.route("/api/redeem", methods=["POST"])
def api_redeem():
    """
    口令兑换密钥。每个口令每天有限额，每个IP每天限领1次。
    重复领取不消耗名额，返回之前的token。
    """
    import secrets as _sec
    import string as _str

    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"error": "请输入口令"}), 400

    # 获取真实 IP（兼容反代）
    client_ip = request.headers.get("X-Forwarded-For", "").split(",")[0].strip() \
                or request.headers.get("X-Real-Ip", "") \
                or request.remote_addr or "unknown"

    today = time.strftime("%Y-%m-%d")

    with _redeem_lock:
        if code not in _redeem_codes:
            return jsonify({"error": "口令无效"}), 403

        info = _redeem_codes[code]

        # 日期翻转，重置计数
        if info["today_date"] != today:
            info["today_date"] = today
            info["today_count"] = 0

        # 检查这个 IP 今天是否已经领过
        ip_key = f"{client_ip}:{code}"
        ip_record = _redeem_ip_map.get(ip_key)
        if ip_record and ip_record["date"] == today:
            # 已经领过了，返回之前的 token（如果还有效的话）
            old_token = ip_record.get("token", "")
            if old_token and old_token in _active_tokens:
                # token 还活着，直接返回
                return jsonify({"key": ip_record.get("key", ""), "token": old_token, "remaining": info["daily_limit"] - info["today_count"], "reused": True})
            else:
                # token 过期了，重新生成一个，但不消耗名额
                new_token = hashlib.sha256(f"reissue_{client_ip}_{time.time()}".encode()).hexdigest()[:16]
                _active_tokens.add(new_token)
                _token_times[new_token] = time.time()
                ip_record["token"] = new_token
                return jsonify({"key": ip_record.get("key", ""), "token": new_token, "remaining": info["daily_limit"] - info["today_count"], "reused": True})

        # 检查今日总名额
        if info["today_count"] >= info["daily_limit"]:
            return jsonify({"error": f"今日名额已满（每天限{info['daily_limit']}个），明天再来吧～"}), 429

        # 生成密钥
        alphabet = _str.ascii_letters + _str.digits
        key_len = info.get("key_length", 8)
        new_key = "".join(_sec.choice(alphabet) for _ in range(key_len))

        with _keys_lock:
            while new_key in _valid_keys or new_key in _used_keys:
                new_key = "".join(_sec.choice(alphabet) for _ in range(key_len))
            _valid_keys.add(new_key)
            _used_keys.add(new_key)
            token = hashlib.sha256(f"{new_key}_{time.time()}".encode()).hexdigest()[:16]
            _active_tokens.add(token)
            _token_times[token] = time.time()

        info["today_count"] += 1
        remaining = info["daily_limit"] - info["today_count"]

        # 记录这个 IP
        _redeem_ip_map[ip_key] = {"date": today, "token": token, "key": new_key}

    _save_keys_to_github()
    _save_redeem_to_github()
    return jsonify({"key": new_key, "token": token, "remaining": remaining})


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

    # 访客 token 过期检查（30分钟）
    if token in _guest_tokens:
        if time.time() - _guest_tokens[token] > SESSION_TIMEOUT:
            _active_tokens.discard(token)
            del _guest_tokens[token]
            _token_times.pop(token, None)
            return jsonify({"error": "会话已过期（30分钟），请重新登录"}), 401

    # 所有 token 过期检查（30分钟）
    if token in _token_times:
        if time.time() - _token_times[token] > SESSION_TIMEOUT:
            _active_tokens.discard(token)
            _token_times.pop(token, None)
            _guest_tokens.pop(token, None)
            return jsonify({"error": "会话已过期（30分钟），请重新登录"}), 401

    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "缺少文本"}), 400

    session_id = data.get("session_id") or token
    custom_api = data.get("custom_api")       # dict | None
    custom_tts = data.get("custom_tts")       # dict | None
    tts_api_key = (data.get("tts_api_key") or "").strip()  # TTS API Key（计费模式）

    # 访客 token 必须自带 LLM API
    if token in _guest_tokens:
        if not custom_api or not custom_api.get("base_url") or not custom_api.get("api_key"):
            return jsonify({"error": "访客模式需要自备 LLM API（请在设置中填写 API 地址和 Key）"}), 400
        # TTS：必须提供 custom_tts 或 tts_api_key，或者用内置的
        if not custom_tts and not tts_api_key:
            # 允许不传（用内置 TTS），但如果内置也没配就会在合成时报错
            pass
    custom_prompt = data.get("custom_prompt")  # str | None
    req_model = data.get("model")             # str | None — 前端选择的模型
    max_history = min(100, max(1, int(data.get("max_history") or 20)))  # 1-100轮

    # 构建 system prompt
    parts = []
    if _builtin_prompt:
        parts.append(_builtin_prompt)
    if custom_prompt:
        parts.append(custom_prompt)
    parts.append(VOICE_INSTRUCTION)
    system_prompt = "\n\n".join(parts)

    # 获取 / 创建 session history（限制条数）
    with _sessions_lock:
        if session_id not in _sessions:
            _sessions[session_id] = []
        full_history = _sessions[session_id]
        max_msgs = max_history * 2  # 每轮一问一答
        history = list(full_history[-max_msgs:]) if len(full_history) > max_msgs else list(full_history)

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
                    if tts_api_key:
                        # TTS API Key 模式：走计费
                        result = _api_svc.call_tts(tts_api_key, sentence)
                        if "error" in result:
                            logger.error("TTS API error for sentence %d: %s", idx, result["error"])
                            q.put(json.dumps({"type": "tts_error", "text": result["error"]}, ensure_ascii=False))
                            return
                        mp3_bytes = result["audio_bytes"]
                    else:
                        # 直接调用 TTS（内置或自定义 MiniMax）
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
                # 限制历史长度（最多保留 200 条 = 100 轮）
                if len(_sessions[session_id]) > 200:
                    _sessions[session_id] = _sessions[session_id][-200:]

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
# 管理员路由 (ADMIN_PASSWORD 环境变量保护)
# =====================================================================

import secrets as _secrets
import string as _string

def _check_admin(req):
    """检查管理员密码，支持 header 和 query 参数"""
    admin_pw = os.environ.get("ADMIN_PASSWORD", "")
    if not admin_pw:
        return False
    pw = req.headers.get("X-Admin-Password", "") or req.args.get("pw", "")
    return pw == admin_pw


def _gen_key(length=8):
    """生成随机密钥：大小写字母+数字"""
    alphabet = _string.ascii_letters + _string.digits
    return "".join(_secrets.choice(alphabet) for _ in range(length))


@app.route("/admin")
def admin_page():
    """管理员页面"""
    if not _check_admin(request):
        return "未授权", 403
    return render_template("admin.html")


@app.route("/api/admin/keys", methods=["GET"])
def admin_keys_list():
    """查看所有密钥及状态"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    with _keys_lock:
        keys = []
        for k in sorted(_valid_keys):
            keys.append({
                "key": k,
                "used": k in _used_keys,
            })
    return jsonify({"keys": keys, "total": len(keys), "used": sum(1 for k in keys if k["used"]), "available": sum(1 for k in keys if not k["used"])})


@app.route("/api/admin/keys/generate", methods=["POST"])
def admin_keys_generate():
    """批量生成新密钥"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    count = min(50, max(1, int(data.get("count", 10))))
    length = min(32, max(6, int(data.get("length", 8))))
    new_keys = []
    with _keys_lock:
        for _ in range(count):
            k = _gen_key(length)
            while k in _valid_keys or k in _used_keys:
                k = _gen_key(length)
            _valid_keys.add(k)
            new_keys.append(k)
    _save_keys_to_github()
    return jsonify({"generated": new_keys, "count": len(new_keys)})


@app.route("/api/admin/keys/delete", methods=["POST"])
def admin_keys_delete():
    """删除/作废指定密钥"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    keys_to_delete = data.get("keys", [])
    if isinstance(keys_to_delete, str):
        keys_to_delete = [keys_to_delete]
    deleted = []
    with _keys_lock:
        for k in keys_to_delete:
            k = k.strip()
            if k in _valid_keys:
                _valid_keys.discard(k)
                deleted.append(k)
    if deleted:
        _save_keys_to_github()
    return jsonify({"deleted": deleted, "count": len(deleted)})


@app.route("/api/admin/keys/reset-used", methods=["POST"])
def admin_keys_reset_used():
    """重置已使用状态（让密钥可以再次使用）"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    keys_to_reset = data.get("keys", [])
    if isinstance(keys_to_reset, str):
        keys_to_reset = [keys_to_reset]
    reset = []
    with _keys_lock:
        if not keys_to_reset or keys_to_reset == ["all"]:
            reset = list(_used_keys)
            _used_keys.clear()
        else:
            for k in keys_to_reset:
                k = k.strip()
                if k in _used_keys:
                    _used_keys.discard(k)
                    reset.append(k)
    if reset:
        _save_keys_to_github()
    return jsonify({"reset": reset, "count": len(reset)})


@app.route("/api/admin/sessions", methods=["GET"])
def admin_sessions_list():
    """查看活跃会话"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    now = time.time()
    sessions = []
    for token in list(_active_tokens):
        created = _token_times.get(token, 0)
        elapsed = now - created if created else 0
        remaining = max(0, SESSION_TIMEOUT - elapsed)
        is_guest = token in _guest_tokens
        expired = remaining <= 0
        sessions.append({
            "token": token[:6] + "...",
            "type": "访客" if is_guest else "密钥",
            "created": int(created),
            "elapsed_min": round(elapsed / 60, 1),
            "remaining_min": round(remaining / 60, 1),
            "expired": expired,
        })
    return jsonify({"sessions": sessions, "total": len(sessions)})


@app.route("/api/admin/sessions/clear-expired", methods=["POST"])
def admin_sessions_clear_expired():
    """清理过期会话"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    now = time.time()
    cleared = 0
    for token in list(_active_tokens):
        created = _token_times.get(token, 0)
        if created and now - created > SESSION_TIMEOUT:
            _active_tokens.discard(token)
            _token_times.pop(token, None)
            _guest_tokens.pop(token, None)
            cleared += 1
    return jsonify({"cleared": cleared})


@app.route("/api/admin/redeem", methods=["GET"])
def admin_redeem_list():
    """查看所有口令及状态"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    today = time.strftime("%Y-%m-%d")
    with _redeem_lock:
        codes = []
        for code, info in _redeem_codes.items():
            today_count = info["today_count"] if info["today_date"] == today else 0
            codes.append({
                "code": code,
                "daily_limit": info["daily_limit"],
                "today_used": today_count,
                "today_remaining": info["daily_limit"] - today_count,
                "key_length": info.get("key_length", 8),
            })
    return jsonify({"codes": codes})


@app.route("/api/admin/redeem/add", methods=["POST"])
def admin_redeem_add():
    """添加新口令"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    if not code:
        return jsonify({"error": "口令不能为空"}), 400
    daily_limit = min(100, max(1, int(data.get("daily_limit", 10))))
    key_length = min(32, max(6, int(data.get("key_length", 8))))
    with _redeem_lock:
        _redeem_codes[code] = {
            "daily_limit": daily_limit,
            "today_count": 0,
            "today_date": "",
            "key_length": key_length,
        }
    _save_redeem_to_github()
    return jsonify({"ok": True, "code": code, "daily_limit": daily_limit})


@app.route("/api/admin/redeem/update", methods=["POST"])
def admin_redeem_update():
    """修改口令限额"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    with _redeem_lock:
        if code not in _redeem_codes:
            return jsonify({"error": "口令不存在"}), 404
        if "daily_limit" in data:
            _redeem_codes[code]["daily_limit"] = min(100, max(1, int(data["daily_limit"])))
        if "key_length" in data:
            _redeem_codes[code]["key_length"] = min(32, max(6, int(data["key_length"])))
    _save_redeem_to_github()
    return jsonify({"ok": True})


@app.route("/api/admin/redeem/delete", methods=["POST"])
def admin_redeem_delete():
    """删除口令"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    with _redeem_lock:
        if code in _redeem_codes:
            del _redeem_codes[code]
            _save_redeem_to_github()
            return jsonify({"ok": True})
    return jsonify({"error": "口令不存在"}), 404


@app.route("/api/admin/redeem/reset", methods=["POST"])
def admin_redeem_reset():
    """重置口令今日计数"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    code = (data.get("code") or "").strip()
    with _redeem_lock:
        if code in _redeem_codes:
            _redeem_codes[code]["today_count"] = 0
            _redeem_codes[code]["today_date"] = ""
            _save_redeem_to_github()
            return jsonify({"ok": True})
    return jsonify({"error": "口令不存在"}), 404


# =====================================================================
# 内置 API 配置管理
# =====================================================================

@app.route("/api/admin/api-config", methods=["GET"])
def admin_api_config_get():
    """获取所有内置 API 配置"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    from llm import get_builtin_config
    return jsonify(get_builtin_config())


@app.route("/api/admin/api-config/model", methods=["POST"])
def admin_api_config_model():
    """设置默认模型"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    model = (data.get("model") or "").strip()
    if not model:
        return jsonify({"error": "模型名不能为空"}), 400
    from llm import set_default_model
    set_default_model(model)
    return jsonify({"ok": True, "model": model})


@app.route("/api/admin/api-config/provider/add", methods=["POST"])
def admin_api_provider_add():
    """添加/更新 LLM provider"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    base_url = (data.get("base_url") or "").strip()
    keys_raw = data.get("keys", [])
    if isinstance(keys_raw, str):
        keys_raw = [k.strip() for k in keys_raw.split(",") if k.strip()]
    enabled = data.get("enabled", True)
    if not name or not base_url or not keys_raw:
        return jsonify({"error": "name, base_url, keys 必填"}), 400
    from llm import add_provider
    add_provider(name, base_url, keys_raw, enabled)
    return jsonify({"ok": True})


@app.route("/api/admin/api-config/provider/update", methods=["POST"])
def admin_api_provider_update():
    """更新 LLM provider（支持追加/删除key）"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name 必填"}), 400
    kwargs = {}
    if "base_url" in data:
        kwargs["base_url"] = data["base_url"].strip()
    if "keys" in data:
        keys_raw = data["keys"]
        if isinstance(keys_raw, str):
            keys_raw = [k.strip() for k in keys_raw.split(",") if k.strip()]
        kwargs["keys"] = keys_raw
    if "add_keys" in data:
        ak = data["add_keys"]
        if isinstance(ak, str):
            ak = [k.strip() for k in ak.split(",") if k.strip()]
        kwargs["add_keys"] = ak
    if "remove_keys" in data:
        rk = data["remove_keys"]
        if isinstance(rk, str):
            rk = [k.strip() for k in rk.split(",") if k.strip()]
        kwargs["remove_keys"] = rk
    if "enabled" in data:
        kwargs["enabled"] = bool(data["enabled"])
    from llm import update_provider
    if update_provider(name, **kwargs):
        return jsonify({"ok": True})
    return jsonify({"error": "provider 不存在"}), 404


@app.route("/api/admin/api-config/provider/delete", methods=["POST"])
def admin_api_provider_delete():
    """删除 LLM provider"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name 必填"}), 400
    from llm import delete_provider
    delete_provider(name)
    return jsonify({"ok": True})


@app.route("/api/admin/api-config/tts", methods=["POST"])
def admin_api_tts_update():
    """更新 MiniMax TTS 配置"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    from llm import update_tts_config
    update_tts_config(
        api_key=data.get("api_key", ""),
        group_id=data.get("group_id", ""),
        voice_id=data.get("voice_id", ""),
        model=data.get("model", ""),
    )
    return jsonify({"ok": True})


# =====================================================================
# TTS API 服务（用户注册/充值/调用）
# =====================================================================

import api_service as _api_svc

@app.route("/api/v1/register", methods=["POST"])
def tts_api_register():
    """用户注册，获取 API Key"""
    data = request.get_json(force=True, silent=True) or {}
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password", "")
    if not nickname:
        return jsonify({"error": "请输入昵称"}), 400
    if len(nickname) > 20:
        return jsonify({"error": "昵称最长20字"}), 400
    result = _api_svc.register_user(nickname, password)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/v1/login", methods=["POST"])
def tts_api_login():
    """用户登录，返回 API Key"""
    data = request.get_json(force=True, silent=True) or {}
    nickname = (data.get("nickname") or "").strip()
    password = data.get("password", "")
    if not nickname or not password:
        return jsonify({"error": "请输入昵称和密码"}), 400
    result = _api_svc.login_user(nickname, password)
    if "error" in result:
        return jsonify(result), 401
    return jsonify(result)


@app.route("/api/v1/balance", methods=["GET"])
def tts_api_balance():
    """查询余额"""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        api_key = request.args.get("key", "").strip()
    if not api_key:
        return jsonify({"error": "缺少 API Key"}), 401
    info = _api_svc.get_user_balance(api_key)
    if not info:
        return jsonify({"error": "API Key 无效"}), 401
    return jsonify(info)


@app.route("/api/v1/redeem", methods=["POST"])
def tts_api_redeem():
    """卡密充值"""
    data = request.get_json(force=True, silent=True) or {}
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        api_key = (data.get("api_key") or "").strip()
    card_code = (data.get("card_code") or data.get("code") or "").strip()
    if not api_key:
        return jsonify({"error": "缺少 API Key"}), 401
    if not card_code:
        return jsonify({"error": "缺少卡密"}), 400
    result = _api_svc.redeem_card(api_key, card_code)
    if "error" in result:
        return jsonify(result), 400
    return jsonify(result)


@app.route("/api/v1/tts", methods=["POST"])
def tts_api_synthesize():
    """TTS 合成接口（计费）"""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        return jsonify({"error": "缺少 API Key，请在 Header 中传 Authorization: Bearer YOUR_KEY"}), 401

    data = request.get_json(force=True, silent=True) or {}
    text = (data.get("text") or "").strip()
    model = data.get("model", "speech-2.8-hd")
    voice_id = data.get("voice_id")

    if not text:
        return jsonify({"error": "缺少 text 参数"}), 400

    result = _api_svc.call_tts(api_key, text, model, voice_id)
    if "error" in result:
        status = 402 if "余额不足" in result["error"] else 400
        return jsonify(result), status

    # 返回音频
    audio_bytes = result.pop("audio_bytes")
    resp = Response(audio_bytes, mimetype="audio/mpeg")
    resp.headers["X-Chars"] = str(result["chars"])
    resp.headers["X-Cost"] = str(result["cost_yuan"])
    resp.headers["X-Balance"] = str(result["balance_yuan"])
    return resp


@app.route("/api/v1/pricing", methods=["GET"])
def tts_api_pricing():
    """查看价格表"""
    return jsonify({
        "pricing": [
            {"model": "speech-2.8-hd", "price_yuan_per_10k_chars": 3.5, "desc": "高清·支持语气词"},
            {"model": "speech-2.8-turbo", "price_yuan_per_10k_chars": 2.0, "desc": "快速·支持语气词"},
        ],
        "note": "按字符数计费，价格与 MiniMax 官方一致"
    })


@app.route("/api/v1/usage", methods=["GET"])
def tts_api_usage():
    """查看自己的调用记录"""
    api_key = request.headers.get("Authorization", "").replace("Bearer ", "").strip()
    if not api_key:
        api_key = request.args.get("key", "").strip()
    if not api_key:
        return jsonify({"error": "缺少 API Key"}), 401
    if not _api_svc.get_user(api_key):
        return jsonify({"error": "API Key 无效"}), 401
    limit = min(50, max(5, int(request.args.get("limit", 20))))
    return jsonify({"records": _api_svc.get_user_usage(api_key, limit)})


# ── 管理面板：TTS API 管理 ──

@app.route("/api/admin/tts-users", methods=["GET"])
def admin_tts_users():
    """查看所有 TTS API 用户"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    return jsonify({"users": _api_svc.admin_list_users()})


@app.route("/api/admin/tts-cards", methods=["GET"])
def admin_tts_cards():
    """查看所有卡密"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    only_unused = request.args.get("unused", "") == "1"
    return jsonify({"cards": _api_svc.list_cards(only_unused)})


@app.route("/api/admin/tts-cards/generate", methods=["POST"])
def admin_tts_cards_generate():
    """生成卡密"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    count = min(50, max(1, int(data.get("count", 10))))
    amount_yuan = float(data.get("amount", 5))
    amount_cents = int(amount_yuan * 100)
    cards = _api_svc.generate_cards(count, amount_cents)
    return jsonify({"cards": cards, "count": len(cards)})


@app.route("/api/admin/tts-users/adjust", methods=["POST"])
def admin_tts_users_adjust():
    """手动调整用户余额"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    api_key = (data.get("api_key") or "").strip()
    amount_yuan = float(data.get("amount", 0))
    amount_cents = int(amount_yuan * 100)
    if not api_key:
        return jsonify({"error": "缺少 api_key"}), 400
    result = _api_svc.admin_adjust_balance(api_key, amount_cents)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/admin/tts-users/delete", methods=["POST"])
def admin_tts_users_delete():
    """删除用户"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    data = request.get_json(force=True, silent=True) or {}
    api_key = (data.get("api_key") or "").strip()
    result = _api_svc.admin_delete_user(api_key)
    if "error" in result:
        return jsonify(result), 404
    return jsonify(result)


@app.route("/api/admin/tts-usage", methods=["GET"])
def admin_tts_usage():
    """查看使用记录"""
    if not _check_admin(request):
        return jsonify({"error": "未授权"}), 403
    limit = min(100, max(10, int(request.args.get("limit", 50))))
    return jsonify({"records": _api_svc.admin_get_usage(limit)})


# =====================================================================
# 启动
# =====================================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 7860))
    app.run(host="0.0.0.0", port=port, debug=False)
