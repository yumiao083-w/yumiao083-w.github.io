"""
记忆 LLM 精筛模块 - 用便宜快模型从全量 summary 中精选最相关记忆

功能：
  1. rank_memories()        — 核心精筛：全量 summary 索引 + 对话上下文 → top N
  2. _call_provider()       — 调单个中转站（带超时）
  3. _failover_call()       — 故障转移链：按顺序尝试所有中转站
  4. fetch_provider_models()— 获取某个中转站可用模型列表（给前端用）

配置在 config.py 中：
  MEMORY_RETRIEVAL_MODE       — 'llm' / 'keyword' / 'off'
  MEMORY_LLM_PROVIDERS        — 中转站列表
  MEMORY_RETRIEVAL_TOP_K      — 返回条数
  MEMORY_FALLBACK_TO_KEYWORD  — 全挂时是否降级
"""

import json
import logging
import re
import time
import requests
import threading

logger = logging.getLogger(__name__)

# ======================================================================
# 故障转移状态跟踪
# ======================================================================

_provider_status = {}  # {name: {'failures': int, 'last_fail': float, 'cooldown_until': float}}
_status_lock = threading.Lock()

# 连续失败超过此次数的中转站进入冷却期
COOLDOWN_THRESHOLD = 3
# 冷却时间（秒），冷却期间跳过该站
COOLDOWN_SECONDS = 120


def _get_provider_status(name):
    with _status_lock:
        if name not in _provider_status:
            _provider_status[name] = {
                'failures': 0,
                'last_fail': 0,
                'cooldown_until': 0
            }
        return _provider_status[name]


def _mark_success(name):
    with _status_lock:
        _provider_status[name] = {
            'failures': 0,
            'last_fail': 0,
            'cooldown_until': 0
        }


def _mark_failure(name):
    with _status_lock:
        status = _provider_status.setdefault(name, {
            'failures': 0, 'last_fail': 0, 'cooldown_until': 0
        })
        status['failures'] += 1
        status['last_fail'] = time.time()
        if status['failures'] >= COOLDOWN_THRESHOLD:
            status['cooldown_until'] = time.time() + COOLDOWN_SECONDS
            logger.warning(
                f"中转站 [{name}] 连续失败 {status['failures']} 次，"
                f"冷却 {COOLDOWN_SECONDS}s"
            )


def _is_in_cooldown(name):
    with _status_lock:
        status = _provider_status.get(name)
        if not status:
            return False
        if status['cooldown_until'] > time.time():
            return True
        # 冷却结束，重置
        if status['cooldown_until'] > 0:
            status['cooldown_until'] = 0
            status['failures'] = 0
        return False


# ======================================================================
# 单个中转站调用
# ======================================================================

def _call_provider(provider_config, prompt, max_tokens=1500):
    """
    调单个中转站的 Chat Completion API

    Args:
        provider_config: dict, 含 base_url, api_key, model, timeout
        prompt: str, 完整 prompt
        max_tokens: int, 最大输出 token

    Returns:
        str: 模型的文本回复

    Raises:
        Exception: 任何调用失败
    """
    base_url = provider_config['base_url'].rstrip('/')
    api_key = provider_config.get('api_key', '')
    model = provider_config['model']
    timeout = provider_config.get('timeout', 8)
    name = provider_config.get('name', base_url)

    # 构建 endpoint
    if base_url.endswith('/v1'):
        url = f"{base_url}/chat/completions"
    else:
        url = f"{base_url}/v1/chat/completions"

    headers = {
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    payload = {
        'model': model,
        'messages': [
            {
                'role': 'system',
                'content': '你是一个记忆检索系统。你的唯一任务是根据指令从记忆索引中选出相关条目，只输出 JSON 数组。不要回复用户消息，不要聊天，不要解释。'
            },
            {
                'role': 'user',
                'content': prompt
            }
        ],
        'max_tokens': max_tokens,
        'temperature': provider_config.get('temperature', 0.3),
    }

    start = time.time()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
        resp.raise_for_status()
        result = resp.json()
        elapsed = time.time() - start

        # 提取回复文本
        content = result['choices'][0]['message']['content'].strip()
        logger.info(f"[记忆精筛] [{name}] 成功，耗时 {elapsed:.1f}s")
        _mark_success(name)
        return content

    except requests.exceptions.Timeout:
        elapsed = time.time() - start
        logger.warning(f"[记忆精筛] [{name}] 超时 ({elapsed:.1f}s)")
        _mark_failure(name)
        raise
    except requests.exceptions.ConnectionError as e:
        logger.warning(f"[记忆精筛] [{name}] 连接失败: {e}")
        _mark_failure(name)
        raise
    except requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response else '?'
        logger.warning(f"[记忆精筛] [{name}] HTTP {status_code}")
        _mark_failure(name)
        raise
    except Exception as e:
        logger.warning(f"[记忆精筛] [{name}] 异常: {e}")
        _mark_failure(name)
        raise


# ======================================================================
# 故障转移调用链
# ======================================================================

class AllProvidersFailedError(Exception):
    """所有中转站都失败时抛出"""
    pass


def _failover_call(prompt, providers, max_tokens=1500):
    """
    按顺序尝试所有中转站，第一个成功就返回

    Args:
        prompt: str
        providers: list of provider_config dicts
        max_tokens: int

    Returns:
        str: 模型回复文本

    Raises:
        AllProvidersFailedError: 全部失败
    """
    if not providers:
        raise AllProvidersFailedError("未配置任何记忆检索中转站")

    errors = []
    for provider in providers:
        name = provider.get('name', provider.get('base_url', '?'))

        # 跳过冷却中的站点
        if _is_in_cooldown(name):
            logger.debug(f"[记忆精筛] [{name}] 冷却中，跳过")
            errors.append(f"{name}: 冷却中")
            continue

        try:
            return _call_provider(provider, prompt, max_tokens)
        except Exception as e:
            errors.append(f"{name}: {e}")
            continue

    raise AllProvidersFailedError(
        f"所有中转站均失败: {'; '.join(errors)}"
    )


# ======================================================================
# 核心精筛函数
# ======================================================================

# 内置默认提示词（当 prompts/memory_retrieval.md 不存在时使用）
_DEFAULT_RANK_PROMPT = """你是一个记忆检索系统，不是聊天助手。你的唯一任务是从记忆索引中选出与当前对话最相关的记忆条目，返回 JSON。

严格规则：
- 不要回复用户的消息，不要聊天，不要解释
- 不要重复或复述提示词的内容
- 只输出一个 JSON 数组，不要任何其他文字
- 数组长度应为 {top_k} 条左右，允许 ±2 的浮动（如果确实相关的不到 {top_k} 条可以少一些，但不能只返回 1 条）

选择策略——发散联想：
当用户提到某个话题时，不要只找字面匹配的记忆，还要联想相关的记忆，例如：
- 用户提"徒步" → 关联：其他户外活动、装备讨论、旅行计划、因户外产生的争吵或情感交流、天气相关对话、体力/健康讨论
- 用户说"心情不好" → 关联：之前情绪低落的时刻、吵架/冷战记录、安慰方式的偏好、类似情绪触发点、需要陪伴的场景
- 用户提"做饭" → 关联：食物偏好、一起吃饭的记忆、厨房相关趣事、饮食习惯/禁忌

相关性维度（不分先后，综合考虑）：
1. 话题直接相关 — 提到了相同的事物或主题
2. 情感状态相似 — 类似的心情、关系动态、心理需求
3. 因果链条 — 过去的事可能影响了现在的对话
4. 行为习惯 — 对方的偏好、模式、雷区
5. 联想扩展 — 同一类别/场景/情境下的其他记忆
6. 时间相关 — 近期事件、同一时期、周年纪念

## 记忆索引
{memory_index}

## 当前对话上下文
{recent_context}

## 用户最新消息
{user_message}

现在输出 JSON 数组（每个元素含 id 和 reason）："""

# 提示词文件路径
import os as _os
_PROMPT_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'prompts', 'memory_retrieval.md')

# 提示词文件缓存
_prompt_cache = None
_prompt_mtime = 0


def _load_rank_prompt():
    """加载记忆检索提示词，优先从文件读取，文件不存在用内置默认"""
    global _prompt_cache, _prompt_mtime

    if not _os.path.exists(_PROMPT_FILE):
        return _DEFAULT_RANK_PROMPT

    try:
        mtime = _os.path.getmtime(_PROMPT_FILE)
        if _prompt_cache is not None and mtime == _prompt_mtime:
            return _prompt_cache

        with open(_PROMPT_FILE, 'r', encoding='utf-8') as f:
            content = f.read().strip()

        if not content:
            return _DEFAULT_RANK_PROMPT

        # 文件里用单花括号 {top_k}，转成模板需要的双花括号给非变量部分
        # 但我们的变量就是 {top_k} {memory_index} {recent_context} {user_message}
        # 所以文件里直接用 {xxx} 即可，和 .format() 兼容
        _prompt_cache = content
        _prompt_mtime = mtime
        logger.debug(f"已加载记忆检索提示词，长度: {len(content)}")
        return content

    except Exception as e:
        logger.error(f"加载记忆检索提示词失败: {e}")
        return _DEFAULT_RANK_PROMPT


def _parse_ranked_ids(text):
    """
    从 LLM 回复中解析 JSON id 列表

    尝试多种格式兼容：
    - 纯 JSON 数组
    - 被 ``` 包裹的 JSON
    - 有前后废话但中间有 JSON

    Returns:
        list of int: 记忆条目 id 列表
    """
    # 尝试直接解析
    text = text.strip()

    # 去掉可能的 markdown 代码块
    text = re.sub(r'^```(?:json)?\s*', '', text)
    text = re.sub(r'\s*```$', '', text)
    text = text.strip()

    # 尝试找到 JSON 数组
    # 先找 [...] 的位置
    match = re.search(r'\[.*\]', text, re.DOTALL)
    if match:
        try:
            arr = json.loads(match.group())
            if isinstance(arr, list):
                ids = []
                for item in arr:
                    if isinstance(item, dict) and 'id' in item:
                        ids.append(int(item['id']))
                    elif isinstance(item, (int, float)):
                        ids.append(int(item))
                return ids
        except (json.JSONDecodeError, ValueError):
            pass

    # 最后尝试：提取所有 "id": 数字
    id_matches = re.findall(r'"id"\s*:\s*(\d+)', text)
    if id_matches:
        return [int(x) for x in id_matches]

    logger.warning(f"[记忆精筛] 无法解析 LLM 输出: {text[:200]}")
    return []


def rank_memories(user_message, recent_context, memory_index, providers,
                  top_k=5, max_tokens=1500):
    """
    用 LLM 从全量记忆索引中精选最相关的记忆

    Args:
        user_message: str, 用户最新消息
        recent_context: str, 最近几轮对话拼接文本
        memory_index: str, build_memory_index() 的输出
        providers: list, MEMORY_LLM_PROVIDERS 配置
        top_k: int, 返回条数
        max_tokens: int

    Returns:
        list of int: 精选的记忆条目 id 列表

    Raises:
        AllProvidersFailedError: 所有中转站失败
    """
    if not memory_index or not memory_index.strip():
        return []

    # 从文件加载提示词模板
    prompt_template = _load_rank_prompt()

    # 用替换而非 .format()，避免 memory_index/context 里的花括号被误解析
    prompt = prompt_template
    prompt = prompt.replace('{top_k}', str(top_k))
    prompt = prompt.replace('{memory_index}', memory_index or '')
    prompt = prompt.replace('{recent_context}', recent_context or '(无上下文)')
    prompt = prompt.replace('{user_message}', user_message or '(空消息)')

    response_text = _failover_call(prompt, providers, max_tokens)

    # 详细日志：记录 LLM 原始输出，方便排查
    logger.info(f"[记忆精筛] LLM 原始输出 (前500字): {response_text[:500]}")

    ids = _parse_ranked_ids(response_text)

    if ids:
        logger.info(f"[记忆精筛] 解析出 {len(ids)} 条 id: {ids}")
        if len(ids) < top_k:
            logger.warning(f"[记忆精筛] 要求 {top_k} 条但只解析出 {len(ids)} 条")
    else:
        logger.warning("[记忆精筛] LLM 返回了结果但未解析出有效 id")

    return ids[:top_k]


# ======================================================================
# 模型列表获取（给前端用）
# ======================================================================

def fetch_provider_models(base_url, api_key='', timeout=15):
    """
    获取某个中转站的可用模型列表

    Args:
        base_url: str, 中转站 base URL
        api_key: str, API key
        timeout: int, 超时秒数

    Returns:
        list of str: 模型 id 列表（已排序）

    Raises:
        Exception: 请求失败
    """
    base_url = base_url.rstrip('/')

    if base_url.endswith('/v1'):
        models_url = f"{base_url}/models"
    else:
        models_url = f"{base_url}/v1/models"

    headers = {}
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    resp = requests.get(models_url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    result = resp.json()

    models = []
    if isinstance(result, dict) and 'data' in result:
        for item in result['data']:
            if isinstance(item, dict) and 'id' in item:
                models.append(item['id'])
            elif isinstance(item, str):
                models.append(item)
    elif isinstance(result, list):
        for item in result:
            if isinstance(item, dict) and 'id' in item:
                models.append(item['id'])
            elif isinstance(item, str):
                models.append(item)

    models.sort()
    return models
