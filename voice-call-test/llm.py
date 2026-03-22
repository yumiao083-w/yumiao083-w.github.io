# llm.py — LLM 调用模块（多中转站 + key轮换）

import os
import logging
import requests
from openai import OpenAI

logger = logging.getLogger(__name__)

# 浏览器伪装头
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Stainless-Lang": "",
    "X-Stainless-Package-Version": "",
    "X-Stainless-OS": "",
    "X-Stainless-Arch": "",
    "X-Stainless-Runtime": "",
    "X-Stainless-Runtime-Version": "",
}

# 组3当前使用第几个key，初始0
_provider3_index = 0


def get_providers(custom_api=None):
    """构建provider列表。custom_api优先，否则按 组3→组1→组2 排列。"""
    if custom_api:
        return [{
            "name": "custom",
            "base_url": custom_api["base_url"],
            "api_key": custom_api["api_key"],
        }]

    providers = []

    # 组3：多key轮换
    global _provider3_index
    p3_url = os.environ.get("LLM_PROVIDER3_URL", "")
    p3_keys_raw = os.environ.get("LLM_PROVIDER3_KEYS", "")
    if p3_url and p3_keys_raw:
        keys = [k.strip() for k in p3_keys_raw.split(",") if k.strip()]
        if keys:
            n = len(keys)
            # 从 _provider3_index 开始轮换排列
            rotated = [keys[(i + _provider3_index) % n] for i in range(n)]
            for idx, key in enumerate(rotated):
                providers.append({
                    "name": f"provider3-key{(_provider3_index + idx) % n}",
                    "base_url": p3_url,
                    "api_key": key,
                })

    # 组1
    p1_url = os.environ.get("LLM_PROVIDER1_URL", "")
    p1_key = os.environ.get("LLM_PROVIDER1_KEY", "")
    if p1_url and p1_key:
        providers.append({
            "name": "provider1",
            "base_url": p1_url,
            "api_key": p1_key,
        })

    # 组2
    p2_url = os.environ.get("LLM_PROVIDER2_URL", "")
    p2_key = os.environ.get("LLM_PROVIDER2_KEY", "")
    if p2_url and p2_key:
        providers.append({
            "name": "provider2",
            "base_url": p2_url,
            "api_key": p2_key,
        })

    return providers


def stream_chat(messages, model=None, custom_api=None):
    """
    流式调用LLM，遍历provider列表直到成功。
    yield 每个chunk的文本片段。
    """
    global _provider3_index

    if model is None:
        if custom_api and custom_api.get("model"):
            model = custom_api["model"]
        else:
            model = os.environ.get("LLM_MODEL", "claude-sonnet-4-20250514")

    use_model = model
    if custom_api and custom_api.get("model"):
        use_model = custom_api["model"]

    providers = get_providers(custom_api)
    if not providers:
        raise Exception("所有API均不可用")

    last_error = None
    for provider in providers:
        try:
            client = OpenAI(
                base_url=provider["base_url"],
                api_key=provider["api_key"],
                default_headers=_BROWSER_HEADERS,
            )
            response = client.chat.completions.create(
                model=use_model,
                messages=messages,
                stream=True,
                temperature=0.85,
                max_tokens=4000,
                timeout=30,
            )
            for chunk in response:
                if chunk.choices and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
            # 成功完成，直接返回
            return
        except Exception as e:
            last_error = e
            logger.error("Provider %s failed: %s", provider["name"], e)
            # 组3的key失败时更新 _provider3_index
            if provider["name"].startswith("provider3-"):
                p3_keys_raw = os.environ.get("LLM_PROVIDER3_KEYS", "")
                keys = [k.strip() for k in p3_keys_raw.split(",") if k.strip()]
                if keys:
                    _provider3_index = (_provider3_index + 1) % len(keys)
            continue

    raise Exception(f"所有API均不可用 (last error: {last_error})")


def fetch_models(base_url, api_key):
    """获取指定API端点的可用模型列表。"""
    try:
        url = base_url.rstrip("/") + "/models"
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return [m["id"] for m in data.get("data", [])]
    except Exception as e:
        logger.error("Failed to fetch models from %s: %s", base_url, e)
        return []
