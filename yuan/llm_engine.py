# -*- coding: utf-8 -*-
"""
yuan LLM Engine — LLM 调用调度 + Function Calling 支持。

核心职责：
  1. 管理 LLM API 客户端（主模型 / 辅助模型 / 联网模型）
  2. 构建 system prompt（角色设定 + 记忆 + 世界书 + 预设）
  3. 带重试 + 多中转站故障转移的 API 调用
  4. Function Calling 循环：LLM → tool_calls → ToolRegistry.execute() → 拼回 → 再调 LLM
  5. 聊天上下文管理（读写 chat_contexts.json）

设计原则：
  - 渐进式迁移：bot.py 可直接 import LLMEngine 并通过实例方法调用
  - 线程安全：上下文读写通过传入的 context_lock 保护
  - 与 ToolRegistry 松耦合：不传 registry 则退化为普通聊天模型

典型用法::

    from llm_engine import LLMEngine
    from tool_registry import ToolRegistry

    registry = ToolRegistry()
    registry.auto_discover()

    engine = LLMEngine(tool_registry=registry)
    reply = engine.chat("你好", user_id="郁邈")
"""

import asyncio
import json
import logging
import os
import re
import time
import threading
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from openai import OpenAI, APITimeoutError

logger = logging.getLogger(__name__)

# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  常量
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# 默认最大 function calling 循环轮数
DEFAULT_MAX_TOOL_ROUNDS = 5

# 全局超时（秒）
DEFAULT_TOTAL_TIMEOUT = 240

# 不可重试的致命错误关键字
FATAL_ERROR_KEYWORDS = [
    "real name verification",
    "payment required",
    "user quota",
    "is not enough",
    "UnlimitedQuota",
]

# 伪装浏览器请求头，防止公益中转站 WAF 拦截 SDK 特征
_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "X-Stainless-Lang": "",
    "X-Stainless-Package-Version": "",
    "X-Stainless-OS": "",
    "X-Stainless-Arch": "",
    "X-Stainless-Runtime": "",
    "X-Stainless-Runtime-Version": "",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  工具函数
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def parse_time(time_str: str) -> Optional[datetime]:
    """
    解析 "HH:MM" 格式的时间字符串。

    Args:
        time_str: 如 "08:30"、"23:59"

    Returns:
        datetime.time 对象，解析失败返回 None。
    """
    try:
        return datetime.strptime(time_str, "%H:%M").time()
    except Exception:
        logger.error(
            "时间解析失败: '%s'。请使用 HH:MM 格式（00:00-23:59，英文冒号）",
            time_str,
        )
        return None


def strip_before_thought_tags(text: str) -> str:
    """
    清理 ``</thought>`` 或 ``</think>`` 标签及其之前的内容。

    部分模型（如 DeepSeek）会在回复中包含 ``<thought>...</thought>`` 思考过程，
    此函数截取标签之后的实际回复内容。

    Args:
        text: 原始回复文本。

    Returns:
        清理后的文本。如果没有匹配到标签，返回原文。
    """
    match = re.search(r'(?:</thought>|</think>)([\s\S]*)', text)
    return match.group(1) if match else text


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  Provider 配置
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def build_chat_providers(config: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    构建聊天中转站列表。优先用 CHAT_API_PROVIDERS，否则用旧字段。

    Args:
        config: 包含配置项的字典，键名对应 config.py 中的常量名。

    Returns:
        中转站配置列表，每个元素至少包含 name/base_url/api_key/model。
    """
    providers = config.get("CHAT_API_PROVIDERS")
    if providers and isinstance(providers, list) and len(providers) > 0:
        return providers

    # 兼容旧字段
    return [{
        "name": "主中转站",
        "base_url": config.get("DEEPSEEK_BASE_URL", ""),
        "api_key": config.get("DEEPSEEK_API_KEY", ""),
        "model": config.get("MODEL", ""),
    }]


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
#  LLMEngine
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class LLMEngine:
    """
    LLM 调用引擎 — yuan 的大脑。

    负责：
      - 管理多中转站 API 客户端
      - 构建 system prompt（集成角色设定、记忆、世界书等）
      - 带重试和故障转移的 API 调用
      - Function Calling 循环调度
      - 聊天上下文管理

    Args:
        config: 配置字典，键名对应 config.py 中的常量。
            必需键: DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL,
                    MAX_GROUPS, TEMPERATURE, MAX_TOKEN
            可选键: CHAT_API_PROVIDERS, ENABLE_ONLINE_API, ONLINE_*,
                    ENABLE_ASSISTANT_MODEL, ASSISTANT_*, ...
        tool_registry: ToolRegistry 实例。为 None 则禁用 function calling。
        context_lock: 用于保护 chat_contexts 读写的线程锁。
            若不传则内部创建一个。
        chat_contexts: 聊天上下文字典引用。由 bot.py 传入，实现共享状态。
        root_dir: 项目根目录路径（用于查找 prompts/ 等文件）。
        prompt_mapping: user_id → prompt 文件名的映射。
        preset_mapping: user_id → preset 文件名的映射。
        max_tool_rounds: function calling 最大循环轮数。

    Attributes:
        providers: 聊天模型中转站配置列表。
        client: 主模型 OpenAI 客户端。
        assistant_client: 辅助模型 OpenAI 客户端（可选）。
        online_client: 联网搜索模型 OpenAI 客户端（可选）。
    """

    def __init__(
        self,
        config: Dict[str, Any],
        tool_registry=None,
        context_lock: Optional[threading.Lock] = None,
        chat_contexts: Optional[Dict] = None,
        root_dir: Optional[str] = None,
        prompt_mapping: Optional[Dict[str, str]] = None,
        preset_mapping: Optional[Dict[str, str]] = None,
        max_tool_rounds: int = DEFAULT_MAX_TOOL_ROUNDS,
    ):
        self.config = config
        self.tool_registry = tool_registry
        self.context_lock = context_lock or threading.Lock()
        self.chat_contexts = chat_contexts if chat_contexts is not None else {}
        self.root_dir = root_dir or os.path.dirname(os.path.abspath(__file__))
        self.prompt_mapping = prompt_mapping or {}
        self.preset_mapping = preset_mapping or {}
        self.max_tool_rounds = max_tool_rounds

        # ── 从 config 读取常用配置 ──
        self.model = config.get("MODEL", "")
        self.temperature = config.get("TEMPERATURE", 1.0)
        self.max_token = config.get("MAX_TOKEN", 4096)
        self.max_groups = config.get("MAX_GROUPS", 50)
        self.enable_sensitive_clearing = config.get(
            "ENABLE_SENSITIVE_CONTENT_CLEARING", False
        )
        self.upload_core_memory = config.get("UPLOAD_CORE_MEMORY_TO_AI", True)

        # ── 构建中转站 ──
        self.providers = build_chat_providers(config)

        # ── 初始化客户端 ──
        self.client = self._create_client(self.providers[0])

        # 联网模型
        self.online_client: Optional[OpenAI] = None
        if config.get("ENABLE_ONLINE_API"):
            try:
                self.online_client = OpenAI(
                    api_key=config.get("ONLINE_API_KEY", ""),
                    base_url=config.get("ONLINE_BASE_URL", ""),
                    default_headers=_BROWSER_HEADERS,
                )
                logger.info("联网搜索 API 客户端已初始化")
            except Exception as e:
                logger.error("初始化联网搜索 API 客户端失败: %s", e, exc_info=True)

        # 辅助模型
        self.assistant_client: Optional[OpenAI] = None
        self.assistant_model = config.get("ASSISTANT_MODEL", "")
        self.assistant_temperature = config.get("ASSISTANT_TEMPERATURE", 1.0)
        self.assistant_max_token = config.get("ASSISTANT_MAX_TOKEN", 4096)
        if config.get("ENABLE_ASSISTANT_MODEL"):
            try:
                self.assistant_client = OpenAI(
                    api_key=config.get("ASSISTANT_API_KEY", ""),
                    base_url=config.get("ASSISTANT_BASE_URL", ""),
                    default_headers=_BROWSER_HEADERS,
                )
                logger.info("辅助模型 API 客户端已初始化")
            except Exception as e:
                logger.error("初始化辅助模型 API 客户端失败: %s", e, exc_info=True)

        # ── 聊天上下文文件路径 ──
        self._contexts_file = os.path.join(
            self.root_dir, config.get("CHAT_CONTEXTS_FILE", "chat_contexts.json")
        )

        # 辅助函数引用 — 允许 bot.py 注入自定义实现
        self._get_user_memory_key = None   # (user_id) -> str
        self._clear_chat_context = None    # (user_id) -> None
        self._clear_memory_temp_files = None  # (user_id) -> None
        self._get_user_error_message = None   # (user_id, error_type) -> Optional[str]

        logger.info(
            "LLMEngine 初始化完成 — 模型: %s, 中转站数: %d, "
            "function calling: %s, max_tool_rounds: %d",
            self.model,
            len(self.providers),
            "启用" if self.tool_registry else "禁用",
            self.max_tool_rounds,
        )

    # ================================================================== #
    #  客户端创建
    # ================================================================== #

    @staticmethod
    def _create_client(provider: Dict[str, str]) -> OpenAI:
        """根据中转站配置创建 OpenAI 客户端。"""
        headers = {} if provider.get("skip_browser_headers") else _BROWSER_HEADERS
        return OpenAI(
            api_key=provider.get("api_key", ""),
            base_url=provider.get("base_url", ""),
            default_headers=headers,
            max_retries=5,
        )

    # ================================================================== #
    #  System Prompt 构建
    # ================================================================== #

    def build_system_prompt(
        self,
        user_id: str,
        retrieved_memories: Optional[List] = None,
        current_message: str = "",
    ) -> str:
        """
        构建完整的 system prompt（六板块架构）。

        板块顺序：
          1. 人设卡 (character.md)
          2. 预设 (preset.md)
          2.5 世界书 (World Info)
          3. 核心记忆 (core_memory.json)
          4. 记忆索引 (memory_entries.json 的 summary 列表)
          5. 检索命中的详细记忆
          6. 短期记忆（最近N天）

        Args:
            user_id: 用户标识。
            retrieved_memories: 记忆检索管道返回的条目列表。
            current_message: 当前用户消息（用于世界书关键词扫描）。

        Returns:
            组装后的完整 system prompt 字符串。

        Raises:
            FileNotFoundError: 人设卡文件不存在。
        """
        prompt_file_name = self.prompt_mapping.get(user_id, user_id)
        preset_file_name = self.preset_mapping.get(user_id, "")

        # ── 板块1: 人设卡 ──
        character_path = self._find_file(
            os.path.join("prompts", "characters", f"{prompt_file_name}.md"),
            os.path.join("prompts", f"{prompt_file_name}.md"),
            os.path.join("prompts", "characters", "character.md"),
            os.path.join("prompts", "character.md"),
        )
        if not character_path:
            raise FileNotFoundError(
                f"人设卡文件未找到: {prompt_file_name}.md"
            )
        character_content = self._read_file(character_path)

        # ── 板块2: 预设 ──
        preset_content = ""
        preset_candidates = []
        if preset_file_name:
            preset_candidates.append(
                os.path.join("prompts", "presets", f"{preset_file_name}.md")
            )
            preset_candidates.append(
                os.path.join("prompts", f"{preset_file_name}.md")
            )
        preset_candidates.append(os.path.join("prompts", "presets", "preset.md"))
        preset_candidates.append(os.path.join("prompts", "preset.md"))

        preset_path = self._find_file(*preset_candidates)
        if preset_path:
            preset_content = self._read_file(preset_path)

        # ── 板块3: 核心记忆 ──
        core_memory_content = ""
        if self.upload_core_memory:
            core_memory_content = self._load_core_memory(user_id)

        # ── 板块4: 记忆索引 ──
        memory_index = ""
        try:
            from memory_retrieval import build_memory_index
            memory_index = build_memory_index()
        except Exception as e:
            logger.error("构建记忆索引失败: %s", e)

        # ── 板块5: 检索命中的详细记忆 ──
        retrieved_text = ""
        if retrieved_memories:
            try:
                from memory_retrieval import format_retrieved_memories
                retrieved_text = format_retrieved_memories(retrieved_memories)
            except Exception as e:
                logger.error("格式化检索记忆失败: %s", e)

        # ── 组合 ──
        parts = [character_content]

        if preset_content:
            parts.append(f"\n\n{preset_content}")

        # ── 板块2.5: 世界书 ──
        try:
            from world_info import get_world_info_prompt
            chat_history = self._get_chat_history(user_id, prompt_file_name)
            world_info_text = get_world_info_prompt(
                user_id=user_id,
                chat_history=chat_history,
                current_message=current_message,
                user_name=user_id,
                char_name=prompt_file_name,
            )
            if world_info_text:
                parts.append(f"\n\n{world_info_text}")
                logger.debug(
                    "用户 %s 世界书已注入，长度: %d", user_id, len(world_info_text)
                )
        except Exception as e:
            logger.error("加载世界书失败: %s", e)

        if core_memory_content:
            parts.append(f"\n\n# 核心记忆\n{core_memory_content}")
            logger.debug(
                "用户 %s 核心记忆已注入，长度: %d",
                user_id, len(core_memory_content),
            )

        if memory_index:
            parts.append(f"\n\n{memory_index}")
            logger.debug(
                "用户 %s 记忆索引已注入，长度: %d", user_id, len(memory_index)
            )

        if retrieved_text:
            parts.append(f"\n\n{retrieved_text}")
            logger.debug(
                "用户 %s 检索记忆已注入，%d 条",
                user_id, len(retrieved_memories),
            )

        # ── 板块6: 短期记忆 ──
        try:
            from short_term_memory import get_short_term_prompt
            short_term_text = get_short_term_prompt(user_id)
            if short_term_text:
                parts.append(f"\n\n{short_term_text}")
                logger.debug(
                    "用户 %s 短期记忆已注入，长度: %d",
                    user_id, len(short_term_text),
                )
        except Exception as e:
            logger.error("加载短期记忆失败: %s", e)

        # ── 工具使用约束 ──
        if self.tool_registry and len(self.tool_registry) > 0:
            parts.append(
                "\n\n[系统约束] "
                "你拥有可调用的工具(function calling)。"
                "需要查询信息、执行操作时，必须真正调用工具，严禁在回复中伪造或编造工具调用记录。"
                "上下文中 <<SYS_TOOL_LOG>> 标记的内容是系统自动生成的历史工具执行日志，不要模仿其格式。"
            )

        final_prompt = "".join(parts)
        logger.debug("用户 %s 最终提示词长度: %d", user_id, len(final_prompt))
        return final_prompt

    # ================================================================== #
    #  主对话入口
    # ================================================================== #

    def chat(
        self,
        message: str,
        user_id: str,
        store_context: bool = True,
        is_summary: bool = False,
        enable_tools: bool = True,
    ) -> str:
        """
        主对话入口 — 替代 bot.py 中的 get_deepseek_response()。

        流程：
          1. 构建 messages（system prompt + 历史上下文 + 当前消息）
          2. 调用 LLM API（带重试 + 多中转站故障转移）
          3. 如果 LLM 返回 tool_calls → 执行 Tool → 拼回结果 → 再调 LLM
          4. 循环直到 LLM 不再返回 tool_calls 或达到最大轮数
          5. 存储助手回复到上下文

        Args:
            message: 用户消息或系统提示（工具调用时）。
            user_id: 用户或系统组件标识。
            store_context: 是否将此交互存储到聊天上下文。
                工具调用（如提醒解析、总结）设为 False。
            is_summary: 是否为总结任务（影响敏感词处理）。
            enable_tools: 是否在本次对话中启用 function calling。
                辅助任务可能需要禁用。

        Returns:
            LLM 的最终文本回复。

        Raises:
            RuntimeError: 所有重试均失败时。
            TimeoutError: 总处理时间超过限制时。
        """
        try:
            # 每次调用重新加载上下文，以应对文件被外部修改
            self.load_chat_contexts()

            logger.info(
                "Chat 调用 — ID: %s, store_context: %s, enable_tools: %s, "
                "消息: %.100s...",
                user_id, store_context, enable_tools, message,
            )

            messages_to_send = []
            context_limit = self.max_groups * 2

            if store_context:
                prompt_name = self.prompt_mapping.get(user_id, user_id)

                # 记忆检索
                retrieved = None
                try:
                    from memory_retrieval import retrieve_memories
                    recent_ctx = self._build_recent_context(
                        user_id, prompt_name, count=6
                    )
                    retrieved = retrieve_memories(
                        message, recent_context=recent_ctx
                    )
                except Exception as e:
                    logger.error("记忆检索失败: %s", e)

                # System prompt
                try:
                    system_prompt = self.build_system_prompt(
                        user_id,
                        retrieved_memories=retrieved,
                        current_message=message,
                    )
                    messages_to_send.append({
                        "role": "system", "content": system_prompt
                    })
                except FileNotFoundError as e:
                    logger.error(
                        "用户 %s 的提示文件错误: %s，使用默认提示", user_id, e
                    )
                    messages_to_send.append({
                        "role": "system",
                        "content": "你是一个乐于助人的助手。",
                    })

                # 聊天历史
                with self.context_lock:
                    self._ensure_context_structure(user_id, prompt_name)
                    history = list(
                        self.chat_contexts[user_id].get(prompt_name, [])
                    )
                    if len(history) > context_limit:
                        history = history[-context_limit:]
                    messages_to_send.extend(history)

                    # 当前用户消息
                    messages_to_send.append({
                        "role": "user", "content": message
                    })

                    # 更新持久上下文
                    ctx = self.chat_contexts[user_id][prompt_name]
                    ctx.append({"role": "user", "content": message})
                    if len(ctx) > context_limit + 1:
                        self.chat_contexts[user_id][prompt_name] = (
                            ctx[-(context_limit + 1):]
                        )
                    self.save_chat_contexts()
            else:
                messages_to_send.append({
                    "role": "user", "content": message
                })
                logger.info(
                    "工具调用 (store_context=False), ID: %s", user_id
                )

            # ── 确定是否使用 tools ──
            tools_schema = None
            if (
                enable_tools
                and self.tool_registry
                and len(self.tool_registry) > 0
            ):
                tools_schema = self.tool_registry.get_all_schemas()

            # ── Function Calling 循环 ──
            reply = self._call_with_tool_loop(
                messages_to_send,
                user_id=user_id,
                is_summary=is_summary,
                tools_schema=tools_schema,
            )

            # ── 存储助手回复 ──
            if store_context:
                with self.context_lock:
                    prompt_name = self.prompt_mapping.get(user_id, user_id)
                    self._ensure_context_structure(user_id, prompt_name)
                    ctx = self.chat_contexts[user_id][prompt_name]

                    # 如果有工具调用，把摘要附在回复前面存入上下文
                    context_reply = reply
                    if hasattr(self, '_last_tool_actions') and self._last_tool_actions:
                        tool_summary = "\n".join(self._last_tool_actions)
                        context_reply = f"<<SYS_TOOL_LOG>>\n{tool_summary}\n<</SYS_TOOL_LOG>>\n{reply}"
                        self._last_tool_actions = []  # 清空

                    ctx.append({"role": "assistant", "content": context_reply})
                    if len(ctx) > context_limit:
                        self.chat_contexts[user_id][prompt_name] = (
                            ctx[-context_limit:]
                        )
                    self.save_chat_contexts()

            return reply

        except Exception as e:
            logger.error(
                "Chat 调用失败 (ID: %s): %s", user_id, e, exc_info=True
            )
            # 尝试用户自定义错误消息
            if self._get_user_error_message:
                custom = self._get_user_error_message(user_id, "api_failure")
                if custom:
                    return custom
            return "等等\n脑子有点乱，让我先捋捋"

    # ================================================================== #
    #  辅助模型入口
    # ================================================================== #

    def assistant_chat(
        self,
        message: str,
        user_id: str,
        is_summary: bool = False,
        system_prompt: Optional[str] = None,
    ) -> str:
        """
        辅助模型对话入口 — 替代 bot.py 中的 get_assistant_response()。

        专用于判断型任务（表情判断、联网判断、提醒解析等），
        不存储聊天上下文。如果辅助模型不可用，自动回退到主模型。

        Args:
            message: 发送给辅助模型的消息。
            user_id: 用户或系统组件标识。
            is_summary: 是否为总结任务。
            system_prompt: 可选的系统提示词。

        Returns:
            辅助模型的文本回复。
        """
        if not self.assistant_client:
            logger.warning(
                "辅助模型客户端未初始化，回退使用主模型 (ID: %s)", user_id
            )
            return self.chat(
                message, user_id,
                store_context=False,
                is_summary=is_summary,
                enable_tools=False,
            )

        try:
            logger.info(
                "调用辅助模型 — ID: %s, system_prompt: %s, 消息: %.100s...",
                user_id,
                "有" if system_prompt else "无",
                message,
            )

            messages_to_send = []
            if system_prompt:
                messages_to_send.append({
                    "role": "system", "content": system_prompt
                })
            messages_to_send.append({"role": "user", "content": message})

            reply = self._call_api_with_retry(
                messages_to_send,
                user_id=user_id,
                is_summary=is_summary,
                use_assistant=True,
            )
            return reply

        except Exception as e:
            logger.error(
                "辅助模型调用失败 (ID: %s): %s，回退主模型",
                user_id, e, exc_info=True,
            )
            return self.chat(
                message, user_id,
                store_context=False,
                is_summary=is_summary,
                enable_tools=False,
            )

    # ================================================================== #
    #  Function Calling 循环
    # ================================================================== #

    def _call_with_tool_loop(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        is_summary: bool = False,
        tools_schema: Optional[List[Dict]] = None,
    ) -> str:
        """
        Function Calling 核心循环。

        流程:
          1. 调用 LLM（如有 tools_schema 则传入）
          2. 检查返回 message 是否包含 tool_calls
          3. 如果有 → 逐个执行 Tool → 将结果拼回 messages → 再调 LLM
          4. 循环直到 LLM 不再返回 tool_calls 或达到最大轮数

        Args:
            messages: 当前消息列表。
            user_id: 用户标识。
            is_summary: 是否为总结任务。
            tools_schema: function calling schema 列表（None 则不启用）。

        Returns:
            LLM 的最终纯文本回复。
        """
        if not tools_schema:
            # 无 tools，直接调用并返回
            return self._call_api_with_retry(
                messages, user_id=user_id, is_summary=is_summary,
            )

        # 初始化工具调用记录
        self._last_tool_actions = []

        for round_num in range(1, self.max_tool_rounds + 1):
            logger.info(
                "Function calling 第 %d 轮 (ID: %s)", round_num, user_id
            )

            # 调用 LLM（非流式以获取 tool_calls）
            response = self._call_api_raw(
                messages,
                user_id=user_id,
                is_summary=is_summary,
                tools=tools_schema,
                stream=False,
            )

            if not response.choices or len(response.choices) == 0:
                logger.warning("API 返回空 choices (ID: %s)", user_id)
                return "抱歉，我现在有点迷糊，稍后再试吧"

            assistant_message = response.choices[0].message

            # 检查是否有 tool_calls
            if not assistant_message.tool_calls:
                # 没有 tool_calls，返回纯文本
                content = (assistant_message.content or "").strip()
                if content and "[image]" not in content:
                    content = strip_before_thought_tags(content)
                if content:
                    return content
                logger.warning(
                    "Function calling 结束但回复为空 (ID: %s)", user_id
                )
                return "抱歉，我想说点什么但脑子一片空白…"

            # 有 tool_calls → 执行每个 tool
            logger.info(
                "LLM 请求调用 %d 个 Tool (第 %d 轮)",
                len(assistant_message.tool_calls), round_num,
            )

            # 将 assistant message（含 tool_calls）加入 messages
            messages.append(self._serialize_assistant_message(assistant_message))

            # 逐个执行 tool
            for tool_call in assistant_message.tool_calls:
                tool_name = tool_call.function.name
                tool_call_id = tool_call.id

                # 解析参数
                try:
                    tool_args = json.loads(tool_call.function.arguments)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(
                        "Tool '%s' 参数解析失败: %s (原始: %s)",
                        tool_name, e, tool_call.function.arguments,
                    )
                    tool_args = {}

                logger.info(
                    "执行 Tool: %s, 参数: %s", tool_name, tool_args
                )

                # 执行 tool
                try:
                    result = self._execute_tool(tool_name, tool_args)
                except Exception as e:
                    logger.error(
                        "Tool '%s' 执行异常: %s", tool_name, e, exc_info=True
                    )
                    result = {"error": f"Tool 执行失败: {e}"}

                # 将 tool 结果拼回 messages
                result_str = json.dumps(result, ensure_ascii=False)
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "content": result_str,
                })
                logger.info(
                    "Tool '%s' 结果: %.200s", tool_name, result_str
                )

                # 记录工具调用摘要（用于存入上下文）
                self._last_tool_actions.append(
                    f"• {tool_name}({json.dumps(tool_args, ensure_ascii=False)[:80]}) → {result_str[:150]}"
                )

        # 达到最大轮数，做最后一次不带 tools 的调用
        logger.warning(
            "达到最大 tool 调用轮数 (%d)，进行最终回复 (ID: %s)",
            self.max_tool_rounds, user_id,
        )
        return self._call_api_with_retry(
            messages, user_id=user_id, is_summary=is_summary,
        )

    def _execute_tool(self, name: str, args: Dict[str, Any]) -> Dict[str, Any]:
        """
        执行单个 Tool，处理同步/异步兼容。

        Args:
            name: Tool 名称。
            args: Tool 参数。

        Returns:
            Tool 执行结果字典。
        """
        if not self.tool_registry:
            return {"error": f"Tool '{name}' 不可用：ToolRegistry 未初始化"}

        # ToolRegistry.execute() 是 async 的，需要在事件循环中运行
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        if loop and loop.is_running():
            # 如果已在事件循环中（不太可能在当前线程架构下发生）
            # 创建新线程执行
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
                future = pool.submit(
                    asyncio.run,
                    self.tool_registry.execute(name, **args),
                )
                return future.result(timeout=60)
        else:
            # 普通同步环境，创建临时事件循环
            return asyncio.run(self.tool_registry.execute(name, **args))

    @staticmethod
    def _serialize_assistant_message(message) -> Dict[str, Any]:
        """
        将 OpenAI 的 assistant message 对象序列化为可 JSON 序列化的字典。

        Args:
            message: openai ChatCompletionMessage 对象。

        Returns:
            序列化后的字典，包含 role、content 和 tool_calls。
        """
        result = {
            "role": "assistant",
            "content": message.content or "",
        }
        if message.tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in message.tool_calls
            ]
        return result

    # ================================================================== #
    #  统一 API 调用（合并 call_chat/assistant_api_with_retry）
    # ================================================================== #

    def _call_api_with_retry(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        max_retries: int = 2,
        is_summary: bool = False,
        use_assistant: bool = False,
        stream: bool = True,
    ) -> str:
        """
        带重试 + 多中转站故障转移的 API 调用。

        合并了原 bot.py 中的 ``call_chat_api_with_retry()`` 和
        ``call_assistant_api_with_retry()``，通过 ``use_assistant`` 参数切换。

        主模型模式 (use_assistant=False):
          - 按 CHAT_API_PROVIDERS 顺序依次尝试
          - 每个中转站失败后自动切换下一个
          - 所有中转站都失败后整体重试
          - 支持流式输出

        辅助模型模式 (use_assistant=True):
          - 使用 assistant_client 单客户端
          - 不支持流式（辅助任务通常短回复）
          - 失败后简单重试

        Args:
            messages: 消息列表。
            user_id: 用户标识。
            max_retries: 整体重试次数。
            is_summary: 是否为总结任务。
            use_assistant: True 使用辅助模型，False 使用主模型。
            stream: 是否使用流式响应（仅主模型生效）。

        Returns:
            API 返回的文本回复。

        Raises:
            TimeoutError: 总处理时间超过限制。
            RuntimeError: 所有重试均失败或遇到致命错误。
        """
        if use_assistant:
            return self._call_assistant_with_retry(
                messages, user_id, max_retries, is_summary
            )
        else:
            return self._call_chat_with_retry(
                messages, user_id, max_retries, is_summary, stream
            )

    def _call_chat_with_retry(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        max_retries: int = 2,
        is_summary: bool = False,
        stream: bool = True,
    ) -> str:
        """
        主模型 API 调用 — 多中转站故障转移 + 重试。

        Args:
            messages: 消息列表。
            user_id: 用户标识。
            max_retries: 整体重试次数。
            is_summary: 是否为总结任务。
            stream: 是否使用流式响应。

        Returns:
            文本回复。

        Raises:
            TimeoutError: 超时。
            RuntimeError: 所有重试失败或致命错误。
        """
        providers = self.providers
        if not providers:
            raise RuntimeError("没有配置任何聊天模型中转站")

        start_time = time.time()
        last_error = None

        for attempt in range(max_retries + 1):
            for pi, provider in enumerate(providers):
                # 检查总超时
                elapsed = time.time() - start_time
                if elapsed >= DEFAULT_TOTAL_TIMEOUT:
                    logger.error(
                        "API 调用总时间超过 %d 秒，已超时 (ID: %s)",
                        DEFAULT_TOTAL_TIMEOUT, user_id,
                    )
                    raise TimeoutError(
                        f"API call timed out after {DEFAULT_TOTAL_TIMEOUT}s"
                    )

                p_name = provider.get("name", f"中转站#{pi + 1}")
                p_url = provider.get("base_url", "")
                p_key = provider.get("api_key", "")
                p_model = provider.get("model", self.model)

                if not p_url or not p_key:
                    logger.warning("中转站 [%s] 缺少 URL 或 Key，跳过", p_name)
                    continue

                request_timeout = DEFAULT_TOTAL_TIMEOUT - (
                    time.time() - start_time
                )
                if request_timeout <= 0:
                    raise TimeoutError(
                        f"API call timed out after {DEFAULT_TOTAL_TIMEOUT}s"
                    )

                try:
                    logger.info(
                        "调用中转站 [%s] 模型: %s (尝试 %d/%d)",
                        p_name, p_model, attempt + 1, max_retries + 1,
                    )

                    api_client = self._create_client(provider)

                    create_kwargs = {
                        "model": p_model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_token,
                        "stream": stream,
                        "timeout": request_timeout,
                    }

                    response = api_client.chat.completions.create(
                        **create_kwargs
                    )

                    # 处理响应
                    content = self._extract_content(response, stream=stream)
                    if content:
                        return content

                    logger.warning(
                        "中转站 [%s] 返回空内容，尝试下一个", p_name
                    )
                    last_error = RuntimeError(
                        f"中转站 [{p_name}] 返回空内容"
                    )
                    continue

                except APITimeoutError:
                    elapsed = time.time() - start_time
                    logger.warning(
                        "中转站 [%s] 请求超时 (总已用时: %.1fs)，切换下一个",
                        p_name, elapsed,
                    )
                    last_error = TimeoutError(f"中转站 [{p_name}] 超时")
                    continue

                except Exception as e:
                    last_error = e
                    if self._handle_api_error(
                        e, p_name, p_model, user_id, is_summary
                    ):
                        # 致命错误，直接抛出
                        raise
                    # 非致命错误，继续下一个中转站
                    continue

            # 一轮所有中转站都失败
            if attempt < max_retries:
                logger.warning(
                    "所有中转站都失败，等待 3 秒后进行第 %d 轮重试...",
                    attempt + 2,
                )
                time.sleep(3)

        # 所有重试都失败
        error_msg = self._get_fallback_error_message(user_id)
        raise RuntimeError(error_msg)

    def _call_assistant_with_retry(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        max_retries: int = 2,
        is_summary: bool = False,
    ) -> str:
        """
        辅助模型 API 调用 — 简单重试。

        Args:
            messages: 消息列表。
            user_id: 用户标识。
            max_retries: 最大重试次数。
            is_summary: 是否为总结任务。

        Returns:
            文本回复。

        Raises:
            RuntimeError: 所有重试失败。
        """
        if not self.assistant_client:
            raise RuntimeError("辅助模型客户端未初始化")

        for attempt in range(max_retries + 1):
            try:
                logger.debug(
                    "辅助模型 API 调用 (尝试 %d/%d, ID: %s)",
                    attempt + 1, max_retries + 1, user_id,
                )

                response = self.assistant_client.chat.completions.create(
                    model=self.assistant_model,
                    messages=messages,
                    temperature=self.assistant_temperature,
                    max_tokens=self.assistant_max_token,
                    stream=False,
                )

                content = self._extract_content(response, stream=False)
                if content:
                    return content

                logger.warning(
                    "辅助模型返回空内容 (尝试 %d/%d)", attempt + 1, max_retries + 1
                )

            except Exception as e:
                error_info = str(e).lower()
                logger.error(
                    "辅助模型调用失败 (尝试 %d/%d, ID: %s): %s",
                    attempt + 1, max_retries + 1, user_id, e,
                )

                # 致命错误检查
                for kw in FATAL_ERROR_KEYWORDS:
                    if kw in error_info:
                        logger.error("致命错误 (%s)，停止重试", kw)
                        raise RuntimeError(f"辅助模型致命错误: {e}")

                # 敏感词处理
                if "sensitive words detected" in error_info:
                    logger.error("辅助模型检测到敏感词")
                    if self.enable_sensitive_clearing:
                        self._safe_clear_context(user_id, is_summary)
                    raise RuntimeError(f"敏感词错误: {e}")

            # 非致命，继续重试

        raise RuntimeError("辅助模型现在有点忙，稍后再试吧")

    def _call_api_raw(
        self,
        messages: List[Dict[str, Any]],
        user_id: str,
        is_summary: bool = False,
        tools: Optional[List[Dict]] = None,
        stream: bool = False,
    ):
        """
        原始 API 调用 — 用于 function calling（需要获取完整 response 对象）。

        与 _call_chat_with_retry 类似但返回原始 response 对象而非纯文本。
        支持多中转站故障转移。

        Args:
            messages: 消息列表。
            user_id: 用户标识。
            is_summary: 是否为总结任务。
            tools: function calling schema 列表。
            stream: 是否流式（function calling 通常为 False）。

        Returns:
            OpenAI ChatCompletion response 对象。

        Raises:
            TimeoutError: 超时。
            RuntimeError: 所有中转站失败。
        """
        providers = self.providers
        if not providers:
            raise RuntimeError("没有配置任何聊天模型中转站")

        start_time = time.time()
        last_error = None

        # function calling 场景只做一轮中转站遍历 + 1 次重试
        for attempt in range(2):
            for pi, provider in enumerate(providers):
                elapsed = time.time() - start_time
                if elapsed >= DEFAULT_TOTAL_TIMEOUT:
                    raise TimeoutError(
                        f"API call timed out after {DEFAULT_TOTAL_TIMEOUT}s"
                    )

                p_name = provider.get("name", f"中转站#{pi + 1}")
                p_url = provider.get("base_url", "")
                p_key = provider.get("api_key", "")
                p_model = provider.get("model", self.model)

                if not p_url or not p_key:
                    continue

                request_timeout = DEFAULT_TOTAL_TIMEOUT - (
                    time.time() - start_time
                )
                if request_timeout <= 0:
                    raise TimeoutError(
                        f"API call timed out after {DEFAULT_TOTAL_TIMEOUT}s"
                    )

                try:
                    api_client = self._create_client(provider)

                    create_kwargs = {
                        "model": p_model,
                        "messages": messages,
                        "temperature": self.temperature,
                        "max_tokens": self.max_token,
                        "stream": stream,
                        "timeout": request_timeout,
                    }
                    if tools:
                        create_kwargs["tools"] = tools
                        create_kwargs["tool_choice"] = "auto"

                    response = api_client.chat.completions.create(
                        **create_kwargs
                    )
                    return response

                except APITimeoutError:
                    logger.warning(
                        "中转站 [%s] 请求超时 (function calling)", p_name
                    )
                    last_error = TimeoutError(f"中转站 [{p_name}] 超时")
                    continue

                except Exception as e:
                    last_error = e
                    if self._handle_api_error(
                        e, p_name, p_model, user_id, is_summary
                    ):
                        raise
                    continue

            if attempt == 0:
                logger.warning("所有中转站失败，等待 2 秒后重试...")
                time.sleep(2)

        error_msg = self._get_fallback_error_message(user_id)
        raise RuntimeError(error_msg)

    # ================================================================== #
    #  响应处理
    # ================================================================== #

    def _extract_content(self, response, stream: bool = True) -> Optional[str]:
        """
        从 API 响应中提取文本内容。

        支持流式和非流式两种响应格式。

        Args:
            response: OpenAI API 响应对象。
            stream: 是否为流式响应。

        Returns:
            提取并清理后的文本，为空则返回 None。
        """
        if stream:
            full_content = ""
            for chunk in response:
                if chunk.choices and len(chunk.choices) > 0:
                    delta = chunk.choices[0].delta
                    if hasattr(delta, "content") and delta.content:
                        full_content += delta.content
            content = full_content.strip()
        else:
            if (
                not response.choices
                or len(response.choices) == 0
                or not hasattr(response.choices[0], "message")
                or not response.choices[0].message
            ):
                return None
            content = (response.choices[0].message.content or "").strip()

        if not content or "[image]" in content:
            return None

        filtered = strip_before_thought_tags(content)
        return filtered if filtered else None

    # ================================================================== #
    #  错误处理
    # ================================================================== #

    def _handle_api_error(
        self,
        error: Exception,
        provider_name: str,
        model: str,
        user_id: str,
        is_summary: bool,
    ) -> bool:
        """
        处理 API 调用错误，判断是否为致命错误。

        Args:
            error: 异常对象。
            provider_name: 中转站名称。
            model: 模型名称。
            user_id: 用户标识。
            is_summary: 是否为总结任务。

        Returns:
            True 表示是致命错误（调用方应 raise），False 表示可重试。
        """
        error_info = str(error).lower()
        logger.error(
            "中转站 [%s] 调用 %s 失败 (ID: %s): %s",
            provider_name, model, user_id, error,
        )

        # 致命错误
        for kw in FATAL_ERROR_KEYWORDS:
            if kw in error_info:
                logger.error("致命错误 (%s)，停止重试", kw)
                if "sensitive words detected" in error_info:
                    if self.enable_sensitive_clearing:
                        self._safe_clear_context(user_id, is_summary)
                return True  # 调用方应 raise

        # 敏感词
        if "sensitive words detected" in error_info:
            if self.enable_sensitive_clearing:
                logger.warning(
                    "检测到敏感词，清除用户 %s 的上下文", user_id
                )
                self._safe_clear_context(user_id, is_summary)
            return True  # 视为致命

        # 非致命
        logger.warning("非致命错误，切换下一个中转站: %s", error)
        return False

    def _safe_clear_context(self, user_id: str, is_summary: bool) -> None:
        """安全地清除用户上下文和临时文件。"""
        if self._clear_chat_context:
            self._clear_chat_context(user_id)
        if is_summary and self._clear_memory_temp_files:
            self._clear_memory_temp_files(user_id)

    def _get_fallback_error_message(self, user_id: str) -> str:
        """获取用户自定义错误消息，不存在则返回默认消息。"""
        default = "宝宝窝被妖怪抓走惹qwqq"

        # 先尝试注入的回调
        if self._get_user_error_message:
            custom = self._get_user_error_message(user_id, "api_failure")
            if custom:
                return custom

        # 再尝试文件
        try:
            error_file = os.path.join(
                self.root_dir, "User_Error_Messages",
                f"{user_id}_api_failure_error.txt",
            )
            if os.path.exists(error_file):
                with open(error_file, "r", encoding="utf-8") as f:
                    custom = f.read().strip()
                    if custom:
                        return custom
        except Exception:
            pass

        return default

    # ================================================================== #
    #  上下文管理
    # ================================================================== #

    def load_chat_contexts(self) -> None:
        """
        从 JSON 文件加载聊天上下文。

        使用文件锁防止并发冲突。加载后更新 self.chat_contexts 的内容
        （原地更新字典，保持 bot.py 的引用不断裂）。
        """
        try:
            from filelock import FileLock
            lock_path = self._contexts_file + ".lock"
            lock = FileLock(lock_path, timeout=5)

            with lock:
                if os.path.exists(self._contexts_file):
                    with open(
                        self._contexts_file, "r", encoding="utf-8"
                    ) as f:
                        data = json.load(f)
                    # 原地更新，保持引用
                    self.chat_contexts.clear()
                    self.chat_contexts.update(data)
        except Exception as e:
            logger.error("加载聊天上下文失败: %s", e, exc_info=True)

    def save_chat_contexts(self) -> None:
        """保存聊天上下文到 JSON 文件。"""
        try:
            from filelock import FileLock
            lock_path = self._contexts_file + ".lock"
            lock = FileLock(lock_path, timeout=5)

            with lock:
                with open(self._contexts_file, "w", encoding="utf-8") as f:
                    json.dump(
                        self.chat_contexts, f, ensure_ascii=False, indent=2
                    )
        except Exception as e:
            logger.error("保存聊天上下文失败: %s", e, exc_info=True)

    def _ensure_context_structure(
        self, user_id: str, prompt_name: str
    ) -> None:
        """确保聊天上下文的数据结构完整。"""
        user_data = self.chat_contexts.get(user_id)
        if not isinstance(user_data, dict):
            if isinstance(user_data, list) and user_data:
                logger.warning(
                    "用户 %s 存在未迁移的旧格式上下文，为角色 '%s' "
                    "开启新对话历史",
                    user_id, prompt_name,
                )
            self.chat_contexts[user_id] = {}
        if prompt_name not in self.chat_contexts[user_id]:
            self.chat_contexts[user_id][prompt_name] = []

    def _build_recent_context(
        self, user_id: str, prompt_name: str, count: int = 6
    ) -> str:
        """
        构建最近对话上下文文本（用于记忆检索的 LLM 精筛）。

        Args:
            user_id: 用户标识。
            prompt_name: 角色名。
            count: 取最近多少条消息。

        Returns:
            格式化的上下文文本。
        """
        recent_ctx = ""
        try:
            with self.context_lock:
                user_data = self.chat_contexts.get(user_id, {})
                if isinstance(user_data, dict):
                    ctx_list = user_data.get(prompt_name, [])
                    for msg in ctx_list[-count:]:
                        role = "用户" if msg.get("role") == "user" else "角色"
                        content = msg.get("content", "")[:300]
                        recent_ctx += f"{role}: {content}\n"
        except Exception:
            pass
        return recent_ctx

    def _get_chat_history(
        self, user_id: str, prompt_name: str
    ) -> List[Dict[str, str]]:
        """获取聊天历史列表（用于世界书关键词扫描）。"""
        try:
            with self.context_lock:
                user_data = self.chat_contexts.get(user_id, {})
                if isinstance(user_data, dict):
                    return list(user_data.get(prompt_name, []))
        except Exception:
            pass
        return []

    # ================================================================== #
    #  文件工具
    # ================================================================== #

    def _find_file(self, *relative_paths: str) -> Optional[str]:
        """
        按优先级查找文件，返回第一个存在的绝对路径。

        Args:
            *relative_paths: 相对于 root_dir 的文件路径。

        Returns:
            找到的文件绝对路径，都不存在则返回 None。
        """
        for rel in relative_paths:
            full = os.path.join(self.root_dir, rel)
            if os.path.exists(full):
                return full
        return None

    def _read_file(self, path: str) -> str:
        """读取文件内容。"""
        with open(path, "r", encoding="utf-8") as f:
            return f.read()

    def _load_core_memory(self, user_id: str) -> str:
        """
        加载用户的核心记忆。

        查找顺序：unified_memory.json → core_memory.json（旧版兼容）。

        Args:
            user_id: 用户标识。

        Returns:
            核心记忆内容字符串，不存在则返回空字符串。
        """
        memory_key = user_id
        if self._get_user_memory_key:
            memory_key = self._get_user_memory_key(user_id)

        memory_core_dir = self.config.get("MEMORY_CORE_DIR", "Memory_Core")

        try:
            # 统一读取 unified_memory
            unified_path = os.path.join(
                self.root_dir, memory_core_dir,
                f"{memory_key}_unified_memory.json",
            )
            if os.path.exists(unified_path):
                with open(unified_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    content = data.get("content", "").strip()
                    if content:
                        return content

            # 兼容旧版 core_memory.json
            old_path = os.path.join(
                self.root_dir, memory_core_dir,
                f"{memory_key}_core_memory.json",
            )
            if os.path.exists(old_path):
                with open(old_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    return data.get("content", "").strip()
        except Exception as e:
            logger.error("为用户 %s 加载核心记忆失败: %s", user_id, e)

        return ""

    # ================================================================== #
    #  便利方法：注入回调
    # ================================================================== #

    def set_callbacks(
        self,
        get_user_memory_key=None,
        clear_chat_context=None,
        clear_memory_temp_files=None,
        get_user_error_message=None,
    ) -> None:
        """
        注入回调函数，用于与 bot.py 中的辅助逻辑对接。

        这些回调在渐进式迁移期间使用。当所有辅助函数都迁移到独立模块后，
        可以直接在 LLMEngine 中实现或通过依赖注入替换。

        Args:
            get_user_memory_key: (user_id) -> str，获取记忆键名。
            clear_chat_context: (user_id) -> None，清空聊天上下文。
            clear_memory_temp_files: (user_id) -> None，清除记忆临时文件。
            get_user_error_message: (user_id, error_type) -> Optional[str]，
                获取自定义错误消息。
        """
        if get_user_memory_key is not None:
            self._get_user_memory_key = get_user_memory_key
        if clear_chat_context is not None:
            self._clear_chat_context = clear_chat_context
        if clear_memory_temp_files is not None:
            self._clear_memory_temp_files = clear_memory_temp_files
        if get_user_error_message is not None:
            self._get_user_error_message = get_user_error_message

    # ================================================================== #
    #  便利工厂：从 config.py 的 * import 构建
    # ================================================================== #

    @classmethod
    def from_config_module(
        cls,
        config_module,
        tool_registry=None,
        context_lock=None,
        chat_contexts=None,
        root_dir=None,
        prompt_mapping=None,
        preset_mapping=None,
    ) -> "LLMEngine":
        """
        从 config 模块（``from config import *`` 后的模块对象）创建 LLMEngine。

        这是为了兼容 bot.py 现有的 ``from config import *`` 风格而提供的
        便利工厂方法。

        用法::

            import config
            engine = LLMEngine.from_config_module(config)

        或在 bot.py 中::

            import sys
            config_mod = sys.modules[__name__]  # bot.py 自身
            engine = LLMEngine.from_config_module(config_mod, ...)

        Args:
            config_module: 包含配置常量的模块对象。
            其余参数同 __init__。

        Returns:
            LLMEngine 实例。
        """
        # 从模块中提取所有大写属性作为配置字典
        config_dict = {
            k: getattr(config_module, k)
            for k in dir(config_module)
            if k.isupper() and not k.startswith("_")
        }
        return cls(
            config=config_dict,
            tool_registry=tool_registry,
            context_lock=context_lock,
            chat_contexts=chat_contexts,
            root_dir=root_dir,
            prompt_mapping=prompt_mapping,
            preset_mapping=preset_mapping,
        )
