# -*- coding: utf-8 -*-
"""
memory_compat.py — 记忆系统兼容层
旧 bot.py 的函数签名 → 新模块 (skills/memory/) 的类方法
"""

import os
import logging
import json
from typing import Optional, List

logger = logging.getLogger(__name__)

# 延迟初始化的全局实例
_diary_summarizer = None
_core_memory_updater = None


def _get_diary_summarizer():
    """延迟初始化 DiarySummarizer 实例"""
    global _diary_summarizer
    if _diary_summarizer is None:
        from skills.memory.diary import DiarySummarizer
        from skills.memory.core_memory import call_ai_for_summary
        # 导入 bot.py 的全局变量
        import sys; bot = sys.modules["__main__"]
        _diary_summarizer = DiarySummarizer(
            root_dir=bot.root_dir,
            prompt_mapping=bot.prompt_mapping,
            call_ai_fn=call_ai_for_summary,
        )
        # 从 config 中读取配置覆盖默认值
        try:
            from config import (MEMORY_TEMP_DIR, MEMORY_DAILY_DIR, MEMORY_SUMMARIES_DIR,
                                ENABLE_DAILY_SUMMARY, ENABLE_DIARY_SUMMARY, ENABLE_MEMO_SUMMARY)
            _diary_summarizer.memory_temp_dir = MEMORY_TEMP_DIR
            _diary_summarizer.memory_daily_dir = MEMORY_DAILY_DIR
            _diary_summarizer.memory_summaries_dir = MEMORY_SUMMARIES_DIR
            _diary_summarizer.enable_daily_summary = ENABLE_DAILY_SUMMARY
            _diary_summarizer.enable_diary_summary = ENABLE_DIARY_SUMMARY
            _diary_summarizer.enable_memo_summary = ENABLE_MEMO_SUMMARY
        except ImportError:
            pass
    return _diary_summarizer


def _get_core_memory_updater():
    """延迟初始化 CoreMemoryUpdater 实例"""
    global _core_memory_updater
    if _core_memory_updater is None:
        from skills.memory.core_memory import CoreMemoryUpdater, call_ai_for_summary
        import sys; bot = sys.modules["__main__"]
        _core_memory_updater = CoreMemoryUpdater(
            root_dir=bot.root_dir,
            prompt_mapping=bot.prompt_mapping,
            call_ai_fn=call_ai_for_summary,
            core_memory_update_in_progress=bot.core_memory_update_in_progress,
        )
        try:
            from config import MEMORY_TEMP_DIR, MEMORY_CORE_DIR, MEMORY_SUMMARIES_DIR
            _core_memory_updater.memory_temp_dir = MEMORY_TEMP_DIR
            _core_memory_updater.memory_core_dir = MEMORY_CORE_DIR
            _core_memory_updater.memory_summaries_dir = MEMORY_SUMMARIES_DIR
        except ImportError:
            pass
        try:
            from config import MAX_MESSAGE_LOG_ENTRIES
            _core_memory_updater.max_message_log_entries = MAX_MESSAGE_LOG_ENTRIES
        except ImportError:
            pass
    return _core_memory_updater


# ===== 独立函数 wrapper（直接调用新模块的顶层函数） =====

def get_user_memory_key(user_id):
    """旧签名只有 user_id，新模块需要 prompt_mapping"""
    from skills.memory.diary import get_user_memory_key as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(user_id, bot.prompt_mapping)


def is_quiet_time():
    from skills.memory.diary import is_quiet_time as _new_func
    try:
        from config import QUIET_TIME_START, QUIET_TIME_END
        return _new_func(QUIET_TIME_START, QUIET_TIME_END)
    except ImportError:
        return False


def get_user_error_message(username, error_type):
    from skills.memory.diary import get_user_error_message as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(username, error_type, bot.prompt_mapping)


def get_user_memory_prompt(username, prompt_type):
    from skills.memory.diary import get_user_memory_prompt as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(username, prompt_type, bot.root_dir, bot.prompt_mapping)


def append_to_memory_section(user_id, role_name, summary):
    from skills.memory.diary import append_to_memory_section as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(user_id, role_name, summary, bot.root_dir)


def call_ai_for_summary(prompt, user_id):
    from skills.memory.core_memory import call_ai_for_summary as _new_func
    import sys; bot = sys.modules["__main__"]
    try:
        import config
        import importlib
        importlib.reload(config)

        # 优先从 CHAT_API_PROVIDERS 读取第一个中转站（新多中转站架构）
        providers = getattr(config, 'CHAT_API_PROVIDERS', [])
        if providers and isinstance(providers, list) and len(providers) > 0:
            p = providers[0]
            base_url = p.get('base_url', '')
            api_key = p.get('api_key', '')
            model = p.get('model', '')
        else:
            # 兼容旧配置
            base_url = getattr(config, 'DEEPSEEK_BASE_URL', '')
            api_key = getattr(config, 'DEEPSEEK_API_KEY', '')
            model = getattr(config, 'MODEL', '')

        # 辅助模型配置
        enable_assistant = getattr(config, 'ENABLE_ASSISTANT_MODEL', False)
        use_assistant = getattr(config, 'USE_ASSISTANT_FOR_MEMORY_SUMMARY', True) and enable_assistant

        return _new_func(
            prompt, user_id,
            assistant_base_url=getattr(config, 'ASSISTANT_BASE_URL', ''),
            assistant_api_key=getattr(config, 'ASSISTANT_API_KEY', ''),
            assistant_model=getattr(config, 'ASSISTANT_MODEL', ''),
            deepseek_base_url=base_url,
            deepseek_api_key=api_key,
            model=model,
            enable_assistant_model=enable_assistant,
            use_assistant_for_memory=use_assistant,
            browser_headers=bot._BROWSER_HEADERS,
        )
    except Exception as e:
        logger.error(f"call_ai_for_summary 兼容层出错: {e}")
        return None


def memory_manager():
    from skills.memory.core_memory import memory_manager as _new_func
    return _new_func()


def clear_memory_temp_files(user_id):
    from skills.memory.core_memory import clear_memory_temp_files as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(user_id, bot.root_dir, bot.prompt_mapping)


def clear_chat_context(user_id):
    from skills.memory.core_memory import clear_chat_context as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(user_id, bot.chat_contexts, bot.save_chat_contexts)


def log_user_message_to_memory(username, original_content):
    from skills.memory.logger import log_message_to_memory as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(username, original_content, bot.prompt_mapping, bot.root_dir)


def get_memory_log_path(username, role_name):
    from skills.memory.logger import get_memory_log_path as _new_func
    import sys; bot = sys.modules["__main__"]
    return _new_func(username, role_name, bot.root_dir)


# ===== 类方法 wrapper（通过全局实例转发） =====

def generate_daily_summary(user_id, target_date=None):
    ds = _get_diary_summarizer()
    return ds.generate_daily_summary(user_id, target_date=target_date)


def backup_temp_log_files(user_id):
    ds = _get_diary_summarizer()
    return ds.backup_temp_log_files(user_id)


def restore_temp_log_files(user_id, backup_files):
    ds = _get_diary_summarizer()
    return ds.restore_temp_log_files(user_id, backup_files)


def cleanup_temp_backup_files(backup_files):
    from skills.memory.diary import DiarySummarizer
    return DiarySummarizer.cleanup_temp_backup_files(backup_files)


def backup_memory_summaries(user_id):
    ds = _get_diary_summarizer()
    return ds.backup_memory_summaries(user_id)


def load_existing_memory_summaries(user_id):
    ds = _get_diary_summarizer()
    return ds.load_existing_memory_summaries(user_id)


def check_core_memory_update_needed(user_id):
    cmu = _get_core_memory_updater()
    return cmu.check_core_memory_update_needed(user_id)


def generate_core_memory_update_with_cleanup(user_id, force_update=False):
    cmu = _get_core_memory_updater()
    return cmu.generate_with_cleanup(user_id, force_update=force_update)


def generate_core_memory_update(user_id, force_update=False):
    cmu = _get_core_memory_updater()
    return cmu.generate(user_id, force_update=force_update)


def clean_up_temp_files():
    """清理 wxautox 临时文件目录中超过7天的旧文件"""
    temp_dir = "wxautox文件下载"
    if not os.path.exists(temp_dir):
        return
    try:
        import time as _time
        now = _time.time()
        cutoff = now - 7 * 24 * 3600  # 7天前
        cleaned = 0
        for f in os.listdir(temp_dir):
            fpath = os.path.join(temp_dir, f)
            try:
                if os.path.isfile(fpath) and os.path.getmtime(fpath) < cutoff:
                    os.remove(fpath)
                    cleaned += 1
            except Exception:
                pass
        if cleaned:
            logger.info(f"清理了 {cleaned} 个超过7天的临时文件")
    except Exception as e:
        logger.error(f"清理临时文件失败: {e}")
