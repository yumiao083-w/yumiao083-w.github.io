"""
记忆检索与注入模块 - 新记忆系统的核心

提供：
  1. build_memory_index()        - 构建记忆索引（summary 列表，常驻注入）
  2. retrieve_memories()         - 检索管道入口（根据配置走 LLM 精筛 / 关键词 / 关闭）
  3. retrieve_by_keyword()       - 关键词匹配检索（原版逻辑，也作为 fallback）
  4. format_retrieved_memories() - 格式化命中的详细记忆
"""

import json
import os
import re
import logging
import threading

logger = logging.getLogger(__name__)

# 默认路径
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
MEMORY_ENTRIES_FILE = os.path.join(ROOT_DIR, 'memory_entries.json')

# 缓存
_memory_entries_cache = None
_memory_entries_mtime = 0


def _load_entries():
    """加载 memory_entries.json，带文件修改时间缓存"""
    global _memory_entries_cache, _memory_entries_mtime

    if not os.path.exists(MEMORY_ENTRIES_FILE):
        logger.warning(f"记忆文件不存在: {MEMORY_ENTRIES_FILE}")
        return []

    mtime = os.path.getmtime(MEMORY_ENTRIES_FILE)
    if _memory_entries_cache is not None and mtime == _memory_entries_mtime:
        return _memory_entries_cache

    try:
        with open(MEMORY_ENTRIES_FILE, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        _memory_entries_cache = entries
        _memory_entries_mtime = mtime
        logger.debug(f"已加载 {len(entries)} 条记忆")
        return entries
    except Exception as e:
        logger.error(f"加载记忆文件失败: {e}")
        return []


def _get_entries_by_ids(ids):
    """根据 id 列表获取完整记忆条目"""
    entries = _load_entries()
    if not entries:
        return []

    # 构建 id → entry 映射
    id_map = {e['id']: e for e in entries if 'id' in e}

    result = []
    for entry_id in ids:
        if entry_id in id_map:
            result.append(id_map[entry_id])
        else:
            logger.warning(f"记忆条目 id={entry_id} 不存在")

    return result


def build_memory_index():
    """
    构建记忆索引 Markdown 文本（常驻注入）
    格式：编号列表，每条 [日期] + summary
    """
    entries = _load_entries()
    if not entries:
        return ""

    lines = ["## 记忆索引\n"]
    lines.append("以下是你与郁邈的所有记忆概要。如果当前对话涉及某条记忆，你可以自然地引用其中的情感和细节。\n")

    for e in entries:
        date = e.get('date', '?')
        summary = e.get('summary', '(无概要)')
        # 日期只取月-日
        if date and len(date) >= 10:
            short_date = date[5:]  # MM-DD
        else:
            short_date = date
        lines.append(f"{e['id']}. [{short_date}] {summary}")

    return '\n'.join(lines)


# ======================================================================
# 关键词匹配检索（原版逻辑，也作为 LLM 失败时的 fallback）
# ======================================================================

def retrieve_by_keyword(user_message, top_k=5):
    """
    关键词匹配检索：根据 event 字段做关键词命中

    Args:
        user_message: 用户发送的消息文本
        top_k: 最多返回几条

    Returns:
        list: 命中的记忆条目列表（完整条目）
    """
    entries = _load_entries()
    if not entries or not user_message:
        return []

    user_msg_lower = user_message.lower()

    scored = []
    for e in entries:
        event = e.get('event', '')
        if not event:
            continue

        # 拆分 event 关键词
        keywords = [kw.strip().lower() for kw in event.split(',') if kw.strip()]

        # 计算匹配分数
        score = 0
        for kw in keywords:
            if kw in user_msg_lower:
                score += 1
                # 较长的关键词匹配权重更高（更具体）
                if len(kw) >= 4:
                    score += 1

        if score > 0:
            scored.append((score, e))

    # 按分数降序，取 top_k
    scored.sort(key=lambda x: x[0], reverse=True)
    results = [entry for _, entry in scored[:top_k]]

    if results:
        logger.debug(f"[关键词检索] 命中 {len(results)} 条: {[r['id'] for r in results]}")

    return results


# ======================================================================
# 检索管道入口（路由）
# ======================================================================

def retrieve_memories(user_message, top_k=None, recent_context=""):
    """
    检索管道主入口：根据配置选择检索策略

    模式：
      - 'llm'     : LLM 精筛（全量 summary 丢给便宜模型选），失败降级关键词
      - 'keyword' : 仅关键词匹配（原版）
      - 'off'     : 不检索

    兼容性：保持和旧版相同的调用签名 retrieve_memories(message)，
    新增 recent_context 参数传对话上下文给 LLM 精筛。

    Args:
        user_message: str, 用户最新消息
        top_k: int or None, 返回条数（None 时从 config 读）
        recent_context: str, 最近几轮对话拼接文本（LLM 模式用）

    Returns:
        list: 命中的记忆条目列表（完整条目）
    """
    # 懒导入 config，避免循环依赖
    try:
        import config
        mode = getattr(config, 'MEMORY_RETRIEVAL_MODE', 'keyword')
        if top_k is None:
            top_k = getattr(config, 'MEMORY_RETRIEVAL_TOP_K', 5)
        fallback = getattr(config, 'MEMORY_FALLBACK_TO_KEYWORD', True)
        providers = getattr(config, 'MEMORY_LLM_PROVIDERS', [])
    except ImportError:
        mode = 'keyword'
        if top_k is None:
            top_k = 5
        fallback = True
        providers = []

    if mode == 'off':
        return []

    if mode == 'keyword':
        return retrieve_by_keyword(user_message, top_k)

    if mode == 'llm':
        # 并行策略：先跑关键词（瞬间），再跑 LLM
        keyword_results = retrieve_by_keyword(user_message, top_k)

        if not providers:
            logger.warning("[记忆检索] LLM 模式但未配置中转站，降级到关键词")
            return keyword_results

        try:
            from memory_llm_ranker import rank_memories, AllProvidersFailedError

            memory_index = build_memory_index()
            if not memory_index:
                return keyword_results

            ranked_ids = rank_memories(
                user_message=user_message,
                recent_context=recent_context,
                memory_index=memory_index,
                providers=providers,
            )

            if ranked_ids:
                llm_results = _get_entries_by_ids(ranked_ids)
                if llm_results:
                    logger.info(
                        f"[记忆检索] LLM 精筛成功，返回 {len(llm_results)} 条: "
                        f"{[r['id'] for r in llm_results]}"
                    )
                    return llm_results

            # LLM 返回了但解析不出 id，降级
            logger.warning("[记忆检索] LLM 精筛未返回有效结果，降级到关键词")
            if fallback:
                return keyword_results
            return []

        except Exception as e:
            logger.warning(f"[记忆检索] LLM 精筛失败: {e}")
            if fallback:
                logger.info("[记忆检索] 降级到关键词匹配")
                return keyword_results
            return []

    # 未知模式
    logger.warning(f"[记忆检索] 未知模式: {mode}，降级到关键词")
    return retrieve_by_keyword(user_message, top_k)


def format_retrieved_memories(memories):
    """
    格式化检索命中的详细记忆，用于注入 prompt

    Args:
        memories: retrieve_memories() 返回的条目列表

    Returns:
        str: Markdown 格式的详细记忆文本
    """
    if not memories:
        return ""

    lines = ["## 相关记忆详情\n"]
    lines.append("以下记忆与当前对话相关，供你参考：\n")

    for m in memories:
        date = m.get('date', '?')
        content = m.get('content', '')
        memo = m.get('memo', '')

        lines.append(f"### [{date}]")
        lines.append(content)
        if memo:
            lines.append(f"\n**碎碎念备忘录：**\n{memo}")
        lines.append("")  # 空行分隔

    return '\n'.join(lines)
