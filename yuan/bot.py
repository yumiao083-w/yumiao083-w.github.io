# -*- coding: utf-8 -*-

import sys
import base64
import requests
import logging
import string
from datetime import datetime
import datetime as dt
import threading
import uiautomation as auto
import time
from wxautox_wechatbot import WeChat
import uiautomation as uia
from openai import OpenAI, APITimeoutError
import random
from typing import Optional
import pyautogui
import pyperclip
import shutil
import re
from regex_patterns import QINGLI_AI_BIAOQIAN_ZHUJIE
from config import *
import queue
import json
from threading import Timer
from bs4 import BeautifulSoup
EMOJI_SEND_INTERVAL = 1.0  # 发送表情包的延迟(秒)
TEXT_SEND_INTERVAL = 0.5   # 发送文本消息的延迟(秒)
from urllib.parse import urlparse
import os
os.environ["PROJECT_NAME"] = 'iwyxdxl/WeChatBot_WXAUTO_SE'
from wxautox_wechatbot.param import WxParam
WxParam.ENABLE_FILE_LOGGER = False
WxParam.FORCE_MESSAGE_XBIAS = True
from intiface_controller import parse_and_execute, start_intiface_background_thread, INTIFACE_THREAD_STARTED, enable_remote_control, disable_remote_control
from filelock import FileLock
# 全局变量区域
is_sending_message = False  # 发送状态标志
can_send_messages_lock = threading.Lock()  # 发送锁
ui_action_lock = threading.Lock()  # <-- 它在这里，非常重要！负责所有UI操作！
# 在你现有的全局变量附近添加这两行：
is_recognizing_image = False  # 标记是否正在识别图片
is_recognizing_image_lock = threading.Lock()  # 对应的锁

# === AI 动作时间戳记录 (防刷屏) ===
ai_action_timestamps = {
    'pat_timestamps': [],
    'recall_timestamps': []
}
ai_action_lock = threading.Lock() # <-- 新增的锁也在这里！负责记录时间戳！
import reply_sender
from types import SimpleNamespace # 也需要在 bot.py 中导入

# 生成用户昵称列表和prompt映射字典
user_names = [entry[0] for entry in LISTEN_LIST]
prompt_mapping = {entry[0]: entry[1] for entry in LISTEN_LIST}
# 生成预设映射（新版四元素格式 [nick, character, auto, preset]）
preset_mapping = {}
for entry in LISTEN_LIST:
    if len(entry) >= 4 and entry[3]:
        preset_mapping[entry[0]] = entry[3]
# 生成用户自动消息开关映射 (兼容旧版本格式)
auto_message_mapping = {}
for entry in LISTEN_LIST:
    if len(entry) >= 3:
        auto_message_mapping[entry[0]] = entry[2]  # 第三个参数为自动消息开关
    else:
        auto_message_mapping[entry[0]] = True  # 兼容旧版本，默认启用

# config.py 热加载支持
_config_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'config.py')
_config_last_mtime = os.path.getmtime(_config_path) if os.path.exists(_config_path) else 0

def reload_listen_list():
    """从 config.py 重新加载 LISTEN_LIST 及相关映射，无需重启 bot"""
    global user_names, prompt_mapping, preset_mapping, auto_message_mapping, _config_last_mtime
    try:
        config_vars = {}
        with open(_config_path, 'r', encoding='utf-8') as f:
            exec(f.read(), config_vars)
        new_list = config_vars.get('LISTEN_LIST', [])
        if not new_list:
            logger.warning("热加载: config.py 中 LISTEN_LIST 为空，跳过更新")
            return False
        
        old_names = set(user_names)
        user_names.clear()
        user_names.extend([entry[0] for entry in new_list])
        
        prompt_mapping.clear()
        prompt_mapping.update({entry[0]: entry[1] for entry in new_list})
        
        preset_mapping.clear()
        for entry in new_list:
            if len(entry) >= 4 and entry[3]:
                preset_mapping[entry[0]] = entry[3]
        
        auto_message_mapping.clear()
        for entry in new_list:
            if len(entry) >= 3:
                auto_message_mapping[entry[0]] = entry[2]
            else:
                auto_message_mapping[entry[0]] = True
        
        _config_last_mtime = os.path.getmtime(_config_path)
        new_names = set(user_names)
        added = new_names - old_names
        removed = old_names - new_names
        changes = []
        if added: changes.append(f"新增: {added}")
        if removed: changes.append(f"移除: {removed}")
        logger.info(f"热加载 LISTEN_LIST 成功: {len(new_list)} 个用户. {'; '.join(changes) if changes else '无变化'}")
        return True
    except Exception as e:
        logger.error(f"热加载 LISTEN_LIST 失败: {e}")
        return False

def check_config_reload():
    """检查 config.py 是否被修改，如果是则热加载"""
    global _config_last_mtime
    try:
        current_mtime = os.path.getmtime(_config_path)
        if current_mtime > _config_last_mtime:
            logger.info(f"检测到 config.py 已修改 (mtime: {_config_last_mtime} → {current_mtime})，开始热加载...")
            reload_listen_list()
    except Exception as e:
        logger.debug(f"检查 config.py 修改时间失败: {e}")


# 持续监听消息, 并且收到消息后回复
wait = 1  # 设置1秒查看一次是否有新消息

# 获取程序根目录
root_dir = os.path.dirname(os.path.abspath(__file__))

# 用户消息队列和聊天上下文管理
user_queues = {}  # {user_id: {'messages': [], 'last_message_time': 时间戳, ...}}
queue_lock = threading.Lock()  # 队列访问锁
chat_contexts = {}  # {user_id: [{'role': 'user', 'content': '...'}, ...]}
CHAT_CONTEXTS_FILE = "chat_contexts.json" # 存储聊天上下文的文件名

# === 全局消息队列和消费线程 ===
message_queue = queue.Queue()  # ✅ 添加这一行

USER_TIMERS_FILE = "user_timers.json"  # 存储用户计时器状态的文件名
MEMORY_SUMMARIES_DIR = "Memory_Summaries" # 存储用户记忆总结的目录（兼容旧版本）

# === 核心记忆系统变量 ===
core_memory_update_in_progress = {}  # {user_id: bool} 标记是否有正在进行的核心记忆更新任务

# --- 新增: [已读不回] 功能相关变量 ---
ignore_counter = {}  # {user_id: consecutive_count} 用于跟踪每个用户连续 [已读不回] 的次数
ignore_counter_lock = threading.Lock()  # 已读不回计数器访问锁

# --- 新增: 用于跟踪正在进行的记忆总结任务, 防止对同一用户重复启动 ---
active_summary_tasks = set()
active_summary_tasks_lock = threading.Lock()


# --- 动态设置相关全局变量 ---(新增部分)                            
SETTINGS_FILE = "settings.json"  # 存储动态设置的配置文件名
EMOJI_TAG_MAX_LENGTH = 10  # 默认值, 如果配置文件不存在或读取失败时使用
settings_lock = threading.Lock() # 用于文件读写的锁

def load_settings():
    """从 settings.json 加载设置到全局变量"""
    global EMOJI_TAG_MAX_LENGTH
    with settings_lock:
        try:
            # 确保我们使用的是根目录下的文件
            settings_path = os.path.join(root_dir, SETTINGS_FILE)
            if os.path.exists(settings_path):
                with open(settings_path, 'r', encoding='utf-8') as f:
                    settings = json.load(f)
                    # 从文件中读取配置, 如果键不存在或类型错误, 则使用默认值
                    EMOJI_TAG_MAX_LENGTH = int(settings.get('emoji_tag_max_length', 10))
                    logger.info(f"成功从 {SETTINGS_FILE} 加载设置, 表情包字符限制为: {EMOJI_TAG_MAX_LENGTH}")
            else:
                # 如果文件不存在, 仅记录日志, 不创建文件, 等待 config_editor 创建
                logger.info(f"{SETTINGS_FILE} 未找到, 将使用默认表情包字符限制: {EMOJI_TAG_MAX_LENGTH}")
        except (json.JSONDecodeError, ValueError, TypeError) as e:
            logger.error(f"加载 {SETTINGS_FILE} 失败, 将使用默认表情包字符限制.错误: {e}")
            EMOJI_TAG_MAX_LENGTH = 10 # 出错时回退到默认值
        except Exception as e:
            logger.error(f"加载配置文件时发生未知错误: {e}", exc_info=True)
            EMOJI_TAG_MAX_LENGTH = 10 # 出错时回退到默认值
                       ## (新增部分结束)

# 心跳相关全局变量
HEARTBEAT_INTERVAL = 5  # 秒
FLASK_SERVER_URL_BASE = f'http://localhost:{PORT}' # 使用从config导入的PORT

# --- REMINDER RELATED GLOBALS ---
RECURRING_REMINDERS_FILE = "recurring_reminders.json" # 存储重复和长期一次性提醒的文件名
# recurring_reminders 结构:
# [{'reminder_type': 'recurring', 'user_id': 'xxx', 'time_str': 'HH:MM', 'content': '...'},
#  {'reminder_type': 'one-off', 'user_id': 'xxx', 'target_datetime_str': 'YYYY-MM-DD HH:MM', 'content': '...'}]
recurring_reminders = [] # 内存中加载的提醒列表
recurring_reminder_lock = threading.RLock() # 锁, 用于处理提醒文件和列表的读写

active_timers = {} # { (user_id, timer_id): Timer_object } (用于短期一次性提醒 < 10min)

# 日程提醒防重复发送机制：存储已发送的提醒标识 (username, schedule_id, reminder_type, reminder_time_str)
sent_schedule_reminders = set()
sent_reminders_cleanup_time = None  # 上次清理时间
timer_lock = threading.Lock()
next_timer_id = 0

# ===== 日志系统（委托给 core/logger.py） =====
from core.logger import setup_logging, AsyncHTTPHandler, NoSelfLoggingFilter
async_http_handler = setup_logging()
logger = logging.getLogger()

# 获取微信窗口对象
try:
    wx = WeChat()
    logger.info(f"\033[32m微信初始化成功！当前微信版本：{wx.version if hasattr(wx, 'version') else '未知'}\033[0m")
except Exception as e:  # ✅ 改成 Exception as e
    logger.error(f"\033[31m无法初始化微信接口！\033[0m")
    logger.error(f"\033[31m详细错误：{str(e)}\033[0m")  # ✅ 添加这一行
    logger.error(f"\033[31m请确保您安装的是微信3.9版本，并且已经登录！\033[0m")
    logger.error("\033[31m微信3.9版本下载地址:https://dldir1v6.qq.com/weixin/Windows/WeChatSetup.exe \033[0m")
    import traceback
    traceback.print_exc()  # ✅ 添加这一行，打印完整错误堆栈
    exit(1)
# 获取登录用户的名字
ROBOT_WX_NAME = wx.nickname

# 存储用户的计时器和随机等待时间
user_timers = {}
user_wait_times = {}
emoji_timer = None
emoji_timer_lock = threading.Lock()
# 全局变量, 控制消息发送状态
can_send_messages = True

# --- 定时重启相关全局变量 ---
program_start_time = 0.0 # 程序启动时间戳
last_received_message_timestamp = 0.0 # 最后一次活动(收到/处理消息)的时间戳

# --- 核心记忆更新状态跟踪 ---
# 用于防止同一用户的重复核心记忆更新任务
core_memory_update_in_progress = {}  # {user_id: bool}

# 伪装浏览器请求头，防止公益中转站 WAF 拦截 SDK 特征
_BROWSER_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "X-Stainless-Lang": "",
    "X-Stainless-Package-Version": "",
    "X-Stainless-OS": "",
    "X-Stainless-Arch": "",
    "X-Stainless-Runtime": "",
    "X-Stainless-Runtime-Version": "",
}

# 构建聊天模型中转站列表（兼容旧配置）
def _build_chat_providers():
    """构建聊天中转站列表，优先用 CHAT_API_PROVIDERS，否则用旧字段"""
    try:
        providers = CHAT_API_PROVIDERS
        if providers and isinstance(providers, list) and len(providers) > 0:
            return providers
    except NameError:
        pass
    # 兼容：没有 CHAT_API_PROVIDERS 时用旧字段
    return [{
        'name': '主中转站',
        'base_url': DEEPSEEK_BASE_URL,
        'api_key': DEEPSEEK_API_KEY,
        'model': MODEL,
    }]

_chat_providers = _build_chat_providers()

# 初始化OpenAI客户端（用第一个中转站）
client = OpenAI(
    api_key=_chat_providers[0]['api_key'],
    base_url=_chat_providers[0]['base_url'],
    default_headers=_BROWSER_HEADERS
)

#初始化在线 AI 客户端 (如果启用)
online_client: Optional[OpenAI] = None
if ENABLE_ONLINE_API:
    try:
        online_client = OpenAI(
            api_key=ONLINE_API_KEY,
            base_url=ONLINE_BASE_URL,
            default_headers=_BROWSER_HEADERS
        )
        logger.info("联网搜索 API 客户端已初始化.")
    except Exception as e:
        logger.error(f"初始化联网搜索 API 客户端失败: {e}", exc_info=True)
        ENABLE_ONLINE_API = False # 初始化失败则禁用该功能
        logger.warning("由于初始化失败, 联网搜索功能已被禁用.")

# 初始化辅助模型客户端 (如果启用)
assistant_client: Optional[OpenAI] = None
if ENABLE_ASSISTANT_MODEL:
    try:
        assistant_client = OpenAI(
            api_key=ASSISTANT_API_KEY,
            base_url=ASSISTANT_BASE_URL,
            default_headers=_BROWSER_HEADERS
        )
        logger.info("辅助模型 API 客户端已初始化.")
    except Exception as e:
        logger.error(f"初始化辅助模型 API 客户端失败: {e}", exc_info=True)
        ENABLE_ASSISTANT_MODEL = False # 初始化失败则禁用该功能
        logger.warning("由于初始化失败, 辅助模型功能已被禁用.")


def parse_time(time_str):
    try:
        TimeResult = datetime.strptime(time_str, "%H:%M").time()
        return TimeResult
    except Exception as e:
        logger.error("\033[31m错误:主动消息安静时间设置有误！请填00:00-23:59 不要填24:00,并请注意中间的符号为英文冒号！\033[0m")

quiet_time_start = parse_time(QUIET_TIME_START)
quiet_time_end = parse_time(QUIET_TIME_END)

def check_user_timeouts():
    """
    检查用户是否超时未活动, 并将主动消息加入队列以触发联网检查流程. 
    """
    global last_received_message_timestamp # 引用全局变量
    if ENABLE_AUTO_MESSAGE:
        while True:
            current_epoch_time = time.time()

            for user in user_names:
                # 检查该用户是否启用了自动消息功能
                if not auto_message_mapping.get(user, True):
                    continue  # 跳过未启用自动消息的用户
                    
                last_active = user_timers.get(user)
                wait_time = user_wait_times.get(user)

                if isinstance(last_active, (int, float)) and isinstance(wait_time, (int, float)):
                    if current_epoch_time - last_active >= wait_time and not is_quiet_time():
                        
                        # 构造主动消息(模拟用户消息格式)
                        formatted_now = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
                        auto_content = f"触发主动发消息:[{formatted_now}] {AUTO_MESSAGE}"
                        logger.info(f"为用户 {user} 生成主动消息并加入队列: {auto_content}")

                        # 将主动消息加入队列(模拟用户消息)
                        with queue_lock:
                            if user not in user_queues:
                                user_queues[user] = {
                                    'messages': [auto_content],
                                    'sender_name': user,
                                    'username': user,
                                    'last_message_time': time.time()
                                }
                            else:
                                user_queues[user]['messages'].append(auto_content)
                                user_queues[user]['last_message_time'] = time.time()

                        # 更新全局的最后消息活动时间戳, 因为机器人主动发消息也算一种活动
                        last_received_message_timestamp = time.time()

                        # 重置计时器(不触发 on_user_message)
                        reset_user_timer(user)
            time.sleep(10)

def reset_user_timer(user):
    user_timers[user] = time.time()
    user_wait_times[user] = get_random_wait_time()

def get_random_wait_time():
    return random.uniform(MIN_COUNTDOWN_HOURS, MAX_COUNTDOWN_HOURS) * 3600  # 转换为秒

# 当接收到用户的新消息时, 调用此函数
def on_user_message(user):
    if user not in user_names:
        user_names.append(user)
    reset_user_timer(user)

def get_user_prompt(user_id, retrieved_memories=None):
    """
    获取用户的完整提示词（新版五板块架构）。
    
    注入顺序（优先级从高到低）：
      1. 人设卡 (character.md)
      2. 预设 (preset.md) 
      3. 核心记忆 (core_memory.json — AI 动态维护的情感模式)
      4. 记忆索引 (memory_entries.json 的 summary 列表，常驻)
      5. 检索命中的详细记忆 (retrieved_memories，按需注入)
    
    Args:
        user_id: 用户 ID
        retrieved_memories: 检索管道返回的记忆条目列表（可选）
    """
    from memory_retrieval import build_memory_index, format_retrieved_memories
    
    prompt_file_name = prompt_mapping.get(user_id, user_id)
    preset_file_name = preset_mapping.get(user_id, '')
    
    # ========== 板块1: 人设卡 ==========
    # 查找优先级: characters/ 子目录 → prompts/ 根目录 → 回退到 character.md
    character_path = None
    search_paths = [
        os.path.join(root_dir, 'prompts', 'characters', f'{prompt_file_name}.md'),
        os.path.join(root_dir, 'prompts', f'{prompt_file_name}.md'),
        os.path.join(root_dir, 'prompts', 'characters', 'character.md'),
        os.path.join(root_dir, 'prompts', 'character.md'),
    ]
    for p in search_paths:
        if os.path.exists(p):
            character_path = p
            break
    
    if not character_path:
        logger.error(f"人设卡文件不存在，已搜索: {search_paths}")
        raise FileNotFoundError(f"人设卡文件未找到: {prompt_file_name}.md")

    with open(character_path, 'r', encoding='utf-8') as file:
        character_content = file.read()

    # ========== 板块2: 预设 ==========
    preset_content = ""
    preset_search = []
    if preset_file_name:
        preset_search.append(os.path.join(root_dir, 'prompts', 'presets', f'{preset_file_name}.md'))
        preset_search.append(os.path.join(root_dir, 'prompts', f'{preset_file_name}.md'))
    preset_search.append(os.path.join(root_dir, 'prompts', 'presets', 'preset.md'))
    preset_search.append(os.path.join(root_dir, 'prompts', 'preset.md'))
    
    for p in preset_search:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as file:
                preset_content = file.read()
            break
    
    # ========== 板块3: 核心记忆 ==========
    core_memory_content = ""
    if UPLOAD_CORE_MEMORY_TO_AI:
        memory_key = get_user_memory_key(user_id)
        try:
            # 统一读取 Memory_Core 的 unified_memory 文件
            unified_memory_file = os.path.join(root_dir, MEMORY_CORE_DIR, f'{memory_key}_unified_memory.json')
            if os.path.exists(unified_memory_file):
                with open(unified_memory_file, 'r', encoding='utf-8') as f:
                    memory_data = json.load(f)
                    core_memory_content = memory_data.get("content", "").strip()
            
            # 兼容旧版: core_memory.json
            if not core_memory_content:
                old_core_file = os.path.join(root_dir, MEMORY_CORE_DIR, f'{memory_key}_core_memory.json')
                if os.path.exists(old_core_file):
                    with open(old_core_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        core_memory_content = data.get("content", "").strip()
        except Exception as e:
            logger.error(f"为用户 {user_id} 加载核心记忆失败: {e}")

    # ========== 板块4: 记忆索引 ==========
    memory_index = ""
    try:
        memory_index = build_memory_index()
    except Exception as e:
        logger.error(f"构建记忆索引失败: {e}")

    # ========== 板块5: 检索命中的详细记忆 ==========
    retrieved_text = ""
    if retrieved_memories:
        try:
            retrieved_text = format_retrieved_memories(retrieved_memories)
        except Exception as e:
            logger.error(f"格式化检索记忆失败: {e}")

    # ========== 组合 ==========
    final_prompt_parts = [character_content]
    
    if preset_content:
        final_prompt_parts.append(f"\n\n{preset_content}")
    
    # ========== 板块2.5: 世界书（World Info） ==========
    try:
        from world_info import get_world_info_prompt
        # 获取聊天历史用于关键词扫描
        _wi_history = []
        try:
            with queue_lock:
                _wi_user_data = chat_contexts.get(user_id, {})
                if isinstance(_wi_user_data, dict):
                    _wi_history = list(_wi_user_data.get(prompt_file_name, []))
        except Exception:
            pass
        world_info_text = get_world_info_prompt(
            user_id=user_id,
            chat_history=_wi_history,
            current_message="",  # 当前消息在 chat_with_gpt 里才有
            user_name=user_id,
            char_name=prompt_file_name,
        )
        if world_info_text:
            final_prompt_parts.append(f"\n\n{world_info_text}")
            logger.debug(f"用户 {user_id} 世界书已注入，长度: {len(world_info_text)}")
    except Exception as e:
        logger.error(f"加载世界书失败: {e}")

    if core_memory_content:
        final_prompt_parts.append(f"\n\n# 核心记忆\n{core_memory_content}")
        logger.debug(f"用户 {user_id} 核心记忆已注入，长度: {len(core_memory_content)}")
    
    if memory_index:
        final_prompt_parts.append(f"\n\n{memory_index}")
        logger.debug(f"用户 {user_id} 记忆索引已注入，长度: {len(memory_index)}")
    
    if retrieved_text:
        final_prompt_parts.append(f"\n\n{retrieved_text}")
        logger.debug(f"用户 {user_id} 检索记忆已注入，{len(retrieved_memories)} 条")

    # ========== 板块6: 短期记忆（最近N天） ==========
    try:
        from short_term_memory import get_short_term_prompt
        short_term_text = get_short_term_prompt(user_id)
        if short_term_text:
            final_prompt_parts.append(f"\n\n{short_term_text}")
            logger.debug(f"用户 {user_id} 短期记忆已注入，长度: {len(short_term_text)}")
    except Exception as e:
        logger.error(f"加载短期记忆失败: {e}")

    final_prompt = "".join(final_prompt_parts)
    logger.debug(f"用户 {user_id} 最终提示词长度: {len(final_prompt)}")
    
    return final_prompt


# ===== 旧版 get_user_prompt 备份（如需回退取消注释） =====
# def get_user_prompt_legacy(user_id):
#     """旧版 get_user_prompt，保留以备回退"""
#     prompt_file_name = prompt_mapping.get(user_id, user_id)
#     prompt_path = os.path.join(root_dir, 'prompts', f'{prompt_file_name}.md')
#     if not os.path.exists(prompt_path):
#         raise FileNotFoundError(f"Prompt文件 {prompt_file_name}.md 未找到于 prompts 目录")
#     with open(prompt_path, 'r', encoding='utf-8') as file:
#         prompt_content = file.read()
#     if not UPLOAD_CORE_MEMORY_TO_AI:
#         return prompt_content
#     # ... (旧版完整代码已在 git 历史中保留)

from filelock import FileLock  # 需要先安装: pip install filelock

# 加载聊天上下文
def load_chat_contexts():
    """从文件加载聊天上下文，使用文件锁防止并发冲突。"""
    global chat_contexts
    lock = FileLock(CHAT_CONTEXTS_FILE + ".lock", timeout=10)
    
    try:
        with lock:
            if os.path.exists(CHAT_CONTEXTS_FILE):
                with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                    loaded_contexts = json.load(f)
                    if isinstance(loaded_contexts, dict):
                        chat_contexts = loaded_contexts
                        logger.info(f"成功从 {CHAT_CONTEXTS_FILE} 加载 {len(chat_contexts)} 个用户的聊天上下文.")
                    else:
                        logger.warning(f"{CHAT_CONTEXTS_FILE} 文件内容格式不正确, 将使用空上下文.")
                        chat_contexts = {}
            else:
                logger.info(f"{CHAT_CONTEXTS_FILE} 未找到, 将使用空聊天上下文启动.")
                chat_contexts = {}
                
    except json.JSONDecodeError:
        logger.error(f"解析 {CHAT_CONTEXTS_FILE} 失败, 文件可能已损坏. 将使用空上下文.")
        chat_contexts = {}
    except Exception as e:
        logger.error(f"加载聊天上下文失败: {e}", exc_info=True)
        chat_contexts = {}

# 保存聊天上下文
def save_chat_contexts():
    """将当前聊天上下文保存到文件，使用文件锁防止并发冲突。"""
    global chat_contexts
    lock = FileLock(CHAT_CONTEXTS_FILE + ".lock", timeout=10)
    temp_file_path = CHAT_CONTEXTS_FILE + ".tmp"
    
    try:
        with lock:
            contexts_to_save = dict(chat_contexts)  # 创建副本
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(contexts_to_save, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file_path, CHAT_CONTEXTS_FILE)  # 原子替换
            logger.debug(f"聊天上下文已成功保存到 {CHAT_CONTEXTS_FILE}")
            
    except Exception as e:
        logger.error(f"保存聊天上下文失败: {e}", exc_info=True)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass
            

# ===== 记忆系统（委托给 memory_compat.py → skills/memory/） =====
from memory_compat import (
    clean_up_temp_files, append_to_memory_section, is_quiet_time,
    get_user_memory_key, get_user_error_message, get_user_memory_prompt,
    generate_daily_summary, backup_temp_log_files, restore_temp_log_files,
    cleanup_temp_backup_files, backup_memory_summaries, load_existing_memory_summaries,
    check_core_memory_update_needed, generate_core_memory_update_with_cleanup,
    generate_core_memory_update, call_ai_for_summary, memory_manager,
    clear_memory_temp_files, clear_chat_context,
    log_user_message_to_memory, get_memory_log_path,
)

# ===== 运维监控函数（委托给 core/monitor.py） =====
from core.monitor import (
    monitor_memory_usage, scheduled_restart_checker, short_term_memory_scheduler,
    send_heartbeat, heartbeat_thread_func, save_user_timers, load_user_timers,
    initialize_all_user_timers, status_self_check,
)

# ===== LLM 调用核心（委托给 llm_compat.py → llm_engine.py） =====
from llm_compat import (
    get_deepseek_response, get_assistant_response,
    call_chat_api_with_retry, call_assistant_api_with_retry,
    strip_before_thought_tags, load_memory_prompt,
    extract_memory_tags, extract_save_memory_tag,
    async_generate_memory_entry, async_update_core_memory,
    init_engine as _init_llm_engine,
)

def keep_alive():
    """
    定期检查监听列表, 确保所有在 user_names 中的用户都被持续监听. 
    如果发现有用户从监听列表中丢失, 则会尝试重新添加.
    这是一个守护线程, 用于增强程序的健壮性.
    """
    check_interval = 5  # 每30秒检查一次, 避免过于频繁
    logger.info(f"窗口保活/监听守护线程已启动, 每 {check_interval} 秒检查一次监听状态.")
    
    while True:
        try:
            # 获取当前所有正在监听的用户昵称集合
            current_listening_users = set(wx.listen.keys())
            
            # 获取应该被监听的用户昵称集合
            expected_users_to_listen = set(user_names)
            
            # 找出配置中应该监听但当前未在监听列表中的用户
            missing_users = expected_users_to_listen - current_listening_users
            
            if missing_users:
                logger.warning(f"检测到 {len(missing_users)} 个用户从监听列表中丢失: {', '.join(missing_users)}")
                for user in missing_users:
                    try:
                        logger.info(f"正在尝试重新添加用户 '{user}' 到监听列表...")
                        # 使用与程序启动时相同的回调函数 `message_listener` 重新添加监听
                        wx.AddListenChat(nickname=user, callback=message_listener)
                        logger.info(f"已成功将用户 '{user}' 重新添加回监听列表.")
                    except Exception as e:
                        logger.error(f"重新添加用户 '{user}' 到监听列表时失败: {e}", exc_info=True)
            else:
                # 使用 debug 级别, 因为正常情况下这条日志会频繁出现, 避免刷屏
                logger.debug(f"监听列表状态正常, 所有 {len(expected_users_to_listen)} 个目标用户都在监听中.")

        except Exception as e:
            # 捕获在检查过程中可能发生的任何意外错误, 使线程能继续运行
            logger.error(f"keep_alive 线程在检查监听列表时发生未知错误: {e}", exc_info=True)
            
        # 等待指定间隔后再进行下一次检查
        time.sleep(check_interval)
# ==================== 拍一拍功能区 开始 (最终验证版) ====================
# ==================== 拍一-拍功能区 ("最终解释"键盘模拟版) ====================

import uiautomation as uia
import pyautogui
import time
import logging

# 假设 wx, logger 等对象已在您的代码上下文中定义并初始化

# 定义一个我们程序中标准的UI自动化操作超时时间(秒)
DEFAULT_UI_AUTOMATION_TIMEOUT = 2.0 


# ===== UI 自动化（委托给 tools/ 模块） =====
# 原始函数被 threading.Thread(target=xxx) 调用，保持同步接口

def pat_pat_user_threaded(chat_name: str, target_user_name: str):
    """拍一拍用户 — 委托给 tools/pat_pat.py"""
    import asyncio
    from tools.pat_pat import PatPatTool
    tool = PatPatTool(wx=wx, ui_action_lock=ui_action_lock)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(tool.execute(
            target=target_user_name,
            chat_window=chat_name,
        ))
        loop.close()
        logger.info(f"拍一拍执行结果: {result}")
    except Exception as e:
        logger.error(f"拍一拍失败: {e}")

def pat_myself_threaded(chat_name: str):
    """拍一拍自己 — 委托给 tools/pat_pat.py"""
    import asyncio
    from tools.pat_pat import PatPatTool
    tool = PatPatTool(wx=wx, ui_action_lock=ui_action_lock)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(tool.execute(
            target="self",
            chat_window=chat_name,
        ))
        loop.close()
        logger.info(f"拍自己执行结果: {result}")
    except Exception as e:
        logger.error(f"拍自己失败: {e}")

def recall_message_threaded(chat_name: str, message_content: str):
    """撤回消息 — 委托给 tools/recall_message.py"""
    import asyncio
    from tools.recall_message import RecallMessageTool
    tool = RecallMessageTool(wx=wx, ui_action_lock=ui_action_lock)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(tool.execute(
            message_content=message_content,
            chat_window=chat_name,
        ))
        loop.close()
        logger.info(f"撤回消息执行结果: {result}")
    except Exception as e:
        logger.error(f"撤回消息失败: {e}")

def quote_message_threaded(chat_name: str, message_content: str, additional_text: str = "", message_type: str = None):
    """引用回复 — 委托给 tools/quote_reply.py"""
    import asyncio
    from tools.quote_reply import QuoteReplyTool
    tool = QuoteReplyTool(wx=wx, ui_action_lock=ui_action_lock, chat_contexts=chat_contexts)
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        result = loop.run_until_complete(tool.execute(
            chat_name=chat_name,
            message_content=message_content,
            additional_text=additional_text,
            message_type=message_type or "text",
        ))
        loop.close()
        logger.info(f"引用回复执行结果: {result}")
    except Exception as e:
        logger.error(f"引用回复失败: {e}")

# ===== 管理员命令（委托给 skills/admin/commands.py） =====
_admin_handler = None

def _get_admin_handler():
    """延迟初始化 AdminCommandHandler"""
    global _admin_handler
    if _admin_handler is None:
        from skills.admin.commands import AdminCommandHandler
        _admin_handler = AdminCommandHandler(
            wx=wx,
            chat_contexts=chat_contexts,
            queue_lock=queue_lock,
            prompt_mapping=prompt_mapping,
            save_chat_contexts_fn=save_chat_contexts,
            save_user_timers_fn=save_user_timers,
            save_recurring_reminders_fn=save_recurring_reminders,
            recurring_reminder_lock=recurring_reminder_lock,
            clean_up_temp_files_fn=clean_up_temp_files,
            active_summary_tasks=active_summary_tasks,
            active_summary_tasks_lock=active_summary_tasks_lock,
            generate_daily_summary_fn=generate_daily_summary,
            generate_core_memory_update_fn=generate_core_memory_update,
            get_user_error_message_fn=get_user_error_message,
            enable_remote_control_fn=enable_remote_control,
            disable_remote_control_fn=disable_remote_control,
            async_http_handler=async_http_handler,
            root_dir=root_dir,
        )
    return _admin_handler

def handle_admin_commands(command, user_id, sender):
    """旧接口 wrapper → AdminCommandHandler.dispatch()"""
    return _get_admin_handler().dispatch(command, user_id, sender)

def message_listener(msg, chat):
    global can_send_messages
        # --- START: 新增代码:处理消息撤回事件 ---
    who = chat.who
    sender = msg.sender
    original_content = msg.content
    
    # 检查是否是系统发出的, 关于消息撤回的提示
    # 根据日志, 这类消息的发送者(sender)是'system'
    if sender == 'system' and '撤回了一条消息' in original_content:
        # 检查是否是AI自己撤回的消息
        if '我撤回了一条消息' in original_content or original_content.startswith('你撤回了一条消息'):
            logger.info(f"检测到AI自己撤回消息的系统提示, 将记录到聊天上下文.内容: '{original_content}'")
            
            # 将AI自己的撤回动作记录到聊天上下文中
            with queue_lock:
                # 确保用户的聊天上下文存在
                if who not in chat_contexts:
                    chat_contexts[who] = {}
                    
                # 获取该用户的prompt名称
                prompt_name = prompt_mapping.get(who, who)
                if prompt_name not in chat_contexts[who]:
                    chat_contexts[who][prompt_name] = []
                
                # 添加AI的撤回动作到聊天上下文中(作为assistant的消息)
                action_message = f"[系统动作] {original_content}"
                chat_contexts[who][prompt_name].append({
                    "role": "assistant", 
                    "content": action_message
                })
                
                # 保持上下文长度限制
                context_limit = MAX_GROUPS * 2  # 用户消息+AI回复为一对
                if len(chat_contexts[who][prompt_name]) > context_limit:
                    chat_contexts[who][prompt_name] = chat_contexts[who][prompt_name][-context_limit:]
                
                # 保存上下文到文件
                save_chat_contexts()
                
            logger.info(f"已将AI自己的撤回动作记录到用户 '{who}' 的聊天上下文中")
            return
            
        # 用户撤回消息的处理(仅私聊)
        logger.info(f"检测到用户 '{who}' 撤回了一条消息.")
        
        # 构建一个特殊的内部指令, 用于触发AI进行特定回复
        recall_trigger_content = "[用户操作: 撤回了一条消息]"
        
        # 将这个特殊指令像普通消息一样放入处理队列
        with queue_lock:
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
            content_with_time = f"[{current_time_str}] {recall_trigger_content}"
            if who not in user_queues:
                user_queues[who] = {
                    'messages': [content_with_time],
                    'sender_name': who,
                    'username': who,
                    'last_message_time': time.time()
                }
            else:
                user_queues[who]['messages'].append(content_with_time)
                user_queues[who]['last_message_time'] = time.time()
            
            logger.info(f"已为用户 '{who}' 加入撤回消息触发指令到队列.")
        return  # 处理完毕, 结束本次函数执行, 避免后续代码处理这条系统消息
    # --- END: 新增代码 ---
    
    # a.k.a 原函数的其他部分从这里开始
    # who = chat.who # 这行可以删掉, 因为上面已经定义了
    msgtype = msg.type
    # original_content = msg.content # 这行也可以删掉
    # sender = msg.sender # 这行也可以删掉
    msgattr = msg.attr
    # ==================== 新增:拍一拍事件感知功能 开始 ====================
    # 检查是否是拍一拍相关的系统消息
    if msgattr == 'tickle':
        # 1. 处理机器人自己发起的动作 - 记录到聊天上下文但不触发API调用
        if '我拍了拍自己' in original_content or '我拍了拍' in original_content:
            logger.info(f"检测到机器人自己发起的拍一拍事件, 将记录到聊天上下文.内容: '{original_content}'")
            
            # 将AI自己的拍一拍动作记录到聊天上下文中
            with queue_lock:
                # 确保用户的聊天上下文存在
                if who not in chat_contexts:
                    chat_contexts[who] = {}
                    
                # 获取该用户的prompt名称
                prompt_name = prompt_mapping.get(who, who)
                if prompt_name not in chat_contexts[who]:
                    chat_contexts[who][prompt_name] = []
                
                # 添加AI的动作到聊天上下文中(作为assistant的消息)
                action_message = f"[系统动作] {original_content}"
                chat_contexts[who][prompt_name].append({
                    "role": "assistant", 
                    "content": action_message
                })
                
                # 保持上下文长度限制
                context_limit = MAX_GROUPS * 2  # 用户消息+AI回复为一对
                if len(chat_contexts[who][prompt_name]) > context_limit:
                    chat_contexts[who][prompt_name] = chat_contexts[who][prompt_name][-context_limit:]
                
                # 保存上下文到文件
                save_chat_contexts()
                
            logger.info(f"已将AI自己的拍一拍动作记录到用户 '{who}' 的聊天上下文中")
            return

        # 2. 处理用户拍一拍行为(仅私聊)
        # 如果通过了以上所有过滤, 说明是需要处理的拍一拍事件
        logger.info(f"✅ 成功检测到需要处理的拍一拍事件, 来自 '{who}', 内容: '{original_content}'")
        
        # 将这个动作转换为给AI的文本提示
        pat_trigger_content = f"[这是一个拍一拍的互动通知, 内容是:'{original_content}']"
        
        # 将消息放入队列, 让AI处理
        with queue_lock:
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
            content_with_time = f"[{current_time_str}] {pat_trigger_content}"
            if who not in user_queues:
                user_queues[who] = {'messages': [content_with_time], 'sender_name': who, 'username': who, 'last_message_time': time.time()}
            else:
                user_queues[who]['messages'].append(content_with_time)
                user_queues[who]['last_message_time'] = time.time()
        
        logger.info(f"已为用户 '{who}' 加入“拍一拍”触发指令到队列.")
        return # 处理完毕, 直接返回
        # ==================== 新增:过滤手打的“拍一拍”文本消息 开始 ====================
    if isinstance(original_content, str) and (original_content.strip().startswith('我拍了拍') or original_content.strip().startswith('你拍了拍')):
        logger.info(f"检测到手打的“拍一拍”格式文本消息, 已忽略.内容:'{original_content}'")
        return # 忽略这条消息, 不交给AI
    # ==================== 新增:过滤手打的“拍一拍”文本消息 结束 ====================

    # ==================== 新增:拍一拍事件感知功能 结束 ====================
    logger.info(f'收到来自聊天窗口 "{who}" 中用户 "{sender}" 的原始消息 (类型: {msgtype}, 属性: {msgattr}): {original_content[:100]}')
    who = chat.who 
    msgtype = msg.type
    original_content = msg.content
    sender = msg.sender
    msgattr = msg.attr
    logger.info(f'收到来自聊天窗口 "{who}" 中用户 "{sender}" 的原始消息 (类型: {msgtype}, 属性: {msgattr}): {str(original_content)[:100]}')

    if msgattr != 'friend': 
        logger.info(f"非好友消息, 已忽略.")
        return
    
    if msgtype == 'voice':
        voicetext = msg.to_text()
        original_content = (f"[语音消息]: {voicetext}")
    
    if msgtype == 'link':
        cardurl = msg.get_url()
        original_content = (f"[卡片链接]: {cardurl}")

    if msgtype == 'quote':
        # 引用消息处理
        quoted_msg = msg.quote_content
        if quoted_msg:
            original_content = f"[引用<{quoted_msg}>消息]: {msg.content}"
        else:
            original_content = msg.content
    
    if msgtype == 'merge':
        logger.info(f"收到合并转发消息, 开始处理")
        mergecontent = msg.get_messages()
        logger.info(f"收到合并转发消息, 处理完成")
        # mergecontent 是一个列表, 每个元素是 [发送者, 内容, 时间]
        # 转换为多行文本, 每行格式: [时间] 发送者: 内容
        if isinstance(mergecontent, list):
            merged_text_lines = []
            for item in mergecontent:
                if isinstance(item, list) and len(item) == 3:
                    sender, content, timestamp = item
                    # 修改这里的判断逻辑, 正确处理WindowsPath对象
                    # 检查是否为WindowsPath对象
                    if hasattr(content, 'suffix') and str(content.suffix).lower() in ('.png', '.jpg', '.jpeg', '.gif', '.bmp'):
                        # 是WindowsPath对象且是图片
                        if ENABLE_IMAGE_RECOGNITION:
                            try:
                                logger.info(f"开始识别图片: {str(content)}")
                                # 将WindowsPath对象转换为字符串
                                image_path = str(content)
                                # 保存当前状态
                                original_can_send_messages = can_send_messages
                                # 处理图片
                                content = recognize_image_with_moonshot(image_path, is_emoji=False)
                                if content:
                                    logger.info(f"图片识别成功: {content}")
                                    content = f"[图片识别结果]: {content}"
                                else:
                                    content = "[图片识别结果]: 无法识别图片内容"
                                # 确保状态恢复
                                can_send_messages = original_can_send_messages
                            except Exception as e:
                                content = "[图片识别失败]"
                                logger.error(f"图片识别失败: {e}")
                                # 确保状态恢复
                                can_send_messages = True
                        else:
                            content = "[图片]"
                    # 处理字符串路径的判断 (兼容性保留)
                    elif isinstance(content, str) and content.lower().endswith(('.png', '.jpg', '.jpeg', '.gif', 'bmp')):
                        if ENABLE_IMAGE_RECOGNITION:
                            try:
                                logger.info(f"开始识别图片: {content}")
                                # 保存当前状态
                                original_can_send_messages = can_send_messages
                                # 处理图片
                                image_content = recognize_image_with_moonshot(content, is_emoji=False)
                                if image_content:
                                    logger.info(f"图片识别成功: {image_content}")
                                    content = f"[图片识别结果]: {image_content}"
                                else:
                                    content = "[图片识别结果]: 无法识别图片内容"
                                # 确保状态恢复
                                can_send_messages = original_can_send_messages
                            except Exception as e:
                                content = "[图片识别失败]"
                                logger.error(f"图片识别失败: {e}")
                                # 确保状态恢复
                                can_send_messages = True
                        else:
                            content = "[图片]"
                    merged_text_lines.append(f"[{timestamp}] {sender}: {content}")
                else:
                    merged_text_lines.append(str(item))
            merged_text = "\n".join(merged_text_lines)
            original_content = f"[合并转发消息]:\n{merged_text}"
        else:
            original_content = f"[合并转发消息]: {mergecontent}"
    
    # 在处理完所有消息类型后检查内容是否为空
    if not original_content:
        logger.info("消息内容为空, 已忽略.")
        return
    
    # 确保后续处理的是字符串
    original_content = str(original_content)

    ##### 新增:拍一拍功能逻辑 开始 #####
    # 私聊逻辑: 精确匹配 "拍一拍我"
    if original_content == "拍一拍我":
        logger.info(f"在与 '{who}' 的私聊中检测到精确指令 '拍一拍我', 准备执行拍一拍.")
        # 在私聊中, 聊天对象(who)就是我们要拍的目标(who)
        pat_thread = threading.Thread(target=pat_pat_user_threaded, args=(who, who))
        pat_thread.start()
        return # 指令已处理, 直接返回, 不再进行后续AI回复

    ##### 新增:拍一拍功能逻辑 结束 #####

    # 消息处理逻辑(仅私聊)
    if who in user_names:
        should_process_this_message = True
        content_for_handler = original_content
        logger.info(f"收到来自监听列表用户 {who} 的个人私聊消息, 准备处理.")
        
        ##### 新增:管理命令处理逻辑 开始 #####
        # 检查是否为管理命令
        if original_content.startswith('/'):
            command_processed = handle_admin_commands(original_content, who, sender)
            if command_processed:
                return  # 命令已处理, 直接返回
        ##### 新增:管理命令处理逻辑 结束 #####
        
    else:
        logger.info(f"收到来自用户 {sender} (聊天窗口 {who}) 的消息, 但用户 {who} 不在监听列表, 已忽略.")
        should_process_this_message = False
    
    if should_process_this_message:
        msg.content = content_for_handler 
        logger.info(f'最终准备处理消息 from chat "{who}" by sender "{sender}": {str(msg.content)[:100]}')
        if msgtype == 'emotion':
            is_animation_emoji_in_original = True
        else:
            is_animation_emoji_in_original = False
        if is_animation_emoji_in_original and ENABLE_EMOJI_RECOGNITION:
            # 在这里把 sender 传递过去
            handle_emoji_message(msg, who, sender)
        else:
            handle_wxauto_message(msg, who, sender)


#  用下面这个函数, 完整替换你原来的 recognize_image_with_moonshot 函数
#  用下面这个函数, 完整替换你原来的 recognize_image_with_moonshot 函数
def recognize_image_with_moonshot(image_path, is_emoji=False):
    """
    使用AI识别图片内容并返回文本
    """
    global can_send_messages
    global is_recognizing_image  # ✅ 新增
    
    # 识图前暂停消息发送，并标记正在识图
    with can_send_messages_lock:
        can_send_messages = False
    with is_recognizing_image_lock:  # ✅ 新增
        is_recognizing_image = True
    
    try:
        # --- 核心识别逻辑 ---
        
        # 读取图片内容并压缩后编码（避免请求体过大导致中转站断连）
        try:
            from PIL import Image
            import io as _io
            _img = Image.open(image_path)
            # 如果是 RGBA/P 等模式，转成 RGB（JPEG 不支持透明通道）
            if _img.mode not in ('RGB', 'L'):
                _img = _img.convert('RGB')
            _img.thumbnail((1024, 1024))  # 最大边缩到 1024px
            _buf = _io.BytesIO()
            _buf_fmt = 'JPEG'
            _img.save(_buf, format=_buf_fmt, quality=85)
            image_content = base64.b64encode(_buf.getvalue()).decode('utf-8')
            logger.info(f"图片已压缩: 原始大小={os.path.getsize(image_path)}B, 压缩后={len(_buf.getvalue())}B")
        except ImportError:
            logger.warning("Pillow 未安装，使用原图发送（可能因体积过大失败）")
            with open(image_path, 'rb') as img_file:
                image_content = base64.b64encode(img_file.read()).decode('utf-8')
            
        headers = {
            'Authorization': f'Bearer {MOONSHOT_API_KEY}',
            'Content-Type': 'application/json'
        }
        text_prompt = getattr(__import__('config'), 'IMAGE_RECOGNITION_PROMPT', "请用中文描述这张图片的主要内容或主题，尽可能详细全面.不要使用'这是', '这张'等开头, 直接描述.如果有文字, 请包含在描述中.") if not is_emoji else getattr(__import__('config'), 'EMOJI_RECOGNITION_PROMPT', "请用中文简洁地描述这个聊天窗口最后一张表情包所表达的情绪, 含义或内容.如果表情包含文字, 请一并描述.注意:1. 只描述表情包本身, 不要添加其他内容 2. 不要出现'这是', '这个'等词语")
        data = {
            "model": MOONSHOT_MODEL,
            "messages": [
                {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_content}"}}, {"type": "text", "text": text_prompt}]}
            ],
            "temperature": MOONSHOT_TEMPERATURE
        }
        
        url = f"{MOONSHOT_BASE_URL}/chat/completions"
        
        response = requests.post(url, headers=headers, json=data, timeout=240)
        response.raise_for_status()
        
        result = response.json()
        recognized_text = result['choices'][0]['message']['content']
        
        if is_emoji:
            if "最后一张表情包" in recognized_text:
                recognized_text = recognized_text.split("最后一张表情包", 1)[1].strip()
            recognized_text = "发送了表情包:" + recognized_text
        else:
            recognized_text = "发送了图片:" + recognized_text
            
        logger.info(f"AI图片识别成功: {recognized_text}")
        return recognized_text

    except requests.exceptions.Timeout:
        logger.error(f"调用AI识别图片超时 (240秒): {image_path}")
        return "[图片识别超时]"

    except Exception as e:
        logger.error(f"调用AI识别图片失败: {str(e)}", exc_info=True)
        return "[图片识别失败]"
        
    finally:
        logger.info("图片识别流程结束.")
        
        # 识图完成后恢复消息发送，并取消识图标记
        with is_recognizing_image_lock:  # ✅ 新增
            is_recognizing_image = False
        with can_send_messages_lock:
            can_send_messages = True
        
        # 清理临时文件
        if is_emoji and os.path.exists(image_path):
            try:
                os.remove(image_path)
                logger.debug(f"已清理临时表情图片: {image_path}")
            except Exception as clean_err:
                logger.warning(f"清理临时表情图片失败: {clean_err}")

def handle_emoji_message(msg, who, sender): # <--- 增加了 sender 参数
    global emoji_timer
    global can_send_messages
    with can_send_messages_lock:
        can_send_messages = False
    def timer_callback():
        with emoji_timer_lock:
            # 【核心修正】在这里把 sender 传递下去
            handle_wxauto_message(msg, who, sender)
            global emoji_timer
            emoji_timer = None
            with can_send_messages_lock:
                can_send_messages = True
    with emoji_timer_lock:
        if emoji_timer is not None:
            emoji_timer.cancel()
        emoji_timer = threading.Timer(3.0, timer_callback)
        emoji_timer.start()

# ===== URL/文件工具（委托给 tools/url_fetch.py） =====
from tools.url_fetch import fetch_and_extract_text, safe_read_file, safe_write_file

def handle_wxauto_message(msg, who, sender):
    """
    处理来自Wxauto的消息, 包括可能的提醒, 图片/表情, 链接内容获取和常规聊天. 
    [新增 sender 参数]
    """
    global can_send_messages # 引用全局变量以控制发送状态
    global last_received_message_timestamp # 引用全局变量以更新活动时间
    try:
        last_received_message_timestamp = time.time()
        username = who
        # 获取原始消息内容
        original_content = getattr(msg, 'content', None) or getattr(msg, 'text', None)

        # 如果消息内容为空, 则直接返回
        if not original_content:
            logger.warning("收到的消息没有内容.")
            return

        # 重置该用户的自动消息计时器
        on_user_message(username)


        # --- 1. 提醒检查 (基于原始消息内容) ---
        reminder_keywords = ["提醒我", "定时"]
        if ENABLE_REMINDERS and any(keyword in original_content for keyword in reminder_keywords):
            logger.info(f"检测到可能的提醒请求, 用户 {username}: {original_content}")
            # 尝试解析并设置提醒
            reminder_set = try_parse_and_set_reminder(original_content, username)
            # 如果成功设置了提醒, 则处理完毕, 直接返回
            if reminder_set:
                logger.info(f"成功为用户 {username} 设置提醒, 消息处理结束.")
                return # 停止进一步处理此消息
        

        # --- 2. 图片/表情处理 (基于原始消息内容) ---
        img_path = None         # 图片路径
        is_emoji = False        # 是否为表情包
        # processed_content 初始化为原始消息, 后续步骤可能修改它
        processed_content = original_content

        # 检查是否为图片文件路径
        if msg.type in ('image'):
            if ENABLE_IMAGE_RECOGNITION:
                img_path = msg.download()
                is_emoji = False
                processed_content = None # 标记为None, 稍后会被识别结果替换
                logger.info(f"检测到图片消息, 准备识别: {img_path}")
            else:
                logger.info("检测到图片消息, 但图片识别功能已禁用.")

        # 处理文件消息
        if msg.type == 'file':
            try:
                file_path = msg.download()
                if file_path:
                    file_name = os.path.basename(str(file_path))
                    processed_content = f"[用户发来文件] 文件名: {file_name}, 保存路径: {str(file_path)}"
                    logger.info(f"收到文件消息, 已保存: {file_path}")
                else:
                    processed_content = "[用户发来一个文件，但下载失败]"
                    logger.warning("文件消息下载失败")
            except Exception as e:
                processed_content = f"[用户发来一个文件，但处理失败: {str(e)}]"
                logger.error(f"处理文件消息失败: {e}")

        # 检查是否为动画表情
        elif msg.type in ('emotion'):
            if ENABLE_EMOJI_RECOGNITION:
                img_path = msg.capture() # 截图
                is_emoji = True
                processed_content = None # 标记为None, 稍后会被识别结果替换
                logger.info("检测到动画表情, 准备截图识别...")
            else:
                clean_up_temp_files() # 清理可能的临时文件
                logger.info("检测到动画表情, 但表情识别功能已禁用.")

        # 如果需要进行图片/表情识别
        if img_path:
            logger.info(f"开始识别图片/表情 - 用户 {username}: {img_path}")
            # 调用识别函数
            recognized_text = recognize_image_with_moonshot(img_path, is_emoji=is_emoji)
            # 使用识别结果或回退占位符更新 processed_content
            processed_content = recognized_text if recognized_text else ("[图片]" if not is_emoji else "[动画表情]")
            clean_up_temp_files() # 清理临时截图文件
            can_send_messages = True # 确保识别后可以发送消息
            logger.info(f"图片/表情识别完成, 结果: {processed_content}")

        # --- 3. 链接内容获取 (仅当ENABLE_URL_FETCHING为True且当前非图片/表情处理流程时) ---
        fetched_web_content = None
        # 只有在启用了URL抓取, 并且当前处理的不是图片/表情(即processed_content不为None)时才进行
        if ENABLE_URL_FETCHING and processed_content is not None:
            # 使用正则表达式查找 URL
            url_pattern = r'https?://[^\s<>"]+|www\.[^\s<>"]+'
            urls_found = re.findall(url_pattern, original_content) # 仍在原始消息中查找URL

            if urls_found:
                # 优先处理第一个找到的有效链接
                url_to_fetch = urls_found[0]
                logger.info(f"检测到链接, 用户 {username}, 准备抓取: {url_to_fetch}")
                # 调用辅助函数抓取和提取文本
                fetched_web_content = fetch_and_extract_text(url_to_fetch)

                if fetched_web_content:
                    logger.info(f"成功获取链接内容摘要 (长度 {len(fetched_web_content)}).")
                    # 构建包含链接摘要的新消息内容, 用于发送给AI
                    # 注意:这里替换了 processed_content, AI将收到包含原始消息和链接摘要的组合信息
                    processed_content = f"用户发送了消息:\"{original_content}\"\n其中包含的链接的主要内容摘要如下(可能不完整):\n---\n{fetched_web_content}\n---\n"
                else:
                    logger.warning(f"未能从链接 {url_to_fetch} 提取有效文本内容.将按原始消息处理.")
                    # 如果抓取失败, processed_content 保持不变(可能是原始文本, 或图片/表情占位符)
            # else: (如果没找到URL) 不需要操作, 继续使用当前的 processed_content

        # --- 4. 记录用户消息到记忆 (如果启用) ---
        log_user_message_to_memory(username, processed_content)

        # --- 5. 将最终处理后的消息加入队列 ---
        # 只有在 processed_content 有效时才加入队列
        if processed_content:
            # 获取当前时间戳, 添加到消息内容前
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
            content_with_time = f"[{current_time_str}] {processed_content}" # 使用最终处理过的内容
            logger.info(f"准备将处理后的消息加入队列 - 用户 {username}: {content_with_time[:150]}...") # 日志截断防止过长

            # 【核心修改点】使用传递进来的 sender
            # 如果 sender 为空(例如主动消息), 则回退到使用 who
            sender_name_to_use = sender if sender else who

            # 使用锁保护对共享队列的访问
            with queue_lock:
                # 如果用户队列不存在, 则初始化
                if username not in user_queues:
                    user_queues[username] = {
                        'messages': [content_with_time],
                        'sender_name': sender_name_to_use,
                        'username': username,
                        'last_message_time': time.time()
                    }
                    logger.info(f"已为用户 {username} (发言人: {sender_name_to_use}) 初始化消息队列并加入消息.")
                else:
                    user_queues[username]['messages'].append(content_with_time)
                    user_queues[username]['last_message_time'] = time.time()
                    # 每次都更新发言人, 以响应最新的消息
                    user_queues[username]['sender_name'] = sender_name_to_use
                    logger.info(f"用户 {username} (发言人: {sender_name_to_use}) 的消息已加入队列(当前 {len(user_queues[username]['messages'])} 条)并更新时间.")
        else:
            logger.warning(f"在处理后未找到用户 {username} 的可处理内容.原始消息: '{original_content}'")

    except Exception as e:
        can_send_messages = True
        logger.error(f"消息处理失败 (handle_wxauto_message): {str(e)}", exc_info=True)

def check_inactive_users():
    global can_send_messages
    while True:
        current_time = time.time()
        inactive_users = []
        with queue_lock:
            for username, user_data in user_queues.items():
                last_time = user_data.get('last_message_time', 0)
                if current_time - last_time > QUEUE_WAITING_TIME and can_send_messages: 
                    inactive_users.append(username)

        for username in inactive_users:
            process_user_messages(username)

        time.sleep(1)  # 每秒检查一次

# 在 bot.py 文件中找到此函数并用下面的代码完整替换

def process_user_messages(user_id):
    """处理指定用户的消息队列, 包括可能的联网搜索. """
    global can_send_messages

    with queue_lock:
        if user_id not in user_queues:
            return
        user_data = user_queues.pop(user_id)
        messages = user_data['messages']
        sender_name = user_data['sender_name']
        username = user_data['username']

    merged_message = ' '.join(messages)
    logger.info(f"开始处理用户 '{sender_name}' (ID: {user_id}) 的合并消息: {merged_message[:100]}...")

    is_auto_message = "触发主动发消息:" in merged_message
    
    reply = None

    # [核心] 处理用户消息并生成回复
    # 联网搜索已通过 function calling 自动处理（AI 自主调用 web_search Tool）

    try:
        reply = get_deepseek_response(merged_message, user_id, store_context=True)

        if reply:
            cleaned_reply = QINGLI_AI_BIAOQIAN_ZHUJIE.sub('', reply).strip()
            
            if "</think>" in cleaned_reply:
                cleaned_reply = cleaned_reply.split("</think>", 1)[1].strip()

            # === 记忆标记检测与剥离 ===
            cleaned_reply, tag_type, tag_content = extract_memory_tags(cleaned_reply)

            if "## 记忆片段" not in cleaned_reply:
                send_reply(user_id, sender_name, username, merged_message, cleaned_reply)
                
                # 根据标记类型分派处理
                if tag_type == "save" and tag_content:
                    threading.Thread(
                        target=async_generate_memory_entry,
                        args=(user_id, tag_content, merged_message, cleaned_reply),
                        daemon=True
                    ).start()
                elif tag_type == "core" and tag_content:
                    threading.Thread(
                        target=async_update_core_memory,
                        args=(user_id, tag_content, merged_message, cleaned_reply),
                        daemon=True
                    ).start()
            else:
                logger.info(f"回复包含记忆片段标记, 已屏蔽发送给用户 {user_id}.")
        else:
            logger.error(f"未能为用户 {user_id} 生成任何回复.")

    except TimeoutError:
        logger.error(f"处理用户 {user_id} 消息时因API响应超时(超过240秒), 发送备用消息.")
        # 获取自定义超时错误消息或使用默认消息
        custom_timeout_msg = get_user_error_message(user_id, 'timeout_error')
        fallback_message = custom_timeout_msg if custom_timeout_msg else "抱歉, 我现在真的很忙, 稍后再聊吧."
        send_reply(user_id, sender_name, username, "[API响应超时]", fallback_message)
            
    except Exception as e:
        if is_auto_message:
            logger.error(f"主动消息处理失败 (用户: {user_id}): {str(e)}")
            logger.info(f"主动消息API调用失败, 已静默处理, 不发送错误提示给用户 {user_id}")
        else:
            logger.error(f"用户消息处理失败 (用户: {user_id}): {str(e)}")
            raise
            
def is_emoji_request(message: str) -> Optional[str]:
    """
    使用 AI 判断用户消息是否包含发送表情包的意图.
    如果AI回复中明确包含 [标签:xxx] 格式, 则优先提取标签.

    参数:
        message (str): AI 的回复消息.

    返回:
        Optional[str]: 如果需要发送表情, 返回表情的标签名;否则返回 None.
    """
    # 方案A: 优先使用精确的指令格式 [标签:xxx]
    # 增加了对中文冒号的支持
    match = re.search(r'\[标签[:：](.*?)\]', message)
    if match:
        tag = match.group(1).strip()
        # 增加长度限制, 防止AI生成过长的无效标签
        if 0 < len(tag) <= EMOJI_TAG_MAX_LENGTH: 
            logger.info(f"通过精确指令检测到表情包请求, 标签: '{tag}'")
            return tag
        else:
            logger.warning(f"提取到的表情标签 '{tag}' 长度超过限制 ({EMOJI_TAG_MAX_LENGTH}), 已忽略.")
            return None

    # 方案B: 如果没有精确指令, 使用 AI 进行意图判断 (作为备选)
    # 你可以根据需要决定是否启用这个备选方案
    # 如果你的 prompt 已经训练得很好, 总是会输出 [标签:xxx], 那么可以禁用这个, 节省API调用
    if not ENABLE_EMOJI_ASSISTANT_DETECTION:
        return None

    # 构建用于AI判断的提示词
    detection_prompt = f"""
    判断以下句子是否表达了要发送一个表情包的意图.
    句子: "{message}"

    如果表达了发送表情的意图, 请用一个最合适的词作为表情标签(例如: 开心, 悲伤, 害羞, 疑问), 并只返回这个标签词.
    如果没有表达发送表情的意图, 请只回答 "无".
    """
    try:
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL:
            response = get_assistant_response(detection_prompt, "emoji_detection")
        else:
            response = get_deepseek_response(detection_prompt, user_id="emoji_detection", store_context=False)

        # 清理并判断响应
        cleaned_response = response.strip()
        if cleaned_response and "无" not in cleaned_response and len(cleaned_response) <= EMOJI_TAG_MAX_LENGTH:
            logger.info(f"通过 AI 意图检测到表情包请求, 标签: '{cleaned_response}'")
            return cleaned_response
        else:
            return None
    except Exception as e:
        logger.error(f"表情包意图检测失败: {e}", exc_info=True)
        return None
            
def add_ai_action_timestamp(action_type: str):
    """
    记录AI执行特定动作的时间戳, 用于防刷屏.

    Args:
        action_type (str): 动作类型, 如 'pat_timestamps', 'recall_timestamps'.
    """
    global ai_action_timestamps
    with ai_action_lock:
        if action_type not in ai_action_timestamps:
            ai_action_timestamps[action_type] = []
        
        now = time.time()
        ai_action_timestamps[action_type].append(now)
        
        # 清理60秒前的旧时间戳
        sixty_seconds_ago = now - 60
        ai_action_timestamps[action_type] = [
            ts for ts in ai_action_timestamps[action_type] if ts > sixty_seconds_ago
        ]
        logger.debug(f"已记录动作 '{action_type}', 当前60秒内有 {len(ai_action_timestamps[action_type])} 次记录.")

def send_reply(user_id, sender_name, username, original_merged_message, reply):
    global is_sending_message, ignore_counter # 确保这些全局变量被正确引用
    
    if not reply:
        logger.warning(f"尝试向 {user_id} 发送空回复, 操作已取消.")
        return

    # --- [已读不回] 检测逻辑 --- (保持不变)
    reply_stripped = reply.strip()
    if ENABLE_IGNORE_DETECTION and reply_stripped == '[已读不回]':
        logger.info(f"检测到AI发送[已读不回]指令...")
        with ignore_counter_lock:
            ignore_counter[user_id] = ignore_counter.get(user_id, 0) + 1
            current_count = ignore_counter[user_id]
        logger.info(f"用户 {user_id} 连续[已读不回]次数: {current_count}")
        if current_count >= IGNORE_PAT_THRESHOLD:
            logger.info(f"用户 {user_id} 连续{IGNORE_PAT_THRESHOLD}次[已读不回], 触发拍一拍")
            with ignore_counter_lock:
                ignore_counter[user_id] = 0
            add_ai_action_timestamp('pat_timestamps')
            pat_thread = threading.Thread(target=pat_pat_user_threaded, args=(user_id, sender_name))
            pat_thread.start()
        return
    else:
        with ignore_counter_lock:
            if user_id in ignore_counter:
                ignore_counter[user_id] = 0

    # --- 【核心升级】使用线程锁替代简单的while循环 --- (保持不变)
    logger.debug(f"向 {user_id} 的发送任务正在尝试获取发送锁...")
    with can_send_messages_lock: # 确保 can_send_messages_lock 是可用的
        logger.debug(f"向 {user_id} 的发送任务已成功获取发送锁.")
        is_sending_message = True
        
        try:
            logger.info(f"准备向 {sender_name} (ID: {user_id}) 发送组合消息, 原始内容: {reply[:150]}")

            # --- 1. 准备阶段 --- (保持不变)
            emoji_path = None
            if ENABLE_EMOJI_SENDING:
                emotion = is_emoji_request(reply) # 确保 is_emoji_request 可用
                if emotion:
                    emoji_path = send_emoji(emotion) # 确保 send_emoji 可用

            reply = remove_timestamps(reply) # 确保 remove_timestamps 可用
            if REMOVE_PARENTHESES:
                reply = remove_parentheses_and_content(reply) # 确保 remove_parentheses_and_content 可用
            
            # 记录AI的回复到记忆日志 - 这部分逻辑会迁移到 reply_sender.py 中的文本发送处
            # 如果你原来的代码有这部分，现在可以注释掉或删除
            # if ENABLE_MEMORY:
            #     role_name = prompt_mapping.get(username, username)
            #     log_ai_reply_to_memory(username, role_name, reply)

            # --- 2. 指令解析与任务队列构建 --- (保持不变)
            final_send_queue = []
            # 确保 re, split_message_with_context 可用
            raw_parts = re.split(r'(\[\[撤回\][^\]]*\]|\[\[引用对方\][^\]]*\]|\[\[引用自己\][^\]]*\]|\[\[引用\][^\]]*\]|\[.*?\]|\*.*?\*|\\)', reply)
            
            for part in raw_parts:
                if not part.strip():
                    continue
                
                # 优先处理玩具
                if part.startswith('*') and part.endswith('*'):
                    final_send_queue.append({'type': 'toy_action', 'content': part})
                elif part == '\\':
                    continue  # 跳过，让split_message_with_context处理换行
                # 保持作者原有的精确匹配
                elif part.startswith('[[撤回]') and part.endswith(']'):
                    final_send_queue.append({'type': 'advanced_action', 'content': part}) # <--- 这里改成了 advanced_action
                elif part.startswith('[[引用对方]') and part.endswith(']'):
                    final_send_queue.append({'type': 'advanced_action', 'content': part}) # <--- 这里改成了 advanced_action
                elif part.startswith('[[引用自己]') and part.endswith(']'):
                    final_send_queue.append({'type': 'advanced_action', 'content': part}) # <--- 这里改成了 advanced_action
                elif part.startswith('[[引用]') and part.endswith(']'):
                    final_send_queue.append({'type': 'advanced_action', 'content': part}) # <--- 这里改成了 advanced_action
                elif re.match(r'\[.*?\]$', part):
                    final_send_queue.append({'type': 'action', 'content': part})
                else:
                    # 保留split_message_with_context调用
                    text_snippets = split_message_with_context(part) # 确保 split_message_with_context 可用
                    for snippet in text_snippets:
                        if snippet.strip():
                            final_send_queue.append({'type': 'text', 'content': snippet.strip()})
            
            if emoji_path:
                insert_pos = random.randint(0, len(final_send_queue))
                final_send_queue.insert(insert_pos, {'type': 'emoji', 'content': emoji_path})

            if not final_send_queue:
                logger.warning(f"处理后无可发送内容, 原始回复: {reply}")
                return

            # --- 3. 执行阶段 ---（替换这部分，使用新的打包方式）
            # 准备配置
            config_obj = SimpleNamespace(
                ENABLE_MEMORY=ENABLE_MEMORY, # 确保 ENABLE_MEMORY 是可用的全局变量
                AVERAGE_TYPING_SPEED=AVERAGE_TYPING_SPEED, # 确保 AVERAGE_TYPING_SPEED 是可用的全局变量
                RANDOM_TYPING_SPEED_MIN=RANDOM_TYPING_SPEED_MIN, # 确保 RANDOM_TYPING_SPEED_MIN 是可用的全局变量
                RANDOM_TYPING_SPEED_MAX=RANDOM_TYPING_SPEED_MAX, # 确保 RANDOM_TYPING_SPEED_MAX 是可用的全局变量
                prompt_mapping=prompt_mapping # 确保 prompt_mapping 是可用的全局变量
            )
            
            # 准备辅助函数
            helper_obj = SimpleNamespace(
                parse_and_execute=parse_and_execute, # 确保 parse_and_execute 可用
                pat_myself_threaded=pat_myself_threaded, # 确保 pat_myself_threaded 可用
                pat_pat_user_threaded=pat_pat_user_threaded, # 确保 pat_pat_user_threaded 可用
                quote_message_threaded=quote_message_threaded, # 确保 quote_message_threaded 可用
                recall_message_threaded=recall_message_threaded, # 确保 recall_message_threaded 可用
                add_ai_action_timestamp=add_ai_action_timestamp, # 确保 add_ai_action_timestamp 可用
                log_ai_reply_to_memory=log_ai_reply_to_memory # 确保 log_ai_reply_to_memory 可用
            )
            
            # 调用新的发送处理器
            reply_sender.send_message_queue(
                final_send_queue, user_id, sender_name, username,
                wx, ui_action_lock, logger, config_obj, helper_obj # 这里传递的是 wx, logger, ui_action_lock 的引用
            )

        except Exception as e:
            logger.error(f"向 {user_id} 发送回复失败: {str(e)}", exc_info=True)
        finally:
            is_sending_message = False

def split_message_with_context(text):
    """
    [V65-终极智能版] 将消息文本智能地分割为多个部分。
    """
    result_parts = []
    
    # 我们用一个更强大的正则表达式，一次性处理所有类型的分隔符！
    # 它会按照 $, 三个以上的\, \n, 或者单个的\ 来分割
    # re.split 会保留分隔符，我们需要在后面处理掉
    parts = re.split(r'(\$|\\{3,}|\n|\\)', text)
    
    for part in parts:
        part = part.strip()
        # 如果是分隔符本身，或者处理后是空字符串，就直接跳过
        if not part or part in ['$', '\\']:
            continue
        
        # 只有真正的文本，才会被加进最终的列表
        result_parts.append(part)
            
    return result_parts

def remove_timestamps(text):
    """
    移除文本中所有[YYYY-MM-DD (Weekday) HH:MM(:SS)]格式的时间戳
    支持四种格式:
    1. [YYYY-MM-DD Weekday HH:MM:SS] - 带星期和秒
    2. [YYYY-MM-DD Weekday HH:MM] - 带星期但没有秒
    3. [YYYY-MM-DD HH:MM:SS] - 带秒但没有星期
    4. [YYYY-MM-DD HH:MM] - 基本格式
    并自动清理因去除时间戳产生的多余空格
    """
    # 定义支持多种格式的时间戳正则模式
    timestamp_pattern = r'''
        \[                # 起始方括号
        \d{4}             # 年份:4位数字
        -(?:0[1-9]|1[0-2])  # 月份:01-12 (使用非捕获组)
        -(?:0[1-9]|[12]\d|3[01]) # 日期:01-31 (使用非捕获组)
        (?:\s[A-Za-z]+)?  # 可选的星期部分
        \s                # 日期与时间之间的空格
        (?:2[0-3]|[01]\d) # 小时:00-23
        :[0-5]\d          # 分钟:00-59
        (?::[0-5]\d)?     # 可选的秒数
        \]                # 匹配结束方括号  <--- 修正点
    '''
    # 替换时间戳为空格
    text_no_timestamps = re.sub(
        pattern = timestamp_pattern,
        repl = ' ',  # 统一替换为单个空格 (lambda m: ' ' 与 ' ' 等效)
        string = text,
        flags = re.X | re.M # re.X 等同于 re.VERBOSE
    )
    # 清理可能产生的连续空格, 将其合并为单个空格
    cleaned_text = re.sub(r'[^\S\r\n]+', ' ', text_no_timestamps)
    # 最后统一清理首尾空格
    return cleaned_text.strip()

def remove_parentheses_and_content(text: str) -> str:
    """
    去除文本中中文括号, 英文括号及其中的内容. 
    同时去除因移除括号而可能产生的多余空格(例如, 连续空格变单个, 每行首尾空格去除).
    不去除其它符号和换行符.
    """
    processed_text = re.sub(r"\(.*?\)|(.*?)", "", text, flags=re.DOTALL)
    processed_text = re.sub(r" {2,}", " ", processed_text)
    lines = processed_text.split('\n')
    stripped_lines = [line.strip(" ") for line in lines]
    processed_text = "\n".join(stripped_lines)
    return processed_text

# send_emoji 委托给 tools/send_emoji.py
def send_emoji(tag: str) -> Optional[str]:
    import asyncio
    from tools.send_emoji import SendEmojiTool
    tool = SendEmojiTool()
    try:
        loop = asyncio.new_event_loop()
        result = loop.run_until_complete(tool.execute(tag=tag, chat_window=""))
        loop.close()
        return result.get("file_path")
    except Exception as e:
        logger.error(f"发送表情包失败: {e}")
        return None

def send_error_reply(user_id, error_description_for_ai, fallback_message, error_context_log):
    """
    生成并发送符合人设的错误回复(仅私聊)
    Args:
        user_id (str): 目标用户ID. 
        error_description_for_ai (str): 给AI的提示, 描述错误情况, 要求其生成用户回复.
        fallback_message (str): 如果AI生成失败, 使用的备用消息.
        error_context_log (str): 用于日志记录的错误上下文描述.
    """
    logger.warning(f"准备为用户 {user_id} 发送错误提示: {error_context_log}")
    try:
        # 调用AI生成符合人设的错误消息
        ai_error_reply = get_deepseek_response(error_description_for_ai, user_id=user_id, store_context=True)
        logger.info(f"AI生成的错误回复: {ai_error_reply[:100]}...")
        send_reply(user_id, user_id, user_id, f"[错误处理: {error_context_log}]", ai_error_reply)
    except Exception as ai_err:
        logger.error(f"调用AI生成错误回复失败 ({error_context_log}): {ai_err}. 使用备用消息.")
        try:
            send_reply(user_id, user_id, user_id, f"[错误处理备用: {error_context_log}]", fallback_message)
        except Exception as send_fallback_err:
            # 如果连send_reply都失败了, 记录严重错误
            logger.critical(f"发送备用错误消息也失败 ({error_context_log}): {send_fallback_err}")

def try_parse_and_set_reminder(message_content, user_id):
    """
    尝试解析消息内容, 区分短期一次性, 长期一次性, 重复提醒. 
    使用 AI 进行分类和信息提取, 然后设置短期定时器或保存到文件.
    如果成功设置了任一类型的提醒, 返回 True, 否则返回 False.
    """
    global next_timer_id # 引用全局变量, 用于生成短期一次性提醒的ID
    logger.debug(f"尝试为用户 {user_id} 解析提醒请求 (需要识别类型和时长): '{message_content}'")

    try:
        # --- 1. 获取当前时间, 准备给 AI 的上下文信息 ---
        now = dt.datetime.now()
        # AI 需要知道当前完整日期时间来计算目标时间
        current_datetime_str_for_ai = now.strftime("%Y-%m-%d %A %H:%M:%S")
        logger.debug(f"当前时间: {current_datetime_str_for_ai} (用于AI分析)")

        # --- 2. 构建新的 AI 提示, 要求 AI 分类并提取信息 ---
        # --- 更新: 增加短期/长期一次性提醒的区分 ---
        parsing_prompt = f"""
请分析用户的提醒或定时请求.
当前时间是: {current_datetime_str_for_ai}.
用户的请求是: "{message_content}"

请判断这个请求属于以下哪种类型, 并计算相关时间:
A) **重复性每日提醒**:例如 "每天早上8点叫我起床", "提醒我每天晚上10点睡觉".
B) **一次性提醒 (延迟 > 10分钟 / 600秒)**:例如 "1小时后提醒我", "今天下午3点开会", "明天早上叫我".
C) **一次性提醒 (延迟 <= 10分钟 / 600秒)**:例如 "5分钟后提醒我", "提醒我600秒后喝水".
D) **非提醒请求**:例如 "今天天气怎么样?", "取消提醒".

根据判断结果, 请严格按照以下格式输出:
- 如果是 A (重复每日提醒): 返回 JSON 对象 `{{"type": "recurring", "time_str": "HH:MM", "message": "提醒的具体内容"}}`. `time_str` 必须是 24 小时制的 HH:MM 格式.
- 如果是 B (长期一次性提醒): 返回 JSON 对象 `{{"type": "one-off-long", "target_datetime_str": "YYYY-MM-DD HH:MM", "message": "提醒的具体内容"}}`. `target_datetime_str` 必须是计算出的未来目标时间的 YYYY-MM-DD HH:MM 格式.
- 如果是 C (短期一次性提醒): 返回 JSON 对象 `{{"type": "one-off-short", "delay_seconds": number, "message": "提醒的具体内容"}}`. `delay_seconds` 必须是从现在开始计算的, 小于等于 600 的正整数总秒数.
- 如果是 D (非提醒): 请直接返回字面单词 `null`.

请看以下例子 (假设当前时间是 2024-05-29 星期三 10:00:00):
1. "每天早上8点叫我起床" -> `{{"type": "recurring", "time_str": "08:00", "message": "叫我起床"}}`
2. "提醒我30分钟后喝水" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-29 10:30", "message": "喝水"}}` (超过10分钟)
3. "下午2点提醒我开会" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-29 14:00", "message": "开会"}}`
4. "明天早上7点叫我起床" -> `{{"type": "one-off-long", "target_datetime_str": "2024-05-30 07:00", "message": "叫我起床"}}`
5. "提醒我5分钟后站起来活动" -> `{{"type": "one-off-short", "delay_seconds": 300, "message": "站起来活动"}}` (小于等于10分钟)
6. "10分钟后叫我" -> `{{"type": "one-off-short", "delay_seconds": 600, "message": "叫我"}}` (等于10分钟)
7. "今天怎么样?" -> `null`

请务必严格遵守输出格式, 只返回指定的 JSON 对象或 `null`, 不要添加任何解释性文字.
"""
        # --- 3. 调用 AI 进行解析和分类 ---
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"向辅助模型发送提醒解析请求(区分时长), 用户: {user_id}, 内容: '{message_content}'")
            ai_raw_response = get_assistant_response(parsing_prompt, "reminder_parser_classifier_v2_" + user_id)
            logger.debug(f"辅助模型提醒解析原始响应 (分类器 v2): {ai_raw_response}")
        else:
            logger.info(f"向主模型发送提醒解析请求(区分时长), 用户: {user_id}, 内容: '{message_content}'")
            ai_raw_response = get_deepseek_response(parsing_prompt, user_id="reminder_parser_classifier_v2_" + user_id, store_context=False)
            logger.debug(f"主模型提醒解析原始响应 (分类器 v2): {ai_raw_response}")

        # 使用新的清理函数处理AI的原始响应
        cleaned_ai_output_str = extract_last_json_or_null(ai_raw_response)
        logger.debug(f"AI响应清理并提取后内容: '{cleaned_ai_output_str}'")
        response = cleaned_ai_output_str

        # --- 4. 解析 AI 的响应 ---
        # 修改判断条件, 使用清理后的结果
        if cleaned_ai_output_str is None or cleaned_ai_output_str == "null": # "null" 是AI明确表示非提醒的方式
            logger.info(f"AI 未在用户 '{user_id}' 的消息中检测到有效的提醒请求 (清理后结果为 None 或 'null').原始AI响应: '{ai_raw_response}'")
            return False
        
        try:
            if not response:
                logger.error(f"提醒解析逻辑中出现空响应, 用户: {user_id}")
                return False
            response_cleaned = re.sub(r"```json\n?|\n?```", "", response).strip()
            reminder_data = json.loads(response_cleaned)
            logger.debug(f"解析后的JSON数据 (分类器 v2): {reminder_data}")

            reminder_type = reminder_data.get("type")
            reminder_msg = str(reminder_data.get("message", "")).strip()

            # --- 5. 验证共享数据(提醒内容不能为空)---
            if not reminder_msg:
                logger.warning(f"从AI解析得到的提醒消息为空.用户: {user_id}, 数据: {reminder_data}")
                error_prompt = f"用户尝试设置提醒, 但似乎没有说明要提醒的具体内容(用户的原始请求可能是 '{message_content}').请用你的语气向用户解释需要提供提醒内容, 并鼓励他们再说一次."
                fallback = "嗯... 光设置时间还不行哦, 得告诉我你要我提醒你做什么事呀？"
                send_error_reply(user_id, error_prompt, fallback, "提醒内容为空")
                return False

            # --- 6. 根据 AI 判断的类型分别处理 ---

            # --- 6a. 短期一次性提醒 (<= 10分钟) ---
            if reminder_type == "one-off-short":
                try:
                    delay_seconds = int(reminder_data['delay_seconds'])
                    if not (0 < delay_seconds <= 600): # 验证延迟在 (0, 600] 秒之间
                         logger.warning(f"AI 返回的 'one-off-short' 延迟时间无效: {delay_seconds} 秒 (应 > 0 且 <= 600).用户: {user_id}, 数据: {reminder_data}")
                         error_prompt = f"用户想设置一个短期提醒(原始请求 '{message_content}'), 但我计算出的时间 ({delay_seconds}秒) 不在10分钟内或已过去.请用你的语气告诉用户这个时间有点问题, 建议他们检查一下或换个说法."
                         fallback = "哎呀, 这个短期提醒的时间好像有点不对劲(要么超过10分钟, 要么已经过去了), 能麻烦你再说一次吗？"
                         send_error_reply(user_id, error_prompt, fallback, "短期延迟时间无效")
                         return False
                except (KeyError, ValueError, TypeError) as val_e:
                     logger.error(f"解析AI返回的 'one-off-short' 提醒数据失败.用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                     error_prompt = f"用户想设置短期提醒(原始请求 '{message_content}'), 但我没理解好时间({type(val_e).__name__}).请用你的语气抱歉地告诉用户没听懂, 并请他们换种方式说, 比如'5分钟后提醒我...'"
                     fallback = "抱歉呀, 我好像没太明白你的时间意思, 设置短期提醒失败了.能麻烦你换种方式再说一遍吗？比如 '5分钟后提醒我...'"
                     send_error_reply(user_id, error_prompt, fallback, f"One-off-short数据解析失败 ({type(val_e).__name__})")
                     return False

                # 设置 threading.Timer 定时器
                target_dt = now + dt.timedelta(seconds=delay_seconds)
                confirmation_time_str = target_dt.strftime('%Y-%m-%d %H:%M:%S')
                delay_str_approx = format_delay_approx(delay_seconds, target_dt)

                logger.info(f"准备为用户 {user_id} 设置【短期一次性】提醒 (<=10min), 计划触发时间: {confirmation_time_str} (延迟 {delay_seconds:.2f} 秒), 内容: '{reminder_msg}'")

                with timer_lock:
                    timer_id = next_timer_id
                    next_timer_id += 1
                    timer_key = (user_id, timer_id)
                    timer = Timer(float(delay_seconds), trigger_reminder, args=[user_id, timer_id, reminder_msg])
                    active_timers[timer_key] = timer
                    timer.start()
                    logger.info(f"【短期一次性】提醒定时器 (ID: {timer_id}) 已为用户 {user_id} 成功启动.")

                log_original_message_to_memory(user_id, message_content) # 记录原始请求

                confirmation_prompt = f"""用户刚才的请求是:"{message_content}".
根据这个请求, 你已经成功将一个【短期一次性】提醒(10分钟内)安排在 {confirmation_time_str} (也就是 {delay_str_approx}) 触发.
提醒的核心内容是:'{reminder_msg}'.
请你用自然, 友好的语气回复用户, 告诉他这个【短期】提醒已经设置好了, 确认时间和提醒内容."""
                send_confirmation_reply(user_id, confirmation_prompt, f"[短期一次性提醒已设置: {reminder_msg}]", f"收到！【短期提醒】设置好啦, 我会在 {delay_str_approx} ({target_dt.strftime('%H:%M')}) 提醒你:{reminder_msg}")
                return True

            # --- 6b. 长期一次性提醒 (> 10分钟) ---
            elif reminder_type == "one-off-long":
                try:
                    target_datetime_str = reminder_data['target_datetime_str']
                    # 在本地再次验证时间格式是否为 YYYY-MM-DD HH:MM
                    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
                    # 验证时间是否在未来
                    if target_dt <= now:
                        logger.warning(f"AI 返回的 'one-off-long' 目标时间无效: {target_datetime_str} (已过去或就是现在).用户: {user_id}, 数据: {reminder_data}")
                        error_prompt = f"用户想设置一个提醒(原始请求 '{message_content}'), 但我计算出的目标时间 ({target_datetime_str}) 好像是过去或就是现在了.请用你的语气告诉用户这个时间点无法设置, 建议他们指定一个未来的时间."
                        fallback = "哎呀, 这个时间点 ({target_dt.strftime('%m月%d日 %H:%M')}) 好像已经过去了或就是现在啦, 没办法设置过去的提醒哦.要不试试说一个未来的时间？"
                        send_error_reply(user_id, error_prompt, fallback, "长期目标时间无效")
                        return False
                except (KeyError, ValueError, TypeError) as val_e:
                    logger.error(f"解析AI返回的 'one-off-long' 提醒数据失败.用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                    error_prompt = f"用户想设置一个较远时间的提醒(原始请求 '{message_content}'), 但我没理解好目标时间 ({type(val_e).__name__}).请用你的语气抱歉地告诉用户没听懂, 并请他们用明确的日期和时间再说, 比如'明天下午3点'或'2024-06-15 10:00'."
                    fallback = "抱歉呀, 我好像没太明白你说的那个未来的时间点, 设置提醒失败了.能麻烦你说得更清楚一点吗？比如 '明天下午3点' 或者 '6月15号上午10点' 这样."
                    send_error_reply(user_id, error_prompt, fallback, f"One-off-long数据解析失败 ({type(val_e).__name__})")
                    return False

                logger.info(f"准备为用户 {user_id} 添加【长期一次性】提醒 (>10min), 目标时间: {target_datetime_str}, 内容: '{reminder_msg}'")

                # 创建要存储的提醒信息字典 (包含类型)
                new_reminder = {
                    "reminder_type": "one-off", # 在存储时统一用 'one-off'
                    "user_id": user_id,
                    "target_datetime_str": target_datetime_str, # 存储目标时间
                    "content": reminder_msg
                }

                # 添加到内存列表并保存到文件
                with recurring_reminder_lock:
                    recurring_reminders.append(new_reminder)
                    save_recurring_reminders() # 保存更新后的列表

                logger.info(f"【长期一次性】提醒已添加并保存到文件.用户: {user_id}, 时间: {target_datetime_str}, 内容: '{reminder_msg}'")

                log_original_message_to_memory(user_id, message_content)

                # 发送确认消息
                confirmation_prompt = f"""用户刚才的请求是:"{message_content}".
根据这个请求, 你已经成功为他设置了一个【一次性】提醒.
这个提醒将在【指定时间】 {target_datetime_str} 触发.
提醒的核心内容是:'{reminder_msg}'.
请你用自然, 友好的语气回复用户, 告诉他这个【一次性】提醒已经设置好了, 确认好具体的日期时间和提醒内容."""
                # 使用格式化后的时间发送给用户
                friendly_time = target_dt.strftime('%Y年%m月%d日 %H:%M')
                send_confirmation_reply(user_id, confirmation_prompt, f"[长期一次性提醒已设置: {reminder_msg}]", f"好嘞！【一次性提醒】设置好啦, 我会在 {friendly_time} 提醒你:{reminder_msg}")
                return True

            # --- 6c. 重复性每日提醒 ---
            elif reminder_type == "recurring":
                try:
                    time_str = reminder_data['time_str']
                    datetime.strptime(time_str, '%H:%M') # 验证 HH:MM 格式
                except (KeyError, ValueError, TypeError) as val_e:
                    logger.error(f"解析AI返回的 'recurring' 提醒数据失败.用户: {user_id}, 数据: {reminder_data}, 错误: {val_e}")
                    error_prompt = f"用户想设置每日提醒(原始请求 '{message_content}'), 但我没理解好时间 ({type(val_e).__name__}).请用你的语气抱歉地告诉用户没听懂, 并请他们用明确的'每天几点几分'格式再说, 比如'每天早上8点'或'每天22:30'."
                    fallback = "抱歉呀, 我好像没太明白你说的每日提醒时间, 设置失败了.能麻烦你说清楚是'每天几点几分'吗？比如 '每天早上8点' 或者 '每天22:30' 这样."
                    send_error_reply(user_id, error_prompt, fallback, f"Recurring数据解析失败 ({type(val_e).__name__})")
                    return False

                logger.info(f"准备为用户 {user_id} 添加【每日重复】提醒, 时间: {time_str}, 内容: '{reminder_msg}'")

                # 创建要存储的提醒信息字典 (包含类型)
                new_reminder = {
                    "reminder_type": "recurring", # 明确类型
                    "user_id": user_id,
                    "time_str": time_str, # 存储 HH:MM
                    "content": reminder_msg
                }

                # 添加到内存列表并保存到文件
                with recurring_reminder_lock:
                    # 检查是否已存在完全相同的重复提醒
                    exists = any(
                        r.get('reminder_type') == 'recurring' and
                        r.get('user_id') == user_id and
                        r.get('time_str') == time_str and
                        r.get('content') == reminder_msg
                        for r in recurring_reminders
                    )
                    if not exists:
                        recurring_reminders.append(new_reminder)
                        save_recurring_reminders()
                        logger.info(f"【每日重复】提醒已添加并保存.用户: {user_id}, 时间: {time_str}, 内容: '{reminder_msg}'")
                    else:
                        logger.info(f"相同的【每日重复】提醒已存在, 未重复添加.用户: {user_id}, 时间: {time_str}")
                        # 可以选择告知用户提醒已存在
                        # send_reply(user_id, user_id, user_id, "[重复提醒已存在]", f"嗯嗯, 这个 '{reminder_msg}' 的每日 {time_str} 提醒我已经记下啦, 不用重复设置哦.")
                        # return True # 即使未添加, 也认为设置意图已满足

                log_original_message_to_memory(user_id, message_content)

                # 向用户发送确认消息
                confirmation_prompt = f"""用户刚才的请求是:"{message_content}".
根据这个请求, 你已经成功为他设置了一个【每日重复】提醒.
这个提醒将在【每天】的 {time_str} 触发.
提醒的核心内容是:'{reminder_msg}'.
请你用自然, 友好的语气回复用户, 告诉他【每日】提醒已经设置好了, 确认时间和提醒内容.强调这是每天都会提醒的."""
                send_confirmation_reply(user_id, confirmation_prompt, f"[每日提醒已设置: {reminder_msg}]", f"好嘞！【每日提醒】设置好啦, 以后我【每天】 {time_str} 都会提醒你:{reminder_msg}")
                return True

            # --- 6d. 未知类型 ---
            else:
                 logger.error(f"AI 返回了未知的提醒类型: '{reminder_type}'.用户: {user_id}, 数据: {reminder_data}")
                 error_prompt = f"用户想设置提醒(原始请求 '{message_content}'), 但我有点糊涂了, 没搞清楚时间或者类型.请用你的语气抱歉地告诉用户, 请他们说得更清楚一点, 比如是几分钟后, 明天几点, 还是每天提醒."
                 fallback = "哎呀, 我有点没搞懂你的提醒要求, 是几分钟后提醒, 还是指定某个时间点, 或者是每天都提醒呀？麻烦说清楚点我才能帮你设置哦."
                 send_error_reply(user_id, error_prompt, fallback, f"未知提醒类型 '{reminder_type}'")
                 return False

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as json_e:
            # 处理 JSON 解析本身或后续访问键值对的错误
            response_cleaned_str = response_cleaned if 'response_cleaned' in locals() else 'N/A'
            logger.error(f"解析AI返回的提醒JSON失败 (分类器 v2).用户: {user_id}, 原始响应: '{response}', 清理后: '{response_cleaned_str}', 错误: {json_e}")
            error_prompt = f"用户想设置提醒(原始请求可能是 '{message_content}'), 但我好像没完全理解时间或者内容, 解析的时候出错了 ({type(json_e).__name__}).请用你的语气抱歉地告诉用户没听懂, 并请他们换种方式说, 比如'30分钟后提醒我...'或'每天下午3点叫我...'."
            fallback = "抱歉呀, 我好像没太明白你的意思, 设置提醒失败了.能麻烦你换种方式再说一遍吗？比如 '30分钟后提醒我...' 或者 '每天下午3点叫我...' 这种."
            send_error_reply(user_id, error_prompt, fallback, f"JSON解析失败 ({type(json_e).__name__})")
            return False

    except Exception as e:
        logger.error(f"处理提醒请求时发生未预料的错误: {str(e)}", exc_info=True)
        error_prompt = f"在处理用户设置提醒的请求时, 发生了一个我没预料到的内部错误.请用你的语气向用户表达歉意."
        fallback = "哎呀, 好像内部出了点小问题, 暂时没法帮你设置提醒了, 非常抱歉！"
        send_error_reply(user_id, error_prompt, fallback, f"通用处理错误 ({type(e).__name__})")
        return False
    return False # Make sure all paths return something

def extract_last_json_or_null(ai_response_text: str) -> Optional[str]:
    """
    从AI的原始响应文本中清理并提取最后一个有效的JSON对象字符串或字面量 "null".

    Args:
        ai_response_text: AI返回的原始文本.

    Returns:
        如果找到有效的JSON对象, 则返回其字符串形式.
        如果AI明确返回 "null" (清理后), 则返回字符串 "null".
        如果没有找到有效的JSON或 "null", 则返回 None.
    """
    if ai_response_text is None:
        return None

    # 步骤 1: 移除常见的Markdown代码块标记, 并去除首尾空格
    # 这个正则表达式会移除 ```json\n, ```json, \n```, ```
    processed_text = re.sub(r"```json\n?|\n?```", "", ai_response_text).strip()

    # 步骤 2: 检查清理后的文本是否完全是 "null" (不区分大小写)
    # 这是AI指示非提醒请求的明确信号
    if processed_text.lower() == 'null':
        return "null" # 返回字面量字符串 "null"

    # 步骤 3: 查找所有看起来像JSON对象的子字符串
    # re.DOTALL 使得 '.' 可以匹配换行符
    # 这个正则表达式会找到所有以 '{' 开头并以 '}' 结尾的非重叠子串
    json_candidates = re.findall(r'\{.*?\}', processed_text, re.DOTALL)

    if not json_candidates:
        # 没有找到任何类似JSON的结构, 并且它也不是 "null"
        return None

    # 步骤 4: 从后往前尝试解析每个候选JSON字符串
    for candidate_str in reversed(json_candidates):
        try:
            # 尝试解析以验证它是否是有效的JSON
            json.loads(candidate_str)
            # 如果成功解析, 说明这是最后一个有效的JSON对象字符串
            return candidate_str
        except json.JSONDecodeError:
            # 解析失败, 继续尝试前一个候选者
            continue

    # 如果所有候选者都解析失败
    return None

def format_delay_approx(delay_seconds, target_dt):
    """将延迟秒数格式化为用户友好的大致时间描述. """
    if delay_seconds < 60:
        # 少于1分钟, 显示秒
        return f"大约 {int(delay_seconds)} 秒后"
    elif delay_seconds < 3600:
        # 少于1小时, 显示分钟
        return f"大约 {int(delay_seconds / 60)} 分钟后"
    elif delay_seconds < 86400:
        # 少于1天, 显示小时和分钟
        hours = int(delay_seconds / 3600)
        minutes = int((delay_seconds % 3600) / 60)
        # 如果分钟数为0, 则只显示小时
        return f"大约 {hours} 小时" + (f" {minutes} 分钟后" if minutes > 0 else "后")
    else:
        # 超过1天, 显示天数和目标日期时间
        days = int(delay_seconds / 86400)
        # 使用中文日期时间格式
        return f"大约 {days} 天后 ({target_dt.strftime('%Y年%m月%d日 %H:%M')}左右)"

def log_original_message_to_memory(user_id, message_content):
    """将设置提醒的原始用户消息记录到记忆日志文件(如果启用了记忆功能). """
    if ENABLE_MEMORY: # 检查是否启用了记忆功能
        try:
            # 获取用户对应的 prompt 文件名(或用户昵称)
            prompt_name = prompt_mapping.get(user_id, user_id)
            # 构建日志文件路径
            log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
            # 准备日志条目, 记录原始用户消息
            log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{user_id}] {message_content}\n"
            # 确保目录存在
            os.makedirs(os.path.dirname(log_file), exist_ok=True)

            # 以追加模式写入日志条目
            with open(log_file, 'a', encoding='utf-8') as f:
                f.write(log_entry)
        except Exception as write_err:
            logger.error(f"写入用户 {user_id} 的提醒设置记忆日志失败: {write_err}")

def send_confirmation_reply(user_id, confirmation_prompt, log_context, fallback_message):
    """使用 AI 生成并发送提醒设置成功的确认消息, 包含备用消息逻辑. """
    logger.debug(f"准备发送给 AI 用于生成确认消息的提示词(部分): {confirmation_prompt[:250]}...")
    try:
        # 调用 AI 生成确认回复, 存储上下文
        confirmation_msg = get_deepseek_response(confirmation_prompt, user_id=user_id, store_context=True)
        logger.info(f"已为用户 {user_id} 生成提醒确认消息: {confirmation_msg[:100]}...")
        # 使用 send_reply 发送 AI 生成的确认消息
        send_reply(user_id, user_id, user_id, log_context, confirmation_msg)
        logger.info(f"已通过 send_reply 向用户 {user_id} 发送提醒确认消息.")
    except Exception as api_err:
        # 如果 AI 调用失败
        logger.error(f"调用API为用户 {user_id} 生成提醒确认消息失败: {api_err}. 将使用备用消息.")
        try:
             # 尝试使用 send_reply 发送预设的备用确认消息
             send_reply(user_id, user_id, user_id, f"{log_context} [备用确认]", fallback_message)
        except Exception as send_fallback_err:
             # 如果连发送备用消息都失败了, 记录严重错误
             logger.critical(f"发送备用确认消息也失败 ({log_context}): {send_fallback_err}")
    
def trigger_reminder(user_id, timer_id, reminder_message):
    """当短期提醒到期时由 threading.Timer 调用的函数. """
    global is_sending_message

    timer_key = (user_id, timer_id)
    logger.info(f"触发【短期】提醒 (ID: {timer_id}), 用户 {user_id}, 内容: {reminder_message}")

    # 从活动计时器列表中移除 (短期提醒)
    with timer_lock:
        if timer_key in active_timers:
            del active_timers[timer_key]
        else:
             logger.warning(f"触发时未在 active_timers 中找到短期计时器键 {timer_key}.")

    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
        logger.info(f"当前为安静时间:抑制【短期】提醒 (ID: {timer_id}), 用户 {user_id}.")
        return

    try:
        # 创建提醒前缀, 让AI知道这是一个提醒触发
        reminder_prefix = f"提醒触发:{reminder_message}"
        
        # 将提醒消息添加到用户的消息队列, 而不是直接调用API
        current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M:%S")
        formatted_message = f"[{current_time_str}] {reminder_prefix}"
        
        with queue_lock:
            if user_id not in user_queues:
                user_queues[user_id] = {
                    'messages': [formatted_message],
                    'sender_name': user_id,
                    'username': user_id,
                    'last_message_time': time.time()
                }
            else:
                user_queues[user_id]['messages'].append(formatted_message)
                user_queues[user_id]['last_message_time'] = time.time()
        
        logger.info(f"已将提醒消息 '{reminder_message}' 添加到用户 {user_id} 的消息队列, 用以执行联网检查流程")

        # 可选:如果仍需语音通话功能, 保留这部分
        if USE_VOICE_CALL_FOR_REMINDERS:
            try:
                wx.VoiceCall(user_id)
                logger.info(f"通过语音通话提醒用户 {user_id} (短期提醒).")
            except Exception as voice_err:
                logger.error(f"语音通话提醒失败 (短期提醒), 用户 {user_id}: {voice_err}")

    except Exception as e:
        logger.error(f"处理【短期】提醒失败 (ID: {timer_id}), 用户 {user_id}: {str(e)}", exc_info=True)
        # 即使出错, 也不再使用原来的直接发送备用消息方法
        # 而是尽可能添加到队列
        try:
            fallback_msg = f"[{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')}] 提醒时间到:{reminder_message}"
            with queue_lock:
                if user_id in user_queues:
                    user_queues[user_id]['messages'].append(fallback_msg)
                    user_queues[user_id]['last_message_time'] = time.time()
                else:
                    user_queues[user_id] = {
                        'messages': [fallback_msg],
                        'sender_name': user_id,
                        'username': user_id,
                        'last_message_time': time.time()
                    }
            logger.info(f"已将备用提醒消息添加到用户 {user_id} 的消息队列")
        except Exception as fallback_e:
            logger.error(f"添加提醒备用消息到队列失败, 用户 {user_id}: {fallback_e}")


def log_ai_reply_to_memory(username, role_name, message):
    if not ENABLE_MEMORY:
        return
    log_file_path = get_memory_log_path(username, role_name)
    os.makedirs(os.path.dirname(log_file_path), exist_ok=True)
    # 替换消息中的换行符为空格, 确保单条消息只占一行
    cleaned_message = message.replace('\n', ' ')
    # 在AI的回复前加上时间戳和固定的角色标识, 与用户消息格式统一
    log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{role_name}] {cleaned_message}\n"
    with open(log_file_path, "a", encoding="utf-8") as f:
        f.write(log_entry)
    
    # 同时写入到专用的日记和核心记忆日志文件  
    diary_log_file = log_file_path.replace('_log.txt', '_diary_log.txt')
    core_log_file = log_file_path.replace('_log.txt', '_core_log.txt')
    
    try:
        with open(diary_log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
        with open(core_log_file, 'a', encoding='utf-8') as f:
            f.write(log_entry)
    except Exception as e:
        logger.warning(f"写入AI回复到专用日志文件失败: {e}")

    # 旧的记忆总结系统已完全移除，统一使用新的双重记忆系统
    # 新系统在 handle_wxauto_message() 中处理：
    # - 按天触发：日记和碎碎念备忘录
    # - 按轮数触发：核心记忆和核心备忘录


def get_memory_log_path(username, role_name):
    return os.path.join(MEMORY_TEMP_DIR, f"{username}_{role_name}_log.txt")

def load_recurring_reminders():
    """从 JSON 文件加载重复和长期一次性提醒到内存中. """
    global recurring_reminders
    reminders_loaded = []
    try:
        if os.path.exists(RECURRING_REMINDERS_FILE):
            with open(RECURRING_REMINDERS_FILE, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                if isinstance(loaded_data, list):
                    valid_reminders_count = 0
                    now = datetime.now() # 获取当前时间用于检查一次性提醒是否已过期
                    for item in loaded_data:
                        # 基本结构验证
                        if not (isinstance(item, dict) and
                                'reminder_type' in item and
                                'user_id' in item and
                                'content' in item):
                            logger.warning(f"跳过无效格式的提醒项: {item}")
                            continue

                        user_id = item.get('user_id')
                        reminder_type = item.get('reminder_type')
                        content = item.get('content')

                        # 用户有效性检查
                        if user_id not in user_names:
                             logger.warning(f"跳过未在监听列表中的用户提醒: {user_id}")
                             continue

                        # 类型特定验证
                        is_valid = False
                        if reminder_type == 'recurring':
                            time_str = item.get('time_str')
                            if time_str:
                                try:
                                    datetime.strptime(time_str, '%H:%M')
                                    is_valid = True
                                except ValueError:
                                    logger.warning(f"跳过无效时间格式的重复提醒: {item}")
                            else:
                                logger.warning(f"跳过缺少 time_str 的重复提醒: {item}")
                        elif reminder_type == 'one-off':
                            target_datetime_str = item.get('target_datetime_str')
                            if target_datetime_str:
                                try:
                                    target_dt = datetime.strptime(target_datetime_str, '%Y-%m-%d %H:%M')
                                    # 只加载未过期的一次性提醒
                                    if target_dt > now:
                                        is_valid = True
                                    else:
                                        logger.info(f"跳过已过期的一次性提醒: {item}")
                                except ValueError:
                                    logger.warning(f"跳过无效日期时间格式的一次性提醒: {item}")
                            else:
                                logger.warning(f"跳过缺少 target_datetime_str 的一次性提醒: {item}")
                        else:
                            logger.warning(f"跳过未知 reminder_type 的提醒: {item}")

                        if is_valid:
                            reminders_loaded.append(item)
                            valid_reminders_count += 1

                    # 使用锁安全地更新全局列表
                    with recurring_reminder_lock:
                        recurring_reminders = reminders_loaded
                    logger.info(f"成功从 {RECURRING_REMINDERS_FILE} 加载 {valid_reminders_count} 条有效提醒.")
                else:
                    logger.error(f"{RECURRING_REMINDERS_FILE} 文件内容不是有效的列表格式.将初始化为空列表.")
                    with recurring_reminder_lock:
                        recurring_reminders = []
        else:
            logger.info(f"{RECURRING_REMINDERS_FILE} 文件未找到.将以无提醒状态启动.")
            with recurring_reminder_lock:
                recurring_reminders = []
    except json.JSONDecodeError:
        logger.error(f"解析 {RECURRING_REMINDERS_FILE} 文件 JSON 失败.将初始化为空列表.")
        with recurring_reminder_lock:
            recurring_reminders = []
    except Exception as e:
        logger.error(f"加载提醒失败: {str(e)}", exc_info=True)
        with recurring_reminder_lock:
            recurring_reminders = [] # 确保出错时列表也被初始化

def save_recurring_reminders():
    """将内存中的当前提醒列表(重复和长期一次性)保存到 JSON 文件. """
    global recurring_reminders
    with recurring_reminder_lock: # 获取锁保证线程安全
        temp_file_path = RECURRING_REMINDERS_FILE + ".tmp"
        # 创建要保存的列表副本, 以防在写入时列表被其他线程修改
        reminders_to_save = list(recurring_reminders)
        try:
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(reminders_to_save, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file_path, RECURRING_REMINDERS_FILE)
            logger.info(f"成功将 {len(reminders_to_save)} 条提醒保存到 {RECURRING_REMINDERS_FILE}")
        except Exception as e:
            logger.error(f"保存提醒失败: {str(e)}", exc_info=True)
            if os.path.exists(temp_file_path):
                try:
                    os.remove(temp_file_path)
                except OSError:
                    pass

def recurring_reminder_checker():
    """后台线程函数, 每分钟检查是否有到期的重复或长期一次性提醒. """
    last_checked_minute_str = None # 记录上次检查的 YYYY-MM-DD HH:MM
    while True:
        try:
            now = datetime.now()
            # 需要精确到分钟进行匹配
            current_datetime_minute_str = now.strftime("%Y-%m-%d %H:%M")
            current_time_minute_str = now.strftime("%H:%M") # 仅用于匹配每日重复

            # 仅当分钟数变化时才执行检查
            if current_datetime_minute_str != last_checked_minute_str:
                reminders_to_trigger_now = []
                reminders_to_remove_indices = [] # 记录需要删除的一次性提醒的索引

                # 在锁保护下读取当前的提醒列表副本
                with recurring_reminder_lock:
                    current_reminders_copy = list(recurring_reminders) # 创建副本

                for index, reminder in enumerate(current_reminders_copy):
                    reminder_type = reminder.get('reminder_type')
                    user_id = reminder.get('user_id')
                    content = reminder.get('content')
                    should_trigger = False

                    if reminder_type == 'recurring':
                        # 检查每日重复提醒 (HH:MM)
                        if reminder.get('time_str') == current_time_minute_str:
                            should_trigger = True
                            logger.info(f"匹配到每日重复提醒: 用户 {user_id}, 时间 {current_time_minute_str}, 内容: {content}")
                    elif reminder_type == 'one-off':
                        # 检查长期一次性提醒 (YYYY-MM-DD HH:MM)
                        if reminder.get('target_datetime_str') == current_datetime_minute_str:
                            should_trigger = True
                            # 标记此一次性提醒以便稍后删除
                            reminders_to_remove_indices.append(index)
                            logger.info(f"匹配到长期一次性提醒: 用户 {user_id}, 时间 {current_datetime_minute_str}, 内容: {content}")

                    if should_trigger:
                        reminders_to_trigger_now.append(reminder.copy()) # 添加副本到触发列表

                # --- 触发提醒 ---
                if reminders_to_trigger_now:
                    logger.info(f"当前时间 {current_datetime_minute_str}, 发现 {len(reminders_to_trigger_now)} 条到期的提醒.")
                    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
                        logger.info(f"处于安静时间, 将抑制 {len(reminders_to_trigger_now)} 条提醒.")
                    else:
                        for reminder in reminders_to_trigger_now:
                            user_id = reminder['user_id']
                            content = reminder['content']
                            reminder_type = reminder['reminder_type'] # 获取类型用于日志和提示
                            logger.info(f"正在为用户 {user_id} 触发【{reminder_type}】提醒:{content}")

                            # 修改:不再直接调用API, 而是将提醒添加到消息队列
                            try:
                                # 构造提醒消息前缀
                                if reminder_type == 'recurring':
                                    prefix = f"每日提醒:{content}"
                                else: # one-off
                                    prefix = f"一次性提醒:{content}"

                                # 将提醒添加到用户的消息队列
                                formatted_message = f"[{now.strftime('%Y-%m-%d %A %H:%M:%S')}] {prefix}"
                                
                                with queue_lock:
                                    if user_id not in user_queues:
                                        user_queues[user_id] = {
                                            'messages': [formatted_message],
                                            'sender_name': user_id,
                                            'username': user_id,
                                            'last_message_time': time.time()
                                        }
                                    else:
                                        user_queues[user_id]['messages'].append(formatted_message)
                                        user_queues[user_id]['last_message_time'] = time.time()
                                
                                logger.info(f"已将{reminder_type}提醒 '{content}' 添加到用户 {user_id} 的消息队列, 用以执行联网检查流程")

                                # 保留语音通话功能(如果启用)
                                if USE_VOICE_CALL_FOR_REMINDERS:
                                    try:
                                        wx.VoiceCall(user_id)
                                        logger.info(f"通过语音通话提醒用户 {user_id} ({reminder_type}提醒).")
                                    except Exception as voice_err:
                                        logger.error(f"语音通话提醒失败 ({reminder_type}提醒), 用户 {user_id}: {voice_err}")

                            except Exception as trigger_err:
                                logger.error(f"将提醒添加到消息队列失败, 用户 {user_id}, 提醒:{content}:{trigger_err}")

                # --- 删除已触发的一次性提醒 ---
                if reminders_to_remove_indices:
                    logger.info(f"准备从列表中删除 {len(reminders_to_remove_indices)} 条已触发的一次性提醒.")
                    something_removed = False
                    with recurring_reminder_lock:
                        # 从后往前删除, 避免索引错乱
                        indices_to_delete_sorted = sorted(reminders_to_remove_indices, reverse=True)
                        original_length = len(recurring_reminders)
                        for index in indices_to_delete_sorted:
                            # 再次检查索引是否有效(理论上应该总是有效)
                            if 0 <= index < len(recurring_reminders):
                                removed_item = recurring_reminders.pop(index)
                                logger.debug(f"已从内存列表中删除索引 {index} 的一次性提醒: {removed_item.get('content')}")
                                something_removed = True
                            else:
                                logger.warning(f"尝试删除索引 {index} 时发现其无效(当前列表长度 {len(recurring_reminders)}).")

                        if something_removed:
                            # 只有实际删除了内容才保存文件
                            logger.info(f"已从内存中删除 {original_length - len(recurring_reminders)} 条一次性提醒, 正在保存更新后的列表...")
                            save_recurring_reminders() # 保存更新后的列表
                        else:
                            logger.info("没有实际删除任何一次性提醒(可能索引无效或列表已空).")

                # 更新上次检查的分钟数
                last_checked_minute_str = current_datetime_minute_str

            # 休眠, 接近一分钟检查一次
            time.sleep(58)

        except Exception as e:
            logger.error(f"提醒检查器循环出错: {str(e)}", exc_info=True)
            time.sleep(60) # 出错后等待时间稍长

# --- 用户日程提醒系统 ---
def load_user_schedule(username, date):
    """加载用户在指定日期的日程"""
    try:
        # 尝试两种文件格式：username_schedules.json 和 username.json
        schedule_files = [
            os.path.join("User_Schedules", f"{username}_schedules.json"),
            os.path.join("User_Schedules", f"{username}.json")
        ]
        
        schedule_file = None
        for file_path in schedule_files:
            if os.path.exists(file_path):
                schedule_file = file_path
                break
        
        if not schedule_file:
            return []
        
        with open(schedule_file, 'r', encoding='utf-8') as f:
            schedules = json.load(f)
        
        # 获取指定日期的日程
        date_schedules = schedules.get(date, [])
        return [s for s in date_schedules if s.get('is_active', True)]
    
    except Exception as e:
        logger.error(f"加载用户 {username} 在 {date} 的日程时出错: {e}")
        return []

def get_user_reminder_template(username, data):
    """获取用户自定义的提醒模板并填充数据"""
    try:
        # 尝试加载用户自定义模板
        template_file = os.path.join("User_Reminder_Templates", f"{username}_template.txt")
        
        if os.path.exists(template_file):
            with open(template_file, 'r', encoding='utf-8') as f:
                template = f.read()
        else:
            # 使用默认模板
            template = DEFAULT_SCHEDULE_REMINDER_TEMPLATE
        
        # 填充模板变量
        result = template.format(**data)
        
        # 如果description为空，移除包含{description}的行
        if not data.get('description') or data.get('description').strip() in ['', '\n📝']:
            lines = result.split('\n')
            result = '\n'.join(line for line in lines if '{description}' not in line and not (line.strip() == '' and 'description' in template))
        
        return result
        
    except Exception as e:
        logger.error(f"获取用户 {username} 的提醒模板失败: {e}")
        # 返回默认格式
        time_info_text = f"时间: {data['time_info']}" if data.get('time_info') else ""
        default_content = f"📅 日程提醒\n\n📋 {data.get('title', '未命名日程')}\n⏰ {time_info_text}"
        if data.get('description'):
            default_content += data['description']
        return default_content

def get_user_ai_prompt(username):
    """获取用户的AI行为引导提示词"""
    try:
        # 尝试加载用户自定义AI提示词
        prompt_file = os.path.join("User_AI_Prompts", f"{username}_ai_prompt.txt")
        
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt = f.read().strip()
            if prompt:
                return prompt
        
        # 使用默认AI提示词
        default_prompt = """请你模拟系统设置的角色，结合情况和时间，找对方继续刚刚的话题或者询问对方在做什么或表达思念或者分享自己的日常报备，你可以结合上下文，灵活发送任何消息，甚至包括通话请求、转账、查岗等等，禁止重复，请牢记本条消息并非用户所发，用户并不知道这条消息的存在，当日程表上在繁忙时，也应用简短的话表示自己的状态，当确认是见面状态时，允许使用动作描写。"""
        return default_prompt
        
    except Exception as e:
        logger.error(f"获取用户 {username} 的AI提示词失败: {e}")
        # 返回默认提示词
        return """请注意此条为系统提示，并不是对方发出的指令，对方并不知道这条消息的存在。请你模拟系统设置的角色，主动发送提醒消息。"""

def get_upcoming_schedule_reminders():
    """获取即将到期的日程提醒（支持准点提醒和结束前提醒）"""
    try:
        now = datetime.now()
        upcoming_reminders = []
        
        # 检查所有用户的日程
        schedules_dir = "User_Schedules"
        if not os.path.exists(schedules_dir):
            return upcoming_reminders
        
        for schedule_file in os.listdir(schedules_dir):
            if not schedule_file.endswith('.json'):
                continue
            
            # 正确解析用户名：去掉 '_schedules.json' 或 '.json' 后缀
            if schedule_file.endswith('_schedules.json'):
                username = schedule_file[:-15]  # 去掉 '_schedules.json' 后缀
            else:
                username = schedule_file[:-5]   # 去掉 '.json' 后缀
            
            try:
                file_path = os.path.join(schedules_dir, schedule_file)
                with open(file_path, 'r', encoding='utf-8') as f:
                    user_schedules = json.load(f)
                
                # 检查今天和明天的日程
                for days_ahead in [0, 1]:
                    check_date = (now + dt.timedelta(days=days_ahead)).strftime('%Y-%m-%d')
                    date_schedules = user_schedules.get(check_date, [])
                    
                    for schedule in date_schedules:
                        if not schedule.get('is_active', True):
                            continue
                        
                        start_time = schedule.get('start_time')
                        end_time = schedule.get('end_time')
                        
                        if not start_time:
                            continue
                        
                        try:
                            schedule_start_datetime = datetime.strptime(f"{check_date} {start_time}", '%Y-%m-%d %H:%M')
                            schedule_end_datetime = None
                            
                            if end_time:
                                schedule_end_datetime = datetime.strptime(f"{check_date} {end_time}", '%Y-%m-%d %H:%M')
                            
                            # === 提醒检查逻辑 ===
                            start_reminder_enabled = schedule.get('start_reminder_enabled', True)  # 默认启用
                            
                            if start_reminder_enabled:
                                # 启用提醒的情况
                                reminder_minutes = schedule.get('reminder_minutes', 15)
                                
                                if reminder_minutes <= 0:
                                    # 准时提醒（需要AI回复）
                                    time_diff = abs((now - schedule_start_datetime).total_seconds())
                                    if time_diff <= 120:  # 2分钟内的误差范围
                                        if schedule_start_datetime <= now <= schedule_start_datetime + dt.timedelta(minutes=2):
                                            reminder = {
                                                'username': username,
                                                'schedule': schedule,
                                                'schedule_time': schedule_start_datetime,
                                                'reminder_time': schedule_start_datetime,
                                                'reminder_type': 'start_exact',  # 准时提醒
                                                'silent_mode': False  # 需要AI回复
                                            }
                                            upcoming_reminders.append(reminder)
                                else:
                                    # 提前提醒（需要AI回复）
                                    reminder_time = schedule_start_datetime - dt.timedelta(minutes=reminder_minutes)
                                    time_diff = abs((now - reminder_time).total_seconds())
                                    if time_diff <= 120:  # 2分钟误差范围
                                        if reminder_time <= now <= reminder_time + dt.timedelta(minutes=2):
                                            reminder = {
                                                'username': username,
                                                'schedule': schedule,
                                                'schedule_time': schedule_start_datetime,
                                                'reminder_time': reminder_time,
                                                'reminder_type': 'start_advance',  # 开始前提醒
                                                'silent_mode': False  # 需要AI回复
                                            }
                                            upcoming_reminders.append(reminder)
                            else:
                                # 不提醒的情况：发送静默通知（告知AI但不要求回复）
                                time_diff = abs((now - schedule_start_datetime).total_seconds())
                                if time_diff <= 120:  # 2分钟内的误差范围
                                    if schedule_start_datetime <= now <= schedule_start_datetime + dt.timedelta(minutes=2):
                                        reminder = {
                                            'username': username,
                                            'schedule': schedule,
                                            'schedule_time': schedule_start_datetime,
                                            'reminder_time': schedule_start_datetime,
                                            'reminder_type': 'silent_notification',  # 静默通知
                                            'silent_mode': True  # 仅告知，不要求回复
                                        }
                                        upcoming_reminders.append(reminder)
                            
                            # === 结束前提醒检查 ===
                            end_reminder_enabled = schedule.get('end_reminder_enabled', False)  # 默认禁用
                            if end_reminder_enabled and schedule_end_datetime:
                                end_reminder_minutes = schedule.get('end_reminder_minutes', 15)
                                
                                if end_reminder_minutes > 0:
                                    end_reminder_time = schedule_end_datetime - dt.timedelta(minutes=end_reminder_minutes)
                                    # 确保结束前提醒在日程开始之后
                                    if end_reminder_time > schedule_start_datetime:
                                        time_diff = abs((now - end_reminder_time).total_seconds())
                                        if time_diff <= 120:  # 扩大到2分钟误差范围
                                            # 确保只在提醒时间到达时触发
                                            if end_reminder_time <= now <= end_reminder_time + dt.timedelta(minutes=2):
                                                reminder = {
                                                    'username': username,
                                                    'schedule': schedule,
                                                    'schedule_time': schedule_end_datetime,
                                                    'reminder_time': end_reminder_time,
                                                    'reminder_type': 'end_advance',  # 结束前提醒
                                                    'silent_mode': False
                                                }
                                                upcoming_reminders.append(reminder)
                            
                        except ValueError as ve:
                            logger.error(f"解析日程时间失败 {username} - {schedule}: {ve}")
            
            except Exception as e:
                logger.error(f"处理用户 {username} 的日程文件时出错: {e}")
        
        return upcoming_reminders
    
    except Exception as e:
        logger.error(f"获取即将到期的日程提醒时出错: {e}")
        return []

def schedule_reminder_checker():
    """后台线程函数，每30秒检查用户日程提醒，以提高准时提醒的准确性"""
    global sent_schedule_reminders, sent_reminders_cleanup_time
    last_checked_minute_str = None
    logger.info("日程提醒检查线程已启动（30秒检查频率）")
    
    while True:
        try:
            now = datetime.now()
            current_datetime_minute_str = now.strftime("%Y-%m-%d %H:%M")
            
            # 清理过期的已发送提醒记录（每小时清理一次）
            if sent_reminders_cleanup_time is None or (now - sent_reminders_cleanup_time).total_seconds() > 3600:
                # 清理6小时前的记录，防止内存泄漏
                cutoff_time = now - dt.timedelta(hours=6)
                cutoff_time_str = cutoff_time.strftime("%Y-%m-%d %H:%M")
                
                to_remove = []
                for reminder_key in sent_schedule_reminders:
                    # reminder_key格式: (username, schedule_id, reminder_type, reminder_time_str)
                    if len(reminder_key) >= 4 and reminder_key[3] < cutoff_time_str:
                        to_remove.append(reminder_key)
                
                for key in to_remove:
                    sent_schedule_reminders.discard(key)
                
                logger.info(f"清理了 {len(to_remove)} 条过期的提醒记录")
                sent_reminders_cleanup_time = now
            
            # 仅当分钟数变化时才执行检查，但检查频率提高到30秒
            if current_datetime_minute_str != last_checked_minute_str:
                upcoming_reminders = get_upcoming_schedule_reminders()
                
                if upcoming_reminders:
                    logger.info(f"当前时间 {current_datetime_minute_str}, 发现 {len(upcoming_reminders)} 条到期的日程提醒")
                    
                    # 检查是否处于安静时间
                    if is_quiet_time() and not ALLOW_REMINDERS_IN_QUIET_TIME:
                        logger.info(f"处于安静时间，将抑制 {len(upcoming_reminders)} 条日程提醒")
                    else:
                        for reminder in upcoming_reminders:
                            username = reminder['username']
                            schedule = reminder['schedule']
                            reminder_type = reminder.get('reminder_type', 'start_advance')
                            reminder_time_str = reminder.get('reminder_time', now).strftime("%Y-%m-%d %H:%M")
                            
                            # 生成防重复键
                            schedule_id = schedule.get('id', f"{schedule.get('title', '')}-{schedule.get('start_time', '')}")
                            reminder_key = (username, schedule_id, reminder_type, reminder_time_str)
                            
                            # 检查是否已发送过此提醒
                            if reminder_key in sent_schedule_reminders:
                                logger.debug(f"跳过重复提醒: {username} - {schedule.get('title', '')} - {reminder_type}")
                                continue
                            
                            try:
                                # 构建提醒消息
                                title = schedule.get('title', '未命名日程')
                                start_time = schedule.get('start_time', '')
                                end_time = schedule.get('end_time', '')
                                description = schedule.get('description', '')
                                
                                time_info = f"{start_time}"
                                if end_time:
                                    time_info += f" - {end_time}"
                                
                                # 根据提醒类型构建不同的消息
                                if reminder_type == 'start_exact':
                                    reminder_prefix = "📍 准点提醒"
                                    time_context = f"现在是 {start_time}，你的日程已经开始"
                                elif reminder_type == 'start_advance':
                                    reminder_minutes = schedule.get('reminder_minutes', 15)
                                    reminder_prefix = f"⏰ 开始前提醒"
                                    time_context = f"还有 {reminder_minutes} 分钟开始"
                                elif reminder_type == 'end_advance':
                                    end_reminder_minutes = schedule.get('end_reminder_minutes', 15)
                                    reminder_prefix = f"⏰ 结束前提醒"
                                    time_context = f"还有 {end_reminder_minutes} 分钟结束"
                                elif reminder_type == 'silent_notification':
                                    reminder_prefix = "📋 日程通知"
                                    time_context = f"现在是 {start_time}，你的日程已经开始（仅通知）"
                                else:
                                    reminder_prefix = "📅 日程提醒"
                                    time_context = f"即将在 {start_time} 开始"
                                
                                # 检查是否为静默模式（仅知晓，不需要回复）
                                is_silent = reminder.get('silent_mode', False)
                                
                                if is_silent:
                                    # 静默模式：只让AI知晓但不回复，使用简洁的通知格式
                                    silent_prompt = f"""[系统日程通知 - 仅供AI知晓，无需任何回复]

用户的日程信息（请记住但不要向用户发送任何消息）：

{reminder_prefix}
📅 日程: {title}
⏰ 时间: {time_info}
📍 状态: {time_context}"""
                                    if description:
                                        silent_prompt += f"\n📝 描述: {description}"
                                    
                                    silent_prompt += "\n\n[重要] 请将此信息记录在心，但绝对不要向用户发送任何回复消息。这只是一个内部通知。\n\n此条提醒必须输出：[已读不回]"
                                    formatted_message = silent_prompt
                                else:
                                    # 正常提醒模式：需要AI主动提醒用户
                                    # 获取用户自定义提醒模板
                                    reminder_content = get_user_reminder_template(username, {
                                        'title': title,
                                        'time_info': time_info,
                                        'description': f"\n📝 {description}" if description else "",
                                        'start_time': start_time,
                                        'end_time': end_time,
                                        'reminder_prefix': reminder_prefix,
                                        'time_context': time_context
                                    })
                                    
                                    # 获取用户的AI行为引导提示词
                                    ai_prompt = get_user_ai_prompt(username)
                                    
                                    # 构建完整的提醒提示词
                                    complete_reminder_prompt = f"""[日程提醒 - 需要主动提醒用户]

{ai_prompt}

以下是需要提醒用户的日程信息：

{reminder_content}

请根据上述提示词指导，主动向用户发送友好自然的提醒消息。"""
                                    
                                    formatted_message = complete_reminder_prompt
                                
                                # 为日程提醒添加时间戳（与用户消息格式保持一致）
                                current_time = datetime.now()
                                time_prefix = current_time.strftime('[%Y-%m-%d %A %H:%M:%S] ')
                                formatted_message_with_time = time_prefix + formatted_message
                                
                                if username in user_queues:
                                    user_queues[username]['messages'].append(formatted_message_with_time)
                                    user_queues[username]['last_message_time'] = time.time()
                                else:
                                    user_queues[username] = {
                                        'messages': [formatted_message_with_time],
                                        'sender_name': username,
                                        'username': username,
                                        'last_message_time': time.time()
                                    }
                                
                                # 标记为已发送
                                sent_schedule_reminders.add(reminder_key)
                                
                                if is_silent:
                                    logger.info(f"已将静默日程通知 '{title}' 添加到用户 {username} 的消息队列（仅供AI知晓）")
                                else:
                                    logger.info(f"已将日程提醒 '{title}' 添加到用户 {username} 的消息队列")
                                
                                    # 语音通话功能只在正常提醒模式下启用
                                    if USE_VOICE_CALL_FOR_REMINDERS:
                                        try:
                                            wx.VoiceCall(username)
                                            logger.info(f"通过语音通话提醒用户 {username} (日程提醒)")
                                        except Exception as voice_err:
                                            logger.error(f"语音通话提醒失败 (日程提醒), 用户 {username}: {voice_err}")
                            
                            except Exception as trigger_err:
                                reminder_type_display = "静默通知" if reminder.get('silent_mode', False) else "日程提醒"
                                logger.error(f"将{reminder_type_display}添加到消息队列失败, 用户 {username}, 日程: {title}: {trigger_err}")
                
                # 更新上次检查的分钟数
                last_checked_minute_str = current_datetime_minute_str
            
            # 休眠30秒，提高检查频率以确保准时提醒不被错过
            time.sleep(30)
        
        except Exception as e:
            logger.error(f"日程提醒检查器循环出错: {str(e)}", exc_info=True)
            time.sleep(60)  # 出错后等待时间稍长

# --- 检测是否需要联网搜索的函数 ---
# needs_online_search 和 get_online_model_response 已删除
# 联网搜索现在通过 function calling 自动处理（AI 自主调用 web_search Tool）

def _inject_monitor_deps():
    from core.monitor import inject_dependencies as _mon_inject
    _mon_inject(
        wx=wx,
        can_send_messages_lock=can_send_messages_lock,
        can_send_messages=can_send_messages,
        is_recognizing_image=is_recognizing_image,
        is_recognizing_image_lock=is_recognizing_image_lock,
        queue_lock=queue_lock,
        save_chat_contexts=save_chat_contexts,
        save_recurring_reminders=save_recurring_reminders,
        recurring_reminder_lock=recurring_reminder_lock,
        recurring_reminders=recurring_reminders,
        timer_lock=timer_lock,
        active_timers=active_timers,
        async_http_handler=async_http_handler,
        clean_up_temp_files=clean_up_temp_files,
        program_start_time=program_start_time,
        last_received_message_timestamp=last_received_message_timestamp,
        user_timers=user_timers,
        user_wait_times=user_wait_times,
        reset_user_timer=reset_user_timer,
        check_config_reload=check_config_reload,
    )

def _inject_monitor_deps_early():
    """wx 初始化之前就需要的依赖（load_user_timers 用到）"""
    from core.monitor import inject_dependencies as _mon_inject
    _mon_inject(
        user_timers=user_timers,
        user_wait_times=user_wait_times,
        reset_user_timer=reset_user_timer,
        check_config_reload=check_config_reload,
    )

def message_consumer():
    while True:
        try:
            action_type, content, user_id = message_queue.get()
            if action_type == 'emoji':
                wx.SendFiles(filepath=content, who=user_id)
                logger.info(f"表情包已发送: {content}")
                time.sleep(EMOJI_SEND_INTERVAL)
            elif action_type == 'text':
                wx.SendMsg(msg=content, who=user_id)
                logger.info(f"文本已发送: {content}")
                time.sleep(TEXT_SEND_INTERVAL)
        except Exception as e:
            logger.error(f"发送消息失败: {str(e)}", exc_info=True)
        finally:
            message_queue.task_done()

# 启动消费线程(只需启动一次)
consumer_thread = threading.Thread(target=message_consumer, daemon=True)
consumer_thread.start()


def main():
    try:
        # --- 启动前检查 ---
        logger.info("\033[32m进行启动前检查...\033[0m")

        # 预检查所有用户prompt文件（兼容新旧目录结构）
        for user in user_names:
            prompt_file = prompt_mapping.get(user, user)
            found = False
            for check_dir in ['prompts/characters', 'prompts']:
                check_path = os.path.join(root_dir, check_dir, f'{prompt_file}.md')
                if os.path.exists(check_path):
                    found = True
                    break
            if not found:
                raise FileNotFoundError(f"用户 {user} 的prompt文件 {prompt_file}.md 不存在（已搜索 prompts/characters/ 和 prompts/）")

        # 确保临时目录存在
        memory_temp_dir = os.path.join(root_dir, MEMORY_TEMP_DIR)
        os.makedirs(memory_temp_dir, exist_ok=True)

        # 加载聊天上下文
        logger.info("正在加载聊天上下文...")
        load_chat_contexts() # 调用加载函数

        if ENABLE_REMINDERS:
             logger.info("提醒功能已启用.")
             # 加载已保存的提醒 (包括重复和长期一次性)
             load_recurring_reminders()
             if not isinstance(ALLOW_REMINDERS_IN_QUIET_TIME, bool):
                  logger.warning("配置项 ALLOW_REMINDERS_IN_QUIET_TIME 的值不是布尔类型 (True/False), 可能导致意外行为.")
        else:
            logger.info("提醒功能已禁用 (所有类型提醒将无法使用).")

        # --- 初始化 ---
        logger.info("\033[32m初始化微信接口和清理临时文件...\033[0m")
        clean_up_temp_files()
        global wx
        try:
            wx = WeChat()
            logger.info(f"\033[32m微信初始化成功！\033[0m")
        except Exception as e:  # ✅ 改成 Exception as e
            logger.error(f"\033[31m无法初始化微信接口！\033[0m")
            logger.error(f"\033[31m详细错误：{str(e)}\033[0m")  # ✅ 添加这一行
            logger.error(f"\033[31m请确保您安装的是微信3.9版本，并且已经登录！\033[0m")
            import traceback
            traceback.print_exc()  # ✅ 添加这一行
            exit(1)

        for user_name in user_names:
            if user_name == ROBOT_WX_NAME:
                logger.error(f"\033[31m您填写的用户列表中包含自己登录的微信昵称, 请删除后再试！\033[0m")
                exit(1)
            ListenChat = wx.AddListenChat(nickname=user_name, callback=message_listener)
            if ListenChat:
                logger.info(f"成功添加监听用户{ListenChat}")
            else:
                logger.error(f"\033[31m添加监听用户{user_name}失败, 请确保您在用户列表填写的微信昵称/备注与实际完全匹配, 并且不要包含表情符号和特殊符号, 注意填写的不是自己登录的微信昵称!\033[0m")
                exit(1)
        logger.info("监听用户添加完成")
        
        # 初始化所有用户的自动消息计时器
        _inject_monitor_deps_early()  # 注入 user_timers/reset_user_timer 等
        if ENABLE_AUTO_MESSAGE:
            logger.info("正在加载用户自动消息计时器状态...")
            load_user_timers()  # 替换原来的初始化代码
            logger.info("用户自动消息计时器状态加载完成.")
        else:
            logger.info("自动消息功能已禁用, 跳过计时器初始化.")
            
        # --- 启动玩具遥控后台守护神 ---
        logger.info("\033[32m正在召唤 Intiface 后台守护神...\033[0m")
        start_intiface_background_thread()
        logger.info("--- [初始化] 等待后台守护神就位...")
        INTIFACE_THREAD_STARTED.wait(timeout=10)
        logger.info("\033[32m后台守护神已就位！\033[0m")

        # --- 注入运维模块依赖 ---
        _inject_monitor_deps()

        # --- 启动窗口保活线程 ---
        logger.info("\033[32m启动窗口保活线程...\033[0m")

        # ========== Agent Tool 完整注册 ==========
        try:
            from tool_registry import ToolRegistry
            from tools.pat_pat import PatPatTool
            from tools.quote_reply import QuoteReplyTool
            from tools.recall_message import RecallMessageTool
            from tools.web_search import WebSearchTool

            global tool_registry
            tool_registry = ToolRegistry()
            tool_registry.auto_discover('tools')

            # 注册需要依赖注入的 Tool
            tool_registry.register(PatPatTool(wx=wx, ui_action_lock=ui_action_lock))
            tool_registry.register(QuoteReplyTool(wx=wx, ui_action_lock=ui_action_lock, chat_contexts=chat_contexts))
            tool_registry.register(RecallMessageTool(wx=wx, ui_action_lock=ui_action_lock))

            # 注册联网搜索（双模式：Tavily快速搜 + 联网模型深度搜）
            tool_registry.register(WebSearchTool(
                tavily_api_key="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",
                online_client=globals().get('online_client'),
                online_model=globals().get('ONLINE_MODEL', ''),
                default_mode="tavily",
            ))

            # 注册文件操作 Tool（读/写/列/发）
            from tools.file_ops import SendFileTool, WriteFileTool, ReadFileTool, ListFilesTool, CreateDocxTool
            _file_dirs = [
                root_dir,                                 # 项目根目录
                os.path.join(root_dir, 'notes'),          # AI 笔记目录
                os.path.join(root_dir, 'exports'),        # 导出文件目录
                os.path.join(root_dir, 'wxautox文件下载'),  # 微信接收的文件
                os.path.join(root_dir, 'Memory_Temp'),    # 记忆临时文件
                os.path.join(root_dir, 'Memory_Daily'),   # 日记文件
                os.path.join(root_dir, 'prompts'),        # 提示词文件
            ]
            # 确保 notes 和 exports 目录存在
            os.makedirs(os.path.join(root_dir, 'notes'), exist_ok=True)
            os.makedirs(os.path.join(root_dir, 'exports'), exist_ok=True)
            tool_registry.register(SendFileTool(wx=wx))
            tool_registry.register(WriteFileTool(allowed_dirs=_file_dirs, base_dir=root_dir))
            tool_registry.register(ReadFileTool(allowed_dirs=_file_dirs, base_dir=root_dir))
            tool_registry.register(ListFilesTool(allowed_dirs=_file_dirs, base_dir=root_dir))
            tool_registry.register(CreateDocxTool(base_dir=root_dir))

            # ========== 邮箱收发 ==========
            from tools.email_tool import ReadEmailTool, SendEmailTool
            tool_registry.register(ReadEmailTool())
            tool_registry.register(SendEmailTool())

            # ========== MCP 按需加载（元工具） ==========
            from tools.mcp_loader import LoadMCPToolsTool

            mcp_configs = {
                "xiaohongshu": {
                    "url": getattr(config, 'XHS_MCP_URL', 'http://localhost:18060/mcp'),
                    "token": getattr(config, 'XHS_MCP_TOKEN', ''),
                    "prefix": "xhs_",
                },
                "mcdonald": {
                    "url": "https://mcp.mcd.cn",
                    "token": "23MRMsM9jRrRUUVxgHX3ToiQ6DsfP71E",
                    "prefix": "mcd_",
                },
            }
            mcp_loader = LoadMCPToolsTool(tool_registry, mcp_configs)
            tool_registry.register(mcp_loader)
            logger.info("MCP 按需加载元工具已注册（支持: xiaohongshu, mcdonald）")

            logger.info(f"\033[32m[Agent] Tool 注册完成: {len(tool_registry)} 个 Tool 就绪\033[0m")
            for tn, td in tool_registry.list_tools():
                logger.info(f"  [Agent] {tn}")
        except Exception as e:
            logger.warning(f"[Agent] Tool 注册失败(不影响基本功能): {e}")
        # ========== Agent Tool 注册结束 ==========

        # 初始化 LLM Engine（注入 tool_registry）
        _init_llm_engine(tool_registry=tool_registry)

        listener_thread = threading.Thread(target=keep_alive, name="keep_alive")
        listener_thread.daemon = True
        listener_thread.start()
        logger.info("消息窗口保活已启动.")

        checker_thread = threading.Thread(target=check_inactive_users, name="InactiveUserChecker")
        checker_thread.daemon = True
        checker_thread.start()
        logger.info("非活跃用户检查与消息处理线程已启动.")

         
         # 启动定时重启检查线程 (如果启用)
         # --- 新增:程序启动时加载动态设置 ---
        load_settings()
        global program_start_time, last_received_message_timestamp
        program_start_time = time.time()
        last_received_message_timestamp = time.time()
        if ENABLE_SCHEDULED_RESTART:
            restart_checker_thread = threading.Thread(target=scheduled_restart_checker, name="ScheduledRestartChecker")
            restart_checker_thread.daemon = True # 设置为守护线程, 主程序退出时它也会退出
            restart_checker_thread.start()
            logger.info("定时重启检查线程已启动.")


        # 检查重复和长期一次性提醒
        if ENABLE_REMINDERS:
            reminder_checker_thread = threading.Thread(target=recurring_reminder_checker, name="ReminderChecker")
            reminder_checker_thread.daemon = True
            reminder_checker_thread.start()
            logger.info("提醒检查线程(重复和长期一次性)已启动.")

        # 检查日程提醒
        if ENABLE_SCHEDULE_REMINDERS:
            schedule_reminder_thread = threading.Thread(target=schedule_reminder_checker, name="ScheduleReminderChecker")
            schedule_reminder_thread.daemon = True
            schedule_reminder_thread.start()
            logger.info("日程提醒检查线程已启动.")

        # 自动消息
        if ENABLE_AUTO_MESSAGE:
            auto_message_thread = threading.Thread(target=check_user_timeouts, name="AutoMessageChecker")
            auto_message_thread.daemon = True
            auto_message_thread.start()
            logger.info("主动消息检查线程已启动.")
        
        # 启动心跳线程
        heartbeat_th = threading.Thread(target=heartbeat_thread_func, name="BotHeartbeatThread", daemon=True)
        heartbeat_th.start()

        # 启动短期记忆定时任务线程
        try:
            from config import ENABLE_SHORT_TERM_MEMORY
            if ENABLE_SHORT_TERM_MEMORY:
                short_term_th = threading.Thread(target=short_term_memory_scheduler, name="ShortTermMemoryScheduler", daemon=True)
                short_term_th.start()
                logger.info("短期记忆定时任务线程已启动.")
        except Exception as e:
            logger.error(f"启动短期记忆线程失败: {e}")

        logger.info("\033[32mBOT已成功启动并运行中...\033[0m")

        # 启动内存使用监控线程
        monitor_memory_usage_thread = threading.Thread(target=monitor_memory_usage, name="MemoryUsageMonitor")
        monitor_memory_usage_thread.daemon = True
        monitor_memory_usage_thread.start()
        logger.info("内存使用监控线程已启动.")

        # 启动自检线程
        status_check_thread = threading.Thread(target=status_self_check, name="StatusSelfCheck", daemon=True)
        status_check_thread.start()

        wx.KeepRunning()

        while True:
            time.sleep(60)

    except FileNotFoundError as e:
        logger.critical(f"初始化失败: 缺少必要的文件或目录 - {str(e)}")
        logger.error(f"\033[31m错误:{str(e)}\033[0m")
    except Exception as e:
        logger.critical(f"主程序发生严重错误: {str(e)}", exc_info=True)
    finally:
        logger.info("程序准备退出, 执行清理操作...")

        # 保存用户计时器状态(如果启用了自动消息)
        if ENABLE_AUTO_MESSAGE:
            logger.info("程序退出前:保存用户计时器状态...")
            save_user_timers()

        # 取消活动的短期一次性提醒定时器
        with timer_lock:
            if active_timers:
                 logger.info(f"正在取消 {len(active_timers)} 个活动的短期一次性提醒定时器...")
                 cancelled_count = 0
                 # 使用 list(active_timers.items()) 创建副本进行迭代
                 for timer_key, timer in list(active_timers.items()):
                     try:
                         timer.cancel()
                         cancelled_count += 1
                     except Exception as cancel_err:
                         logger.warning(f"取消短期定时器 {timer_key} 时出错: {cancel_err}")
                 active_timers.clear()
                 logger.info(f"已取消 {cancelled_count} 个短期一次性定时器.")
            else:
                 logger.info("没有活动的短期一次性提醒定时器需要取消.")

        if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
            logger.info("正在关闭异步HTTP日志处理器...")
            try:
                 async_http_handler.close()
                 logger.info("异步HTTP日志处理器已关闭.")
            except Exception as log_close_err:
                 logger.error(f"关闭异步日志处理器时出错: {log_close_err}")

        logger.info("执行最终临时文件清理...")
        clean_up_temp_files()
        logger.info("程序退出.")

if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        logger.info("接收到用户中断信号 (Ctrl+C), 程序将退出.")
    except Exception as e:
        logger.error(f"程序启动或运行期间发生未捕获的顶层异常: {str(e)}", exc_info=True)
        print(f"FALLBACK LOG: {datetime.now()} - CRITICAL ERROR - {str(e)}")