# -*- coding: utf-8 -*-
"""
llm_compat.py — LLM 调用兼容层
旧 bot.py 的函数签名 → 新模块 (llm_engine.py + skills/memory/tags.py)
"""

import sys
import os
import logging
import threading
from typing import Optional

logger = logging.getLogger(__name__)

# 延迟初始化的全局 LLMEngine 实例
_engine = None
_engine_lock = threading.Lock()


def _get_engine():
    """延迟初始化 LLMEngine 实例"""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                from llm_engine import LLMEngine
                import config
                bot = sys.modules["__main__"]
                _engine = LLMEngine.from_config_module(
                    config,
                    tool_registry=getattr(bot, 'tool_registry', None),
                    context_lock=getattr(bot, 'queue_lock', None),
                    chat_contexts=getattr(bot, 'chat_contexts', None),
                    root_dir=getattr(bot, 'root_dir', None),
                    prompt_mapping=getattr(bot, 'prompt_mapping', None),
                    preset_mapping=getattr(bot, 'preset_mapping', None),
                )
    return _engine


def init_engine(tool_registry=None):
    """在 main() 中 tool_registry 初始化完成后调用，更新 engine 的 tool_registry"""
    engine = _get_engine()
    if tool_registry is not None:
        engine.tool_registry = tool_registry


# ===== 旧函数 wrapper =====

def get_deepseek_response(message, user_id, store_context=True, is_summary=False):
    """旧 bot.py 的主对话入口 → LLMEngine.chat()"""
    engine = _get_engine()
    return engine.chat(
        message=message,
        user_id=user_id,
        store_context=store_context,
        is_summary=is_summary,
    )


def get_assistant_response(message, user_id, is_summary=False, system_prompt=None):
    """辅助模型对话 → LLMEngine.assistant_chat()"""
    engine = _get_engine()
    return engine.assistant_chat(
        message=message,
        user_id=user_id,
        is_summary=is_summary,
        system_prompt=system_prompt,
    )


def call_chat_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """带重试的 API 调用 → LLMEngine._call_chat_with_retry()"""
    engine = _get_engine()
    return engine._call_chat_with_retry(
        messages_to_send=messages_to_send,
        user_id=user_id,
        max_retries=max_retries,
        is_summary=is_summary,
    )


def call_assistant_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """辅助模型带重试 → LLMEngine._call_assistant_with_retry()"""
    engine = _get_engine()
    return engine._call_assistant_with_retry(
        messages_to_send=messages_to_send,
        user_id=user_id,
        max_retries=max_retries,
        is_summary=is_summary,
    )


# load_chat_contexts 和 save_chat_contexts 保留在 bot.py 中
# 因为它们直接操作 bot.py 的全局 chat_contexts dict，
# 走 engine 会修改 engine 自己的 dict，与 bot.py 脱节。


def strip_before_thought_tags(text):
    """清理 before_thought 标签"""
    from llm_engine import strip_before_thought_tags as _new_func
    return _new_func(text)


# ===== 记忆标签相关（从 skills/memory/tags.py 导入） =====

def load_memory_prompt(prompt_type, default_prompt):
    from skills.memory.tags import load_memory_prompt as _new_func
    bot = sys.modules["__main__"]
    return _new_func(prompt_type, default_prompt, root_dir=bot.root_dir)


def extract_memory_tags(text):
    from skills.memory.tags import extract_memory_tags as _new_func
    return _new_func(text)


def extract_save_memory_tag(text):
    from skills.memory.tags import extract_save_memory_tag as _new_func
    return _new_func(text)


def async_generate_memory_entry(user_id, tag_description, user_message, ai_reply):
    from skills.memory.tags import async_generate_memory_entry as _new_func
    bot = sys.modules["__main__"]
    return _new_func(
        user_id, tag_description, user_message, ai_reply,
        root_dir=bot.root_dir,
        prompt_mapping=bot.prompt_mapping,
        chat_contexts=bot.chat_contexts,
        queue_lock=bot.queue_lock,
        call_ai_fn=call_ai_for_summary,
    )


def async_update_core_memory(user_id, tag_description, user_message, ai_reply):
    from skills.memory.tags import async_update_core_memory as _new_func
    bot = sys.modules["__main__"]
    return _new_func(
        user_id, tag_description, user_message, ai_reply,
        root_dir=bot.root_dir,
        prompt_mapping=bot.prompt_mapping,
        call_ai_fn=call_ai_for_summary,
    )


def call_ai_for_summary(prompt, user_id):
    """转发到 memory_compat 的实现"""
    from memory_compat import call_ai_for_summary as _fn
    return _fn(prompt, user_id)
