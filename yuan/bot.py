# -*- coding: utf-8 -*-

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# 
# ===============================================================================
# 双记忆功能版本 - Dual Memory System
# ===============================================================================
# 
# 本版本整合了言言双记忆版的核心功能, 实现了双重记忆系统:
# 
# 1. 【日记系统】- 存储在 prompts/*.md 文件中
#    - 记录每日与用户的重要互动和事件
#    - 以时间线形式追加到角色设定文件末尾
#    - 提供温馨, 自然的记忆回顾体验
# 
# 2. 【核心记忆】- 存储在 Memory_Summaries/*.json 文件中  
#    - 提取和保存用户的关键信息, 偏好, 约定等
#    - 用于AI对话中的上下文理解和个性化回复
#    - 支持迭代更新和智能压缩
# 
# 主要特性:
# - get_user_prompt(): 同时加载角色设定+日记+核心记忆  
# - generate_daily_summary(): 生成日记摘要
# - generate_core_memory_update(): 更新核心记忆
# - append_to_memory_section(): 将日记内容追加到.md文件
# 
# ***********************************************************************

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

class NoSelfLoggingFilter(logging.Filter):
    """一个日志过滤器, 防止将发往日志API的请求本身以及导致循环的特定错误再次发送. """
    def filter(self, record):
        msg = record.getMessage()
        # 过滤掉发往/api/log的请求日志, 避免无限循环
        if '/api/log' in msg:
            return False
        # 过滤掉"Bad request syntax"错误, 这是由HTTPS请求HTTP端口引起的, 是噪音
        if 'Bad request syntax' in msg:
            return False
        return True

class AsyncHTTPHandler(logging.Handler):
    def __init__(self, url, retry_attempts=3, timeout=3, max_queue_size=1000, batch_size=20, batch_timeout=5):
        """
        初始化异步 HTTP 日志处理器. 

        Args:
            url (str): 发送日志的目标 URL.
            retry_attempts (int): 发送失败时的重试次数.
            timeout (int): HTTP 请求的超时时间(秒).
            max_queue_size (int): 内存中日志队列的最大容量.
                                  当队列满时, 新的日志消息将被丢弃.
            batch_size (int): 批量处理的日志数量, 达到此数量会触发发送.
            batch_timeout (int): 批处理超时时间(秒), 即使未达到batch_size, 
                               经过此时间也会发送当前累积的日志.
        """
        super().__init__()
        self.url = url
        self.retry_attempts = retry_attempts
        self.timeout = timeout
        self.log_queue = queue.Queue(maxsize=max_queue_size)
        self._stop_event = threading.Event()
        self.dropped_logs_count = 0  # 添加一个计数器来跟踪被丢弃的日志数量
        self.batch_size = batch_size  # 批处理大小
        self.batch_timeout = batch_timeout  # 批处理超时时间
        
        # 新增: 断路器相关属性
        self.consecutive_failures = 0  # 跟踪连续失败次数
        self.circuit_breaker_open = False  # 断路器状态
        self.circuit_breaker_reset_time = None  # 断路器重置时间
        self.CIRCUIT_BREAKER_THRESHOLD = 5  # 触发断路器的连续失败次数
        self.CIRCUIT_BREAKER_RESET_TIMEOUT = 60  # 断路器重置时间(秒)
        
        # 新增: HTTP请求统计
        self.total_requests = 0
        self.failed_requests = 0
        self.last_success_time = time.time()
        
        # 后台线程用于处理日志队列
        self.worker = threading.Thread(target=self._process_queue, daemon=True)
        self.worker.start()

    def emit(self, record):
        """
        格式化日志记录并尝试将其放入队列. 
        如果队列已满, 则放弃该日志并记录警告.
        """
        try:
            log_entry = self.format(record)
            # 使用非阻塞方式放入队列
            self.log_queue.put(log_entry, block=False)
        except queue.Full:
            # 当队列满时, 捕获 queue.Full 异常
            self.dropped_logs_count += 1
            # 避免在日志处理器内部再次调用 logger (可能导致死循环)
            # 每丢弃一定数量的日志后才记录一次, 避免刷屏
            if self.dropped_logs_count % 100 == 1:  # 每丢弃100条日志记录一次(第1, 101, 201...条时记录)
                logging.warning(f"日志队列已满 (容量 {self.log_queue.maxsize}), 已丢弃 {self.dropped_logs_count} 条日志.请检查日志接收端或网络.")
        except Exception:
            # 处理其他可能的格式化或放入队列前的错误
            self.handleError(record)

    def _should_attempt_send(self):
        """检查断路器是否开启, 决定是否尝试发送"""
        if not self.circuit_breaker_open:
            return True
        
        now = time.time()
        if self.circuit_breaker_reset_time and now >= self.circuit_breaker_reset_time:
            # 重置断路器
            logging.info("日志发送断路器重置, 恢复尝试发送")
            self.circuit_breaker_open = False
            self.consecutive_failures = 0
            return True
        
        return False

    def _process_queue(self):
        """
        后台工作线程, 积累一定数量的日志后批量发送到目标 URL. 
        """
        headers = {
            'Content-Type': 'application/json',
            'User-Agent': 'WeChatBot/1.0'
        }
        batch = []  # 用于存储批处理日志
        last_batch_time = time.time()  # 上次发送批处理的时间
        
        while not self._stop_event.is_set():
            try:
                # 等待日志消息, 设置超时以便能响应停止事件和批处理超时
                try:
                    # 使用较短的超时时间以便及时检查批处理超时
                    log_entry = self.log_queue.get(timeout=0.5)
                    batch.append(log_entry)
                    # 标记队列任务完成
                    self.log_queue.task_done()
                except queue.Empty:
                    # 队列为空时, 检查是否应该发送当前批次(超时)
                    pass
                
                current_time = time.time()
                batch_timeout_reached = current_time - last_batch_time >= self.batch_timeout
                batch_size_reached = len(batch) >= self.batch_size
                
                # 如果达到批量大小或超时, 且有日志要发送
                if (batch_size_reached or batch_timeout_reached) and batch:
                    # 新增: 检查断路器状态
                    if self._should_attempt_send():
                        success = self._send_batch(batch, headers)
                        if success:
                            self.consecutive_failures = 0  # 重置失败计数
                            self.last_success_time = time.time()
                        else:
                            self.consecutive_failures += 1
                            self.failed_requests += 1
                            if self.consecutive_failures >= self.CIRCUIT_BREAKER_THRESHOLD:
                                # 打开断路器
                                self.circuit_breaker_open = True
                                self.circuit_breaker_reset_time = time.time() + self.CIRCUIT_BREAKER_RESET_TIMEOUT
                                logging.warning(f"日志发送连续失败 {self.consecutive_failures} 次, 断路器开启 {self.CIRCUIT_BREAKER_RESET_TIMEOUT} 秒")
                    else:
                        # 断路器开启, 暂时不发送
                        reset_remaining = self.circuit_breaker_reset_time - time.time() if self.circuit_breaker_reset_time else 0
                        logging.debug(f"断路器开启状态, 暂不发送 {len(batch)} 条日志, 将在 {reset_remaining:.1f} 秒后尝试恢复")
                    
                    batch = []  # 无论是否发送成功, 都清空批次
                    last_batch_time = current_time  # 重置批处理时间
            
            except Exception as e:
                # 出错时清空当前批次, 避免卡住
                logging.error(f"日志处理队列异常: {str(e)}", exc_info=True)
                batch = []
                last_batch_time = time.time()
                time.sleep(1)  # 出错后暂停一下, 避免CPU占用过高
        
        # 关闭前发送剩余的日志
        if batch:
            self._send_batch(batch, headers)

    def _send_batch(self, batch, headers):
        """
        发送一批日志记录, 使用改进的重试策略
        
        返回:
            bool: 是否成功发送
        """
        data = {'logs': batch}
        
        # 改进1: 使用固定的最大重试延迟上限
        MAX_RETRY_DELAY = 2.0  # 最大重试延迟(秒)
        BASE_DELAY = 0.5       # 基础延迟(秒)
        
        self.total_requests += 1
        
        for attempt in range(self.retry_attempts):
            try:
                resp = requests.post(
                    self.url,
                    json=data,
                    headers=headers,
                    timeout=self.timeout
                )
                resp.raise_for_status()  # 检查 HTTP 错误状态码
                # 成功发送, 记录日志数量
                if attempt > 0:
                    logging.info(f"在第 {attempt+1} 次尝试后成功发送 {len(batch)} 条日志")
                else:
                    logging.debug(f"成功批量发送 {len(batch)} 条日志")
                return True  # 成功返回
            except requests.exceptions.RequestException as e:
                # 改进2: 根据错误类型区分处理
                if isinstance(e, requests.exceptions.Timeout):
                    logging.warning(f"日志发送超时 (尝试 {attempt+1}/{self.retry_attempts})")
                    delay = min(BASE_DELAY, MAX_RETRY_DELAY)  # 对超时使用较短的固定延迟
                elif isinstance(e, requests.exceptions.ConnectionError):
                    logging.warning(f"日志发送连接错误 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                    delay = min(BASE_DELAY * (1.5 ** attempt), MAX_RETRY_DELAY)  # 有限的指数退避
                else:
                    logging.warning(f"日志发送失败 (尝试 {attempt+1}/{self.retry_attempts}): {e}")
                    delay = min(BASE_DELAY * (1.5 ** attempt), MAX_RETRY_DELAY)  # 有限的指数退避
                
                # 最后一次尝试不需要等待
                if attempt < self.retry_attempts - 1:
                    time.sleep(delay)
        
        # 改进3: 所有重试都失败, 记录警告并返回失败状态
        downtime = time.time() - self.last_success_time
        logging.error(f"发送日志批次失败, 已达到最大重试次数 ({self.retry_attempts}), 丢弃 {len(batch)} 条日志 (连续失败: {self.consecutive_failures+1}, 持续时间: {downtime:.1f}秒)")
        return False  # 返回失败状态
    
    def get_stats(self):
        """返回日志处理器的统计信息"""
        return {
            'queue_size': self.log_queue.qsize(),
            'queue_capacity': self.log_queue.maxsize,
            'dropped_logs': self.dropped_logs_count,
            'total_requests': self.total_requests,
            'failed_requests': self.failed_requests,
            'circuit_breaker_status': 'open' if self.circuit_breaker_open else 'closed',
            'consecutive_failures': self.consecutive_failures
        }

    def close(self):
        """
        停止工作线程并等待队列处理完成(或超时). 
        """
        if not self.log_queue.empty():
            logging.info(f"关闭日志处理器, 还有 {self.log_queue.qsize()} 条日志待处理")
            # 尝试等待队列处理完成.注意:原生queue.join()没有超时参数.
            # 这里的超时依赖于下方 worker.join() 的超时.
            self.log_queue.join()

        self._stop_event.set()
        self.worker.join(timeout=self.timeout * self.retry_attempts + 5)  # 等待一个合理的时间
        
        if self.worker.is_alive():
            logging.warning("日志处理线程未能正常退出")
        else:
            logging.info("日志处理线程已正常退出")
        
        super().close()

# 创建日志格式器
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')

# 初始化异步HTTP处理器
async_http_handler = AsyncHTTPHandler(
    url=f'http://localhost:{PORT}/api/log',
    batch_size=20,  # 一次发送20条日志
    batch_timeout=1  # 即使不满20条, 最多等待1秒也发送
)
async_http_handler.setFormatter(formatter)
async_http_handler.addFilter(NoSelfLoggingFilter())

# 配置根Logger
logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.handlers.clear()

# 添加异步HTTP日志处理器
logger.addHandler(async_http_handler)

# 同时可以保留控制台日志处理器
console_handler = logging.StreamHandler()
console_handler.setFormatter(formatter)
logger.addHandler(console_handler)

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
            
def get_deepseek_response(message, user_id, store_context=True, is_summary=False):
    """
    从 DeepSeek API 获取响应, 确保正确的上下文处理, 并持久化上下文. 

    参数:
        message (str): 用户的消息或系统提示词(用于工具调用).
        user_id (str): 用户或系统组件的标识符.
        store_context (bool): 是否将此交互存储到聊天上下文中.
                              对于工具调用(如解析或总结), 设置为 False.
    """
    try:
        # 每次调用都重新加载聊天上下文, 以应对文件被外部修改的情况
        load_chat_contexts()
        
        logger.info(f"调用 Chat API - ID: {user_id}, 是否存储上下文: {store_context}, 消息: {message[:100]}...") # 日志记录消息片段

        messages_to_send = []
        context_limit = MAX_GROUPS * 2  # 最大消息总数(不包括系统消息)

        if store_context:
            # --- 2024-05-24: 分角色记忆 ---
            # 1. 获取用户当前的角色(prompt)
            prompt_name = prompt_mapping.get(user_id, user_id)
            
            # 2. 检索相关记忆 + 获取系统提示词
            try:
                from memory_retrieval import retrieve_memories
                # 拼接最近对话上下文，供 LLM 精筛使用
                _recent_ctx = ""
                try:
                    with queue_lock:
                        _user_data = chat_contexts.get(user_id, {})
                        if isinstance(_user_data, dict):
                            _ctx_list = _user_data.get(prompt_name, [])
                            # 取最近 6 条（约 3 轮对话），每条截断 300 字
                            for _msg in _ctx_list[-6:]:
                                _role = "用户" if _msg.get("role") == "user" else "角色"
                                _recent_ctx += f"{_role}: {_msg.get('content', '')[:300]}\n"
                except Exception:
                    pass
                retrieved = retrieve_memories(message, recent_context=_recent_ctx)
            except Exception as e:
                logger.error(f"记忆检索失败: {e}")
                retrieved = None
            
            try:
                user_prompt = get_user_prompt(user_id, retrieved_memories=retrieved)
                messages_to_send.append({"role": "system", "content": user_prompt})
            except FileNotFoundError as e:
                logger.error(f"用户 {user_id} 的提示文件错误: {e}, 使用默认提示.")
                messages_to_send.append({"role": "system", "content": "你是一个乐于助人的助手."})

            # 3. 管理并检索聊天历史记录
            with queue_lock: # 确保对 chat_contexts 的访问是线程安全的
                # 确保用户条目存在且为字典格式, 处理旧格式到新格式的迁移
                user_data = chat_contexts.get(user_id)
                # 2024-05-24: 修正迁移逻辑
                # Bot不应执行自动迁移, 因为它无法确知旧列表格式上下文对应的原始Prompt.
                # 正确的迁移逻辑已移至config_editor.py的submit_config函数中, 在用户明确切换角色时触发.
                # 如果在此处仍检测到列表格式, 说明数据尚未迁移.为避免数据错乱, 我们将为当前角色开启全新的对话历史.
                if not isinstance(user_data, dict):
                    if isinstance(user_data, list) and user_data:
                        logger.warning(f"用户 {user_id} 存在未迁移的旧格式上下文.机器人将为当前角色 '{prompt_name}' 开启新的对话历史.旧历史将在下次于UI中切换该用户角色时被正确迁移.")
                    # 初始化一个空的字典, 为当前用户创建一个新的, 符合新格式的上下文容器
                    chat_contexts[user_id] = {}
                
                # 确保当前角色的聊天记录列表存在
                if prompt_name not in chat_contexts[user_id]:
                    chat_contexts[user_id][prompt_name] = []

                # 在添加当前消息之前获取现有历史记录
                history = list(chat_contexts[user_id].get(prompt_name, []))

                # 如果历史记录超过限制, 则进行裁剪
                if len(history) > context_limit:
                    history = history[-context_limit:]

                # 将历史消息添加到 API 请求列表中
                messages_to_send.extend(history)

                # 4. 将当前用户消息添加到 API 请求列表中
                messages_to_send.append({"role": "user", "content": message})

                # 5. 在准备 API 调用后更新持久上下文
                current_context = chat_contexts[user_id][prompt_name]
                current_context.append({"role": "user", "content": message})
                if len(current_context) > context_limit + 1:
                    chat_contexts[user_id][prompt_name] = current_context[-(context_limit + 1):]
                
                save_chat_contexts()

        else:
            # --- 处理工具调用(如提醒解析, 总结) ---
            messages_to_send.append({"role": "user", "content": message})
            logger.info(f"工具调用 (store_context=False), ID: {user_id}.仅发送提供的消息.")

        # --- 调用 API ---
        reply = call_chat_api_with_retry(messages_to_send, user_id, is_summary=is_summary)

        # --- 如果需要, 存储助手回复到上下文中 ---
        if store_context:
            with queue_lock: # 再次获取锁来更新和保存
                prompt_name = prompt_mapping.get(user_id, user_id)
                
                # 再次确保数据结构完整性, 以防万一
                if not isinstance(chat_contexts.get(user_id), dict):
                   chat_contexts[user_id] = {}
                if prompt_name not in chat_contexts[user_id]:
                   chat_contexts[user_id][prompt_name] = []

                current_context = chat_contexts[user_id][prompt_name]
                current_context.append({"role": "assistant", "content": reply})

                if len(current_context) > context_limit:
                    chat_contexts[user_id][prompt_name] = current_context[-context_limit:]
                
                # 保存上下文到文件
                save_chat_contexts() # 在助手回复添加后再次保存
        
        return reply

    except Exception as e:
        logger.error(f"Chat 调用失败 (ID: {user_id}): {str(e)}", exc_info=True)
        
        # 尝试获取用户自定义错误提示词
        custom_message = get_user_error_message(user_id, 'api_failure')
        if custom_message:
            return custom_message
        
        return "等等\脑子有点乱，让我先捋捋"


def strip_before_thought_tags(text):
    # 匹配并截取 </thought> 或 </think> 后面的内容
    match = re.search(r'(?:</thought>|</think>)([\s\S]*)', text)
    if match:
        return match.group(1)
    else:
        return text


def load_memory_prompt(prompt_type, default_prompt):
    """
    从 User_Memory_Prompts 加载自定义提示词，没有则返回默认值。
    prompt_type: 'save_memory' 或 'update_core'
    """
    prompt_file = os.path.join(root_dir, 'User_Memory_Prompts', f'global_{prompt_type}_prompt.txt')
    if os.path.exists(prompt_file):
        try:
            with open(prompt_file, 'r', encoding='utf-8') as f:
                custom = f.read().strip()
            if custom:
                logger.info(f"🧠 使用自定义{prompt_type}提示词（{len(custom)}字符）")
                return custom
        except Exception as e:
            logger.warning(f"读取自定义提示词失败: {e}")
    return default_prompt


def extract_memory_tags(text):
    """
    从 AI 回复中提取并剥离 [SAVE_MEMORY: ...] 或 [UPDATE_CORE: ...] 标记
    
    Returns:
        (cleaned_text, tag_type, tag_content)
        tag_type: "save" | "core" | None
        tag_content: 标记内容 | None
    """
    # 先检查 UPDATE_CORE
    core_pattern = r'\n?\s*\[UPDATE_CORE:\s*(.+?)\]\s*$'
    core_match = re.search(core_pattern, text)
    if core_match:
        tag_content = core_match.group(1).strip()
        cleaned = text[:core_match.start()].rstrip()
        logger.info(f"🧠 检测到核心记忆标记: {tag_content}")
        return cleaned, "core", tag_content
    
    # 再检查 SAVE_MEMORY
    save_pattern = r'\n?\s*\[SAVE_MEMORY:\s*(.+?)\]\s*$'
    save_match = re.search(save_pattern, text)
    if save_match:
        tag_content = save_match.group(1).strip()
        cleaned = text[:save_match.start()].rstrip()
        logger.info(f"🧠 检测到碎片记忆标记: {tag_content}")
        return cleaned, "save", tag_content
    
    return text, None, None


def extract_save_memory_tag(text):
    """
    兼容旧接口：从 AI 回复中提取并剥离记忆标记
    
    Returns:
        (cleaned_text, tag_content) - 清理后的文本和标记内容（None 如果没有标记）
    """
    cleaned, tag_type, tag_content = extract_memory_tags(text)
    return cleaned, tag_content


def async_generate_memory_entry(user_id, tag_description, user_message, ai_reply):
    """
    异步生成记忆条目并追加到 memory_entries.json
    
    Args:
        user_id: 用户 ID
        tag_description: [SAVE_MEMORY] 标记中的描述文本
        user_message: 触发此记忆的用户消息
        ai_reply: AI 的回复内容
    """
    try:
        logger.info(f"🧠 开始异步生成记忆条目: {tag_description}")
        
        # 获取尽可能完整的对话上下文（不限制轮数，但限制总字符数防止过长）
        recent_context = ""
        try:
            prompt_name = prompt_mapping.get(user_id, user_id)
            with queue_lock:
                user_data = chat_contexts.get(user_id, {})
                if isinstance(user_data, dict):
                    context_list = user_data.get(prompt_name, [])
                    # 从最新往前取，直到总字符数超过限制
                    MAX_CONTEXT_CHARS = 8000  # 约2000-3000 token
                    collected = []
                    total_chars = 0
                    for msg in reversed(context_list):
                        content = msg.get('content', '')[:500]  # 单条最多500字
                        total_chars += len(content)
                        if total_chars > MAX_CONTEXT_CHARS:
                            break
                        collected.append(msg)
                    collected.reverse()
                    for msg in collected:
                        role = "用户" if msg.get("role") == "user" else "角色"
                        recent_context += f"{role}: {msg.get('content', '')[:500]}\n"
        except Exception as e:
            logger.warning(f"获取对话上下文失败: {e}")
            recent_context = f"用户: {user_message[:300]}\n角色: {ai_reply[:300]}\n"

        # 构建提示词让便宜模型生成 event + summary + content
        default_save_prompt = """你是一位记忆档案师。以下是一段角色扮演中"袁朗"与"郁邈"的对话记录，以及袁朗认为值得记住的事情。

请基于对话内容，找到与标记描述相关的完整事件脉络，生成三个字段：

### event
3-8个客观事实关键词，逗号分隔，用日常口语词汇。

### summary  
30-60字，以袁朗第一人称视角，同时包含事件概括和情感体验。

### content
100-300字，以袁朗第一人称视角的详细记忆，保留具体细节和情感色彩。
注意：只记录与标记相关的事件，忽略对话中不相关的闲聊部分。

## 袁朗标记的要点
{tag_description}

## 对话记录
{recent_context}

## 输出格式（严格遵守）
event: 关键词1, 关键词2, 关键词3
summary: 一段概要文字
content: 一段详细记忆"""
        
        prompt_template = load_memory_prompt('save_memory', default_save_prompt)
        gen_prompt = prompt_template.replace('{tag_description}', tag_description).replace('{recent_context}', recent_context)

        # 调用 AI 生成
        result = call_ai_for_summary(gen_prompt, user_id)
        
        if not result:
            logger.error("记忆条目生成失败: AI 返回空")
            return

        # 解析结果
        event = ""
        summary = ""
        content = ""
        
        event_match = re.search(r'event:\s*(.+?)(?:\n|$)', result, re.IGNORECASE)
        if event_match:
            event = event_match.group(1).strip()
        
        summary_match = re.search(r'summary:\s*(.+?)(?:\n|$)', result, re.IGNORECASE)
        if summary_match:
            summary = summary_match.group(1).strip()
        
        content_match = re.search(r'content:\s*(.+)', result, re.IGNORECASE | re.DOTALL)
        if content_match:
            content = content_match.group(1).strip()

        if not event or not summary:
            logger.warning(f"记忆条目解析不完整: event={bool(event)}, summary={bool(summary)}")
            # 用标记描述作为 fallback
            if not summary:
                summary = tag_description
            if not event:
                event = tag_description

        # 读取现有 entries 并追加
        from memory_retrieval import MEMORY_ENTRIES_FILE, _memory_entries_cache
        import memory_retrieval
        
        entries = []
        if os.path.exists(MEMORY_ENTRIES_FILE):
            with open(MEMORY_ENTRIES_FILE, 'r', encoding='utf-8') as f:
                entries = json.load(f)
        
        today = datetime.now().strftime('%Y-%m-%d')
        new_id = max((e['id'] for e in entries), default=0) + 1
        
        new_entry = {
            "id": new_id,
            "date": today,
            "event": event,
            "summary": summary,
            "content": content if content else tag_description,
            "memo": ""
        }
        
        entries.append(new_entry)
        
        with open(MEMORY_ENTRIES_FILE, 'w', encoding='utf-8') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        
        # 清除缓存，下次检索时重新加载
        memory_retrieval._memory_entries_cache = None
        memory_retrieval._memory_entries_mtime = 0
        
        logger.info(f"🧠 ✅ 记忆条目已保存: #{new_id} [{today}] {summary[:50]}")
        
    except Exception as e:
        logger.error(f"异步生成记忆条目失败: {e}", exc_info=True)


def async_update_core_memory(user_id, tag_description, user_message, ai_reply):
    """
    AI 主动触发的核心记忆更新。
    读取现有核心记忆 → 结合触发描述和最近对话 → AI 以"关系视角"重新生成 → 覆盖写回。
    
    核心记忆不记事件，记的是：
    - 她是谁（关系本质）
    - 我们之间（关系动态）
    - 我学到的（关系智慧）
    - 印记时刻（最多3-5个关键瞬间，一两句话带过）
    """
    try:
        logger.info(f"🧠💎 开始核心记忆更新: {tag_description}")
        
        memory_key = get_user_memory_key(user_id)
        core_dir = os.path.join(root_dir, MEMORY_CORE_DIR)
        os.makedirs(core_dir, exist_ok=True)
        
        unified_memory_file = os.path.join(core_dir, f'{memory_key}_unified_memory.json')
        
        # 读取现有核心记忆
        existing_content = ""
        if os.path.exists(unified_memory_file):
            try:
                with open(unified_memory_file, 'r', encoding='utf-8') as f:
                    memory_data = json.load(f)
                    existing_content = memory_data.get("content", "")
            except Exception as e:
                logger.warning(f"读取现有核心记忆失败: {e}")
        
        # 如果没有统一格式，尝试旧格式
        if not existing_content:
            old_file = os.path.join(core_dir, f'{memory_key}_core_memory.json')
            if os.path.exists(old_file):
                try:
                    with open(old_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        existing_content = data.get("content", "")
                except:
                    pass
        
        # 获取尽可能完整的对话上下文
        recent_context = ""
        try:
            prompt_name = prompt_mapping.get(user_id, user_id)
            with queue_lock:
                user_data = chat_contexts.get(user_id, {})
                if isinstance(user_data, dict):
                    context_list = user_data.get(prompt_name, [])
                    # 从最新往前取，直到总字符数超过限制
                    MAX_CONTEXT_CHARS = 10000  # 核心记忆给更多上下文
                    collected = []
                    total_chars = 0
                    for msg in reversed(context_list):
                        content = msg.get('content', '')[:500]
                        total_chars += len(content)
                        if total_chars > MAX_CONTEXT_CHARS:
                            break
                        collected.append(msg)
                    collected.reverse()
                    for msg in collected:
                        role = "用户" if msg.get("role") == "user" else "角色"
                        recent_context += f"{role}: {msg.get('content', '')[:500]}\n"
        except Exception as e:
            logger.warning(f"获取对话上下文失败: {e}")
            recent_context = f"用户: {user_message[:300]}\n角色: {ai_reply[:300]}\n"
        
        # 构建核心记忆更新提示词
        default_core_prompt = """你是一位关系心理学专家，正在帮助"袁朗"整理他对"郁邈"的核心认知。

## 你的任务

袁朗刚刚在对话中感受到了一个认知变化：
「{tag_description}」

请基于这个触发点、最近的对话、和他现有的核心记忆，重新生成他的核心记忆。

## 重要原则

核心记忆模拟的是人类的"关系认知" — 一个人想起另一个人时，首先浮现的不是具体事件，而是：
- 抽象的情感色调（"和她在一起很安心"）
- 对这个人的整体认知（"她比看起来脆弱"）
- 关系中学到的模式（"她需要被听见而不是被解决"）

所以核心记忆应该：
✅ 记录关系的本质、情感态度、相处智慧
✅ 记录对她这个人的理解（性格、需求、恐惧、成长）
✅ 保留极少数改变关系性质的关键瞬间（一两句话带过）
❌ 不记流水账式的事件细节
❌ 不堆砌信息，要提炼和浓缩
❌ 不重复碎片记忆已经记录的具体事件

## 现有核心记忆
{existing_content}

## 最近对话
{recent_context}

## 输出要求

以袁朗的第一人称视角，生成完整的核心记忆。控制在800-1500字以内。
用自然段落格式书写，像一个人在心里默默整理对另一个人的认知。
如果现有核心记忆中某些内容仍然准确，保留并可适当精炼。
重点体现这次触发带来的认知变化。

请直接输出核心记忆内容，不要包含任何标题、标记或解释。"""

        prompt_template = load_memory_prompt('update_core', default_core_prompt)
        existing = existing_content if existing_content else "（暂无）"
        update_prompt = prompt_template.replace('{tag_description}', tag_description).replace('{recent_context}', recent_context).replace('{existing_content}', existing)

        # 调用 AI 生成
        new_content = call_ai_for_summary(update_prompt, user_id)
        
        if not new_content:
            logger.error("🧠💎 核心记忆更新失败: AI 返回空")
            return
        
        # 清理内容
        cleaned_content = new_content.strip()
        
        # 保存
        unified_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
            "trigger": tag_description,
            "content": cleaned_content
        }
        
        with open(unified_memory_file, 'w', encoding='utf-8') as f:
            json.dump(unified_data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"🧠💎 ✅ 核心记忆已更新: {tag_description[:50]}，长度: {len(cleaned_content)}")
        
    except Exception as e:
        logger.error(f"核心记忆更新失败: {e}", exc_info=True)


def call_chat_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """
    调用 Chat API，支持多中转站故障转移。
    按 CHAT_API_PROVIDERS 顺序依次尝试，每个中转站失败后自动切换下一个。
    所有中转站都失败后再整体重试。

    参数:
        messages_to_send (list): 要发送给 API 的消息列表.
        user_id (str): 用户或系统组件的标识符.
        max_retries (int): 所有中转站都失败后的整体重试次数.
        is_summary (bool): 标记是否为总结任务.

    返回:
        str: API 返回的文本回复.
    
    异常:
        TimeoutError: 如果总处理时间超过240秒.
    """
    providers = _chat_providers
    if not providers:
        raise RuntimeError("没有配置任何聊天模型中转站")

    # --- 全局超时控制 ---
    TOTAL_TIMEOUT = 240  # 秒
    start_time = time.time()
    last_error = None
    # 不可重试的致命错误关键字
    fatal_keywords = [
        "real name verification", "payment required",
        "user quota", "is not enough", "UnlimitedQuota",
    ]

    for attempt in range(max_retries + 1):
        for pi, provider in enumerate(providers):
            # --- 检查总时间是否已超时 ---
            elapsed_time = time.time() - start_time
            if elapsed_time >= TOTAL_TIMEOUT:
                logger.error(f"API调用总时间超过 {TOTAL_TIMEOUT} 秒, 已超时. 用户: {user_id}")
                raise TimeoutError(f"API call timed out after {TOTAL_TIMEOUT} seconds.")

            p_name = provider.get('name', f'中转站#{pi+1}')
            p_url = provider.get('base_url', '')
            p_key = provider.get('api_key', '')
            p_model = provider.get('model', MODEL)

            if not p_url or not p_key:
                logger.warning(f"中转站 [{p_name}] 缺少 URL 或 Key，跳过")
                continue

            request_timeout = TOTAL_TIMEOUT - (time.time() - start_time)
            if request_timeout <= 0:
                raise TimeoutError(f"API call timed out after {TOTAL_TIMEOUT} seconds.")

            try:
                logger.info(f"调用中转站 [{p_name}] 模型: {p_model} (尝试 {attempt+1}/{max_retries+1})")
                logger.debug(f"发送给 API 的消息 (ID: {user_id}): {messages_to_send}")

                # 每次创建新 client 防止连接池污染
                api_client = OpenAI(
                    api_key=p_key,
                    base_url=p_url,
                    default_headers=_BROWSER_HEADERS
                )

                response = api_client.chat.completions.create(
                    model=p_model,
                    messages=messages_to_send,
                    temperature=TEMPERATURE,
                    max_tokens=MAX_TOKEN,
                    stream=True,
                    timeout=request_timeout
                )

                full_content = ""
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, 'content') and delta.content:
                            full_content += delta.content

                if full_content:
                    content = full_content.strip()
                    if content and "[image]" not in content:
                        filtered_content = strip_before_thought_tags(content)
                        if filtered_content:
                            return filtered_content

                # 空回复，记录后尝试下一个中转站
                logger.warning(f"中转站 [{p_name}] 返回空内容，尝试下一个")
                last_error = RuntimeError(f"中转站 [{p_name}] 返回空内容")
                continue

            except APITimeoutError:
                elapsed = time.time() - start_time
                logger.warning(f"中转站 [{p_name}] 请求超时 (总已用时: {elapsed:.1f}s)，切换下一个")
                last_error = TimeoutError(f"中转站 [{p_name}] 超时")
                continue

            except Exception as e:
                error_info = str(e).lower()
                logger.error(f"中转站 [{p_name}] 调用 {p_model} 失败 (ID: {user_id}): {e}")

                # 致命错误直接终止，不再尝试其他中转站
                for kw in fatal_keywords:
                    if kw in error_info:
                        logger.error(f"致命错误 ({kw})，停止重试")
                        if "sensitive words detected" in error_info:
                            if ENABLE_SENSITIVE_CONTENT_CLEARING:
                                clear_chat_context(user_id)
                                if is_summary:
                                    clear_memory_temp_files(user_id)
                        raise RuntimeError(f"API 致命错误: {e}")

                if "sensitive words detected" in error_info:
                    if ENABLE_SENSITIVE_CONTENT_CLEARING:
                        logger.warning(f"检测到敏感词，清除用户 {user_id} 的上下文")
                        clear_chat_context(user_id)
                        if is_summary:
                            clear_memory_temp_files(user_id)
                    raise RuntimeError(f"敏感词错误: {e}")

                # 非致命错误，切换下一个中转站
                last_error = e
                logger.warning(f"非致命错误，切换下一个中转站: {e}")
                continue

        # 一轮所有中转站都失败了
        if attempt < max_retries:
            logger.warning(f"所有中转站都失败，等待 3 秒后进行第 {attempt+2} 轮重试...")
            time.sleep(3)

    # 所有重试都失败
    # 尝试读取用户自定义错误消息
    error_msg = "宝宝窝被妖怪抓走惹qwqq"
    try:
        error_file = os.path.join(root_dir, 'User_Error_Messages', f'{user_id}_api_failure_error.txt')
        if os.path.exists(error_file):
            with open(error_file, 'r', encoding='utf-8') as f:
                custom_msg = f.read().strip()
                if custom_msg:
                    error_msg = custom_msg
    except Exception:
        pass
    raise RuntimeError(error_msg)


def get_assistant_response(message, user_id, is_summary=False, system_prompt=None):
    """
    从辅助模型 API 获取响应, 专用于判断型任务(表情, 联网, 提醒解析等). 
    不存储聊天上下文, 仅用于辅助判断.

    参数:
        message (str): 要发送给辅助模型的消息.
        user_id (str): 用户或系统组件的标识符.
        is_summary (bool): 标记是否为总结任务, 用于敏感词回退.
        system_prompt (str, optional): 一个可选的系统提示词. Defaults to None.
    """
    if not assistant_client:
        logger.warning(f"辅助模型客户端未初始化, 回退使用主模型.用户ID: {user_id}")
        # 回退到主模型
        # 注意:主模型调用不传递 system_prompt, 因为它有自己的 get_user_prompt 逻辑
        return get_deepseek_response(message, user_id, store_context=False, is_summary=is_summary)
    
    try:
        if system_prompt:
             logger.info(f"调用辅助模型 API (带系统提示) - ID: {user_id}, 消息: {message[:100]}...")
        else:
             logger.info(f"调用辅助模型 API - ID: {user_id}, 消息: {message[:100]}...")
        
        messages_to_send = []
        if system_prompt:
            messages_to_send.append({"role": "system", "content": system_prompt})
        messages_to_send.append({"role": "user", "content": message})
        
        # 调用辅助模型 API
        reply = call_assistant_api_with_retry(messages_to_send, user_id, is_summary=is_summary)
        
        return reply

    except Exception as e:
        logger.error(f"辅助模型调用失败 (ID: {user_id}): {str(e)}", exc_info=True)
        logger.warning(f"辅助模型调用失败, 回退使用主模型.用户ID: {user_id}")
        # 回退到主模型
        return get_deepseek_response(message, user_id, store_context=False, is_summary=is_summary)

def call_assistant_api_with_retry(messages_to_send, user_id, max_retries=2, is_summary=False):
    """
    调用辅助模型 API 并在第一次失败或返回空结果时重试. 

    参数:
        messages_to_send (list): 要发送给辅助模型的消息列表.
        user_id (str): 用户或系统组件的标识符.
        max_retries (int): 最大重试次数.

    返回:
        str: 辅助模型返回的文本回复.
    """
    if not assistant_client:
        logger.error("辅助模型客户端在 call_assistant_api_with_retry 中未初始化, 这是一个逻辑错误.")
        raise RuntimeError("抱歉, 辅助模型现在有点忙, 稍后再试吧.")
        
    attempt = 0
    while attempt <= max_retries:
        try:
            logger.debug(f"发送给辅助模型 API 的消息 (ID: {user_id}): {messages_to_send}")

            response = assistant_client.chat.completions.create(
                model=ASSISTANT_MODEL,
                messages=messages_to_send,
                temperature=ASSISTANT_TEMPERATURE,
                max_tokens=ASSISTANT_MAX_TOKEN,
                stream=False
            )

            if response.choices and len(response.choices) > 0:
                if hasattr(response.choices[0], 'message') and response.choices[0].message:
                    content = response.choices[0].message.content
                    if content:
                        content = content.strip()
                        if content and "[image]" not in content:
                            filtered_content = strip_before_thought_tags(content)
                            if filtered_content:
                                return filtered_content

            # 记录错误日志
            logger.error("辅助模型错误请求消息体:")
            logger.error(f"{ASSISTANT_MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            logger.error("辅助模型 API 返回了空的选择项或内容为空.")
            logger.error(f"完整响应对象: {response}")

        except Exception as e:
            logger.error("辅助模型错误请求消息体:")
            logger.error(f"{ASSISTANT_MODEL}")
            logger.error(json.dumps(messages_to_send, ensure_ascii=False, indent=2))
            error_info = str(e)
            logger.error(f"辅助模型自动重试:第 {attempt + 1} 次调用失败 (ID: {user_id}) 原因: {error_info}", exc_info=False)

            # 细化错误分类
            if "real name verification" in error_info:
                logger.error("\033[31m错误:API 服务商反馈请完成实名认证后再使用！\033[0m")
                break  # 终止循环, 不再重试
            elif "rate limit" in error_info:
                logger.error("\033[31m错误:API 服务商反馈当前访问 API 服务频次达到上限, 请稍后再试！\033[0m")
            elif "payment required" in error_info:
                logger.error("\033[31m错误:API 服务商反馈您正在使用付费模型, 请先充值再使用或使用免费额度模型！\033[0m")
                break  # 终止循环, 不再重试
            elif "user quota" in error_info or "is not enough" in error_info or "UnlimitedQuota" in error_info:
                logger.error("\033[31m错误:API 服务商反馈, 你的余额不足, 请先充值再使用! 如有余额, 请检查令牌是否为无限额度.\033[0m")
                break  # 终止循环, 不再重试
            elif "Api key is invalid" in error_info:
                logger.error("\033[31m错误:API 服务商反馈 API KEY 不可用, 请检查配置选项！\033[0m")
            elif "service unavailable" in error_info:
                logger.error("\033[31m错误:API 服务商反馈服务器繁忙, 请稍后再试！\033[0m")
            elif "sensitive words detected" in error_info:
                logger.error("\033[31m错误:提示词中含有敏感词, 无法生成回复, 请联系API服务商！\033[0m")
                if ENABLE_SENSITIVE_CONTENT_CLEARING:
                    logger.warning(f"已开启敏感词自动清除上下文功能, 开始清除用户 {user_id} 的聊天上下文")
                    clear_chat_context(user_id)
                    if is_summary:
                        clear_memory_temp_files(user_id)  # 如果是总结任务, 清除临时文件
                break  # 终止循环, 不再重试
            else:
                logger.error("\033[31m未知错误:" + error_info + "\033[0m")

        attempt += 1

    raise RuntimeError("抱歉, 辅助模型现在有点忙, 稍后再试吧.")

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

def pat_pat_user_threaded(chat_name: str, target_user_name: str):
    """
    在一个新的线程中执行拍一拍操作. 
    【【【终极修正版 - 基于头像位置判断】】】
    核心洞察:依赖消息体位置不可靠, 但头像位置是固定的.
    解决方案:
    - 直接遍历所有头像按钮(ButtonControl), 检查按钮本身的位置.
    - 对方的头像一定在聊天区域的左半部分, 机器人的头像一定在右半部分.
    - 从下往上找到第一个位于左半部分的头像, 就是最终目标.
    
    Args:
        chat_name (str): 聊天窗口的名称 (好友昵称).
        target_user_name (str): 要拍的人的昵称.
    """
    chat_window_control = None
    
    try:
        logger.info(f"[拍一拍任务] 子线程启动:准备在聊天 '{chat_name}' 中拍 '{target_user_name}'.")
        
        wx.ChatWith(chat_name)
        time.sleep(1.0) 

        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        logger.info(f"[拍一拍任务] 正在寻找名为 '{chat_name}' 的独立聊天窗口...")
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[拍一拍任务] 失败:找不到名为 '{chat_name}' 的独立聊天窗口.")
            return

        logger.info(f"[拍一拍任务] 成功锁定目标操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.3)
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[拍一拍任务] 失败:在 '{chat_name}' 窗口中找不到 '消息' 列表控件.")
            return
        
        # 【【【终极修正点:改变定位策略】】】
        logger.info("[拍一拍任务] 采用终极定位策略:从下往上直接扫描头像位置...")
        all_items = message_list.GetChildren()
        target_avatar_button = None
        list_rect = message_list.BoundingRectangle
        
        # 定义屏幕中线, 用于区分左右
        pane_center_x = list_rect.left + list_rect.width() / 2

        # 从下往上遍历所有消息项
        for item in reversed(all_items):
            # 尝试在每个消息项里直接寻找头像按钮
            avatar_button = item.ButtonControl()
            if avatar_button.Exists(0.01): # 用极短的超时时间快速查找
                button_rect = avatar_button.BoundingRectangle
                
                # 判断这个头像按钮是在左边还是右边
                if button_rect.xcenter() < pane_center_x:
                    # 如果在左边, 这一定是对方的头像, 就是我们的目标！
                    logger.info(f"[拍一拍任务] 成功锁定左侧头像按钮, 目标消息: '{item.Name}'")
                    target_avatar_button = avatar_button
                    break # 找到了, 立刻跳出循环
                else:
                    # 如果在右边, 这是机器人自己的头像, 跳过
                    logger.debug(f"[拍一拍任务] 跳过右侧头像, 所属消息: '{item.Name}'")
                    continue
        
        if not target_avatar_button:
            logger.warning(f"[拍一拍任务] 失败:遍历完所有消息, 未找到任何位于左侧的头像按钮.")
            return
            
        avatar_rect = target_avatar_button.BoundingRectangle
        click_x = avatar_rect.left + avatar_rect.width() // 2
        click_y = avatar_rect.top + avatar_rect.height() // 2
      
        logger.info(f"[拍一拍任务] 准备在精确计算的坐标 ({click_x}, {click_y}) 执行右键点击...")
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.25)
        logger.info("[拍一拍任务] 右键点击指令已发送.等待菜单弹出...")
        time.sleep(0.5)

        # --- A/B计划执行区 (这部分保持不变) ---
        action_completed = False

        # --- A计划: 智能识别 ---
        logger.info("[拍一拍任务 - A计划] 尝试通过控件属性智能识别'拍一拍'...")
        uia.uiautomation.SetGlobalSearchTimeout(1.0)
        menu = uia.MenuControl(ClassName='CMenuWnd')
        
        if menu.Exists(0.1):
            logger.info("[拍一拍任务 - A计划] 成功定位菜单容器, 开始遍历子项...")
            pat_item = None
            all_menu_items = menu.GetChildren()
            for item in all_menu_items:
                if item.Name == '拍一拍':
                    pat_item = item
                    break
            
            if pat_item:
                logger.info("[拍一拍任务 - A计划] 成功！已通过名称识别到'拍一拍'项, 准备点击.")
                pat_item.Click()
                action_completed = True
            else:
                found_names = [child.Name for child in all_menu_items]
                logger.warning(f"[拍一拍任务 - A计划] 失败:遍历完成, 但未能找到名为'拍一拍'的项.探测到的名称列表: {found_names}.")
        else:
            logger.warning("[拍一拍任务 - A计划] 失败:未能定位到菜单容器.")

        # --- B计划: 键盘模拟 (如果A计划失败) ---
        if not action_completed:
            logger.info("[拍一拍任务 - B计划] A计划失败, 启动终极后备方案:模拟键盘操作！")
            logger.info("[拍一拍任务 - B计划] 正在发送键盘指令: [Down] -> [Down] -> [Enter]")
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('enter')
            action_completed = True
        
        if action_completed:
            logger.info(f"🎉🎉🎉 [拍一拍任务] 任务圆满成功！已对 '{target_user_name}' 执行了拍一拍. 🎉🎉🎉")
        else:
            logger.error("[拍一拍任务] 致命错误:A计划与B计划全部失败, 无法执行操作.")


    except Exception as e:
        logger.error(f"[拍一拍任务] 执行时发生未知严重错误", exc_info=True)
        try:
            custom_message = get_user_error_message(chat_name, 'operation_failure')
            error_msg = custom_message if custom_message else "抱歉, 执行拍一拍操作时内部发生严重错误, 请检查后台日志."
            wx.SendMsg(msg=error_msg, who=chat_name)
        except Exception: pass
    finally:
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        logger.debug(f"[拍一拍任务] 任务结束, 资源已释放, 全局超时已恢复为 {DEFAULT_UI_AUTOMATION_TIMEOUT} 秒.")

def pat_myself_threaded(chat_name: str):
    """
    【【【V2 - 修正版】】】
    在一个新的线程中执行“拍一拍自己”的操作. 
    修正了之前使用左键双击的不可靠方法, 改为和“拍一拍对方”逻辑一致的右键菜单操作.
    """
    chat_window_control = None
    try:
        logger.info(f"[拍自己任务] 子线程启动:准备在聊天 '{chat_name}' 中拍自己.")
        
        # 步骤 1: 激活聊天窗口
        wx.ChatWith(chat_name)
        time.sleep(1.0) 
        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[拍自己任务] 失败:找不到名为 '{chat_name}' 的聊天窗口.")
            return

        logger.info(f"[拍自己任务] 成功锁定操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.3)
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[拍自己任务] 失败:在 '{chat_name}' 窗口中找不到 '消息' 列表控件.")
            return
        
        # 步骤 2: 定位自己的头像(右侧)
        logger.info("[拍自己任务] 采用终极定位策略:从下往上扫描右侧头像位置...")
        all_items = message_list.GetChildren()
        my_avatar_button = None
        list_rect = message_list.BoundingRectangle
        pane_center_x = list_rect.left + list_rect.width() / 2

        for item in reversed(all_items):
            avatar_button = item.ButtonControl()
            if avatar_button.Exists(0.01):
                button_rect = avatar_button.BoundingRectangle
                # 【【【核心区别点】】】寻找右侧的头像
                if button_rect.xcenter() > pane_center_x:
                    logger.info(f"[拍自己任务] 成功锁定我方(右侧)头像按钮, 所属消息: '{item.Name}'")
                    my_avatar_button = avatar_button
                    break 
        
        if not my_avatar_button:
            logger.warning(f"[拍自己任务] 失败:未找到任何位于右侧的我方头像.")
            logger.warning("[拍自己任务] 提示:请确保AI在该聊天中至少发送过一条消息.")
            return
            
        # 步骤 3: 模拟右键点击
        avatar_rect = my_avatar_button.BoundingRectangle
        click_x = avatar_rect.left + avatar_rect.width() // 2
        click_y = avatar_rect.top + avatar_rect.height() // 2
      
        logger.info(f"[拍自己任务] 准备在坐标 ({click_x}, {click_y}) 执行右键点击...")
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.25)
        time.sleep(0.5)

        # 步骤 4: A/B计划选择菜单中的“拍一拍”
        action_completed = False
        logger.info("[拍自己任务 - A计划] 尝试通过控件属性智能识别'拍一拍'...")
        uia.uiautomation.SetGlobalSearchTimeout(1.0)
        menu = uia.MenuControl(ClassName='CMenuWnd')
        
        if menu.Exists(0.1):
            pat_item = menu.MenuItemControl(Name='拍一拍')
            if pat_item.Exists(0.1):
                logger.info("[拍自己任务 - A计划] 成功！已识别到'拍一拍'项, 准备点击.")
                pat_item.Click()
                action_completed = True
            else:
                 logger.warning(f"[拍自己任务 - A计划] 失败:未能找到名为'拍一拍'的项.")
        else:
            logger.warning("[拍自己任务 - A计划] 失败:未能定位到菜单容器.")

        if not action_completed:
            logger.info("[拍自己任务 - B计划] A计划失败, 启动终极后备方案:模拟键盘操作！")
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('down')
            time.sleep(0.1)
            pyautogui.press('enter')
            action_completed = True
        
        logger.info(f"🎉 [拍自己任务] 任务成功！已在 '{chat_name}' 窗口执行了拍一拍自己. 🎉")

    except Exception as e:
        logger.error(f"[拍自己任务] 执行时发生未知严重错误", exc_info=True)
    finally:
        # 步骤 5: 释放资源
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        logger.debug(f"[拍自己任务] 任务结束, 资源已释放.")

# ==================== 拍一拍功能区 结束 ====================

# ==================== 撤回消息功能区 开始 ====================

def recall_message_threaded(chat_name: str, message_content: str):
    """
    在一个新的线程中执行撤回消息操作. 
    
    Args:
        chat_name: 聊天窗口名称
        message_content: 要撤回的消息内容
    """
    chat_window_control = None
    
    try:
        logger.info(f"[撤回消息任务] 子线程启动:准备在聊天 '{chat_name}' 中撤回消息: '{message_content[:50]}...'")
        
        wx.ChatWith(chat_name)
        time.sleep(2.0)  # 增加等待时间, 确保消息发送完成
        
        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        logger.info(f"[撤回消息任务] 正在寻找名为 '{chat_name}' 的独立聊天窗口...")
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[撤回消息任务] 失败:找不到名为 '{chat_name}' 的独立聊天窗口.")
            return
            
        logger.info(f"[撤回消息任务] 成功锁定目标操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.5)  # 增加等待
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[撤回消息任务] 失败:在 '{chat_name}' 窗口中找不到 '消息' 列表控件.")
            return
            
        # 从下往上扫描消息, 寻找匹配的内容
        logger.info("[撤回消息任务] 开始扫描消息列表, 寻找要撤回的消息...")
        all_items = message_list.GetChildren()
        logger.info(f"[撤回消息任务] 获取到 {len(all_items)} 个消息项")
        
        if not all_items:
            logger.warning("[撤回消息任务] 消息列表为空, 可能需要等待消息加载")
            time.sleep(3)  # 等待3秒让消息加载
            all_items = message_list.GetChildren()
            logger.info(f"[撤回消息任务] 重新获取到 {len(all_items)} 个消息项")
        
        target_message_item = None
        list_rect = message_list.BoundingRectangle
        pane_center_x = list_rect.left + list_rect.width() // 2
        logger.info(f"[撤回消息任务] 消息列表区域: left={list_rect.left}, width={list_rect.width()}, center={pane_center_x}")
        
        # 从最新的消息开始搜索(倒序)
        logger.info(f"[撤回消息任务] 开始扫描消息列表, 寻找包含'{message_content}'的消息...")
        found_messages = []  # 用于调试, 记录找到的所有消息
        
        # 新策略:找到所有包含目标内容的消息, 然后选择X坐标最大的(最右边的)
        matching_messages = []
        
        for item in reversed(all_items):
            try:
                item_name = item.Name
                if not item_name:
                    continue
                
                # 获取更详细的坐标信息
                item_rect = item.BoundingRectangle
                item_center_x = item_rect.xcenter() if hasattr(item_rect, 'xcenter') else (item_rect.left + item_rect.width() // 2)
                item_left = item_rect.left
                item_right = item_rect.right
                
                position = "右侧(机器人)" if item_center_x > pane_center_x else "左侧(用户)"
                found_messages.append(f"{position}: '{item_name[:30]}...' [left:{item_left}, center:{item_center_x}, right:{item_right}]")
                
                # 检查是否包含要撤回的消息内容
                if message_content.strip() in item_name:
                    matching_messages.append({
                        'item': item,
                        'name': item_name,
                        'center_x': item_center_x,
                        'left': item_left,
                        'right': item_right
                    })
                    logger.info(f"[撤回消息任务] 找到匹配内容的消息: '{item_name}', X范围: {item_left}-{item_right}, 中心: {item_center_x}")
                    logger.info(f"[撤回消息任务] 已将消息添加到匹配列表, 当前匹配数量: {len(matching_messages)}")
                    
            except Exception as e:
                logger.debug(f"[撤回消息任务] 检查消息项时出错: {e}")
                continue
        
        logger.info(f"[撤回消息任务] 消息扫描完成, 找到 {len(matching_messages)} 个匹配的消息")
        
        # 如果找到匹配的消息, 选择第一个(最新的, 因为我们是倒序遍历)
        if matching_messages:
            # 选择第一个匹配的消息(最新发送的)
            target_message = matching_messages[0]
            target_message_item = target_message['item']
            logger.info(f"[撤回消息任务] 选择最新的匹配消息进行撤回: '{target_message['name']}', X中心: {target_message['center_x']}")
        else:
            logger.warning(f"[撤回消息任务] 未找到任何包含内容 '{message_content}' 的消息.")
        
        # 如果没找到, 输出调试信息
        if not target_message_item:
            logger.warning(f"[撤回消息任务] 失败:未找到包含内容 '{message_content}' 的消息.")
            logger.info(f"[撤回消息任务] 调试信息 - 总共扫描了 {len(all_items)} 个消息项")
            logger.info(f"[撤回消息任务] 调试信息 - 找到 {len(matching_messages)} 个匹配的消息")
            logger.info(f"[撤回消息任务] 调试信息 - 最近找到的消息列表:")
            for i, msg in enumerate(found_messages[:10]):  # 只显示最近10条
                logger.info(f"  {i+1}. {msg}")
            logger.info(f"[撤回消息任务] 调试信息 - 聊天窗口中心X坐标: {pane_center_x}")
            return
            
        # 右键点击目标消息
        message_rect = target_message_item.BoundingRectangle
        chat_window_rect = chat_window_control.BoundingRectangle
        
        # 获取详细的窗口和消息信息
        logger.info(f"[撤回消息任务] === 详细坐标信息 ===")
        logger.info(f"[撤回消息任务] 聊天窗口区域: left={chat_window_rect.left}, top={chat_window_rect.top}, right={chat_window_rect.right}, bottom={chat_window_rect.bottom}")
        logger.info(f"[撤回消息任务] 消息区域: left={message_rect.left}, top={message_rect.top}, right={message_rect.right}, bottom={message_rect.bottom}")
        
        message_width = message_rect.width()
        message_height = message_rect.height()
        
        # 保守的点击策略:点击消息的右侧1/4处
        # 确保点击位置在消息内容区域内, 不会超出窗口
        click_x = message_rect.left + int(message_width * 0.8)  # 消息右侧80%处
        click_y = message_rect.top + message_height // 2  # 垂直居中
        
        # 确保点击坐标在聊天窗口范围内
        if click_x >= chat_window_rect.right:
            click_x = chat_window_rect.right - 20
        elif click_x <= chat_window_rect.left:
            click_x = chat_window_rect.left + 20
            
        if click_y >= chat_window_rect.bottom:
            click_y = chat_window_rect.bottom - 20
        elif click_y <= chat_window_rect.top:
            click_y = chat_window_rect.top + 20
        
        # 再次确保点击坐标在消息范围内
        if click_x >= message_rect.right:
            click_x = message_rect.right - 10
        elif click_x <= message_rect.left:
            click_x = message_rect.left + 10
            
        if click_y >= message_rect.bottom:
            click_y = message_rect.bottom - 5
        elif click_y <= message_rect.top:
            click_y = message_rect.top + 5
        
        logger.info(f"[撤回消息任务] 消息尺寸: {message_width}x{message_height}")
        logger.info(f"[撤回消息任务] 计算点击位置: 消息右侧80%处 = ({message_rect.left + int(message_width * 0.8)}, {message_rect.top + message_height // 2})")
        logger.info(f"[撤回消息任务] 最终点击位置: ({click_x}, {click_y})")
        
        # 检查点击位置是否合理
        if (click_x < chat_window_rect.left or click_x > chat_window_rect.right or 
            click_y < chat_window_rect.top or click_y > chat_window_rect.bottom):
            logger.warning(f"[撤回消息任务] 警告:点击位置可能超出聊天窗口范围！")
        
        logger.info(f"[撤回消息任务] 准备执行右键点击...")
        
        # 直接右键点击消息区域
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.25)
        logger.info("[撤回消息任务] 右键点击指令已发送.等待菜单弹出...")
        time.sleep(0.5)
        
        # A/B计划执行撤回操作
        action_completed = False
        
        # A计划: 智能识别撤回选项
        logger.info("[撤回消息任务 - A计划] 尝试通过控件属性智能识别'撤回'...")
        uia.uiautomation.SetGlobalSearchTimeout(1.0)
        menu = uia.MenuControl(ClassName='CMenuWnd')
        
        if menu.Exists(0.1):
            logger.info("[撤回消息任务 - A计划] 成功定位菜单容器, 开始遍历子项...")
            recall_item = None
            all_menu_items = menu.GetChildren()
            for item in all_menu_items:
                if item.Name == '撤回':
                    recall_item = item
                    break
            
            if recall_item:
                logger.info("[撤回消息任务 - A计划] 成功！已通过名称识别到'撤回'项, 准备点击.")
                recall_item.Click()
                action_completed = True
            else:
                found_names = [child.Name for child in all_menu_items]
                logger.warning(f"[撤回消息任务 - A计划] 失败:遍历完成, 但未能找到名为'撤回'的项.探测到的名称列表: {found_names}.")
        else:
            logger.warning("[撤回消息任务 - A计划] 失败:未能定位到菜单容器.")
        
        # B计划: 键盘模拟(如果A计划失败)
        if not action_completed:
            logger.info("[撤回消息任务 - B计划] A计划失败, 启动终极后备方案:模拟键盘操作！")
            logger.info("[撤回消息任务 - B计划] 正在发送键盘指令: 9次[Down]到达撤回选项 -> [Enter]")
            
            # 微信右键菜单:复制(默认选中) -> 需要按9次Down到达撤回
            for i in range(9):  # 按9次Down键到达撤回选项
                pyautogui.press('down')
                time.sleep(0.1)
            
            pyautogui.press('enter')
            time.sleep(0.1)
            action_completed = True
        
        if action_completed:
            logger.info(f"🎉🎉🎉 [撤回消息任务] 任务圆满成功！已撤回消息: '{message_content[:50]}...' 🎉🎉🎉")
        else:
            logger.error("[撤回消息任务] 致命错误:A计划与B计划全部失败, 无法执行撤回操作.")
            
    except Exception as e:
        logger.error(f"[撤回消息任务] 执行时发生未知严重错误", exc_info=True)
        try:
            custom_message = get_user_error_message(chat_name, 'operation_failure')
            error_msg = custom_message if custom_message else "抱歉, 执行撤回操作时内部发生严重错误, 请检查后台日志."
            wx.SendMsg(msg=error_msg, who=chat_name)
        except Exception: 
            pass
    finally:
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        logger.debug(f"[撤回消息任务] 任务结束, 资源已释放, 全局超时已恢复为 {DEFAULT_UI_AUTOMATION_TIMEOUT} 秒.")

# ==================== 撤回消息功能区 结束 ====================

# ==================== 引用消息功能区 开始 ====================

def quote_message_threaded(chat_name: str, message_content: str, additional_text: str = "", message_type: str = None):
    """
    在一个新的线程中执行引用消息操作.
    
    Args:
        chat_name: 聊天窗口名称
        message_content: 要引用的消息内容
        additional_text: 引用后要添加的额外文本内容
        message_type: 消息类型, "user" 表示用户消息, "ai" 表示AI消息, None 表示智能检测
    
    Returns:
        bool: True表示引用成功, False表示引用失败
    """
    global can_send_messages
    chat_window_control = None
    
    try:
        logger.info(f"[引用消息任务] 子线程启动:准备在聊天 '{chat_name}' 中引用消息: '{message_content[:50]}...'")
        
        wx.ChatWith(chat_name)
        time.sleep(3.0)  # 增加等待时间, 确保消息发送完成并避免与其他操作冲突
        
        uia.uiautomation.SetGlobalSearchTimeout(5.0)
        logger.info(f"[引用消息任务] 正在寻找名为 '{chat_name}' 的独立聊天窗口...")
        chat_window_control = uia.WindowControl(Name=chat_name, searchDepth=1)
        
        if not chat_window_control.Exists():
            logger.error(f"[引用消息任务] 失败:找不到名为 '{chat_name}' 的独立聊天窗口.")
            return
            
        logger.info(f"[引用消息任务] 成功锁定目标操作窗口: '{chat_window_control.Name}'")
        chat_window_control.SetActive()
        chat_window_control.SetTopmost(True)
        time.sleep(0.5)
        
        message_list = chat_window_control.ListControl(Name='消息')
        if not message_list.Exists():
            logger.error(f"[引用消息任务] 失败:在 '{chat_name}' 窗口中找不到 '消息' 列表控件.")
            return
            
        # 获取消息列表
        all_items = message_list.GetChildren()
        logger.info(f"[引用消息任务] 获取到 {len(all_items)} 个消息项")
        
        if not all_items:
            logger.warning("[引用消息任务] 消息列表为空, 可能需要等待消息加载")
            time.sleep(3)
            all_items = message_list.GetChildren()
            logger.info(f"[引用消息任务] 重新获取到 {len(all_items)} 个消息项")
        
        target_message_item = None
        list_rect = message_list.BoundingRectangle
        pane_center_x = list_rect.left + list_rect.width() // 2
        logger.info(f"[引用消息任务] 消息列表区域: left={list_rect.left}, width={list_rect.width()}, center={pane_center_x}")
        
        # 寻找匹配的消息
        matching_messages = []
        
        for item in reversed(all_items):
            try:
                item_name = item.Name
                if not item_name:
                    continue
                
                # 获取消息坐标信息
                item_rect = item.BoundingRectangle
                item_center_x = item_rect.xcenter() if hasattr(item_rect, 'xcenter') else (item_rect.left + item_rect.width() // 2)
                item_left = item_rect.left
                item_right = item_rect.right
                
                # 检查是否包含要引用的消息内容
                # 改进的匹配逻辑:更宽松和智能的匹配
                
                # 清理要搜索的消息内容
                cleaned_search_content = message_content.strip()
                # 移除可能的时间戳格式 [YYYY-MM-DD 星期 HH:MM:SS]
                cleaned_search_content = re.sub(r'\[\d{4}-\d{2}-\d{2}.*?\d{2}:\d{2}(:\d{2})?\]', '', cleaned_search_content).strip()
                
                # 清理显示的消息内容
                cleaned_item_name = item_name.strip()
                # 移除换行符和多余空格
                cleaned_item_name = ' '.join(cleaned_item_name.split())
                cleaned_search_content = ' '.join(cleaned_search_content.split())
                
                # 多种匹配方式
                # 方法1:完全包含匹配
                exact_match = cleaned_search_content in cleaned_item_name
                
                # 方法2:反向包含匹配(处理消息可能被截断的情况)
                reverse_match = cleaned_item_name in cleaned_search_content
                
                # 方法3:去除标点符号的模糊匹配(处理特殊字符问题)
                import string
                search_no_punct = cleaned_search_content.translate(str.maketrans('', '', string.punctuation))
                item_no_punct = cleaned_item_name.translate(str.maketrans('', '', string.punctuation))
                fuzzy_match = search_no_punct in item_no_punct or item_no_punct in search_no_punct
                
                # 方法4:关键词匹配(至少50%的词匹配)
                search_words = set(cleaned_search_content.split())
                item_words = set(cleaned_item_name.split())
                if len(search_words) > 0:
                    word_match_ratio = len(search_words.intersection(item_words)) / len(search_words)
                    keyword_match = word_match_ratio >= 0.5
                else:
                    keyword_match = False
                
                # 综合判断:任一匹配方式成功即认为匹配
                is_match = exact_match or reverse_match or fuzzy_match or keyword_match
                
                logger.debug(f"[引用消息任务] 消息匹配检查 - 搜索内容: '{cleaned_search_content}', 消息内容: '{cleaned_item_name[:50]}...'")
                logger.debug(f"[引用消息任务] 匹配结果: 完全:{exact_match}, 反向:{reverse_match}, 模糊:{fuzzy_match}, 关键词:{keyword_match}")
                
                if is_match:
                    # 更精确的AI消息判断逻辑
                    # 方法1: 基于中心点位置 (主要判断)
                    is_ai_by_center = item_center_x > pane_center_x
                    
                    # 方法2: 基于右边界位置 (辅助判断) - AI消息通常更靠右
                    list_width = list_rect.width()
                    is_ai_by_right_edge = item_right > (list_rect.left + list_width * 0.6)
                    
                    # 方法3: 基于左边界位置 (辅助判断) - 用户消息通常从左边开始
                    is_ai_by_left_edge = item_left > (list_rect.left + list_width * 0.25)
                    
                    # 方法4: 基于聊天历史 (最可靠的判断) - 智能匹配AI消息
                    is_ai_by_history = False
                    match_confidence = 0
                    
                    # 如果明确指定了消息类型, 直接使用, 不需要检测
                    if message_type == "ai":
                        is_ai_by_history = True
                        match_confidence = 100
                        logger.info(f"[引用消息任务] 使用显式类型判断:AI消息")
                    elif message_type == "user":
                        is_ai_by_history = False
                        match_confidence = 100
                        logger.info(f"[引用消息任务] 使用显式类型判断:用户消息")
                    else:
                        # 使用智能检测(向后兼容)
                        try:
                            # 获取当前聊天的上下文
                            if chat_name in chat_contexts:
                                for prompt_name, context in chat_contexts[chat_name].items():
                                    # 检查最近的AI回复中是否包含这条消息
                                    for msg in reversed(context[-30:]):  # 检查最近30条消息
                                        if msg.get('role') == 'assistant':
                                            ai_content = msg.get('content', '')
                                            # 清理AI消息内容进行比较 - 移除换行符和多余空格
                                            cleaned_ai_content = ' '.join(ai_content.replace('\n', ' ').split())
                                            
                                            if len(cleaned_search_content) >= 2:  # 降低最小长度要求
                                                confidence = 0
                                                
                                                # 调试:记录每次比较
                                                logger.debug(f"[引用消息任务] 比较: 搜索='{cleaned_search_content}' vs AI='{cleaned_ai_content[:50]}...'")
                                                
                                                # 匹配方法1:完全相同 (最高权重)
                                                if cleaned_search_content == cleaned_ai_content:
                                                    confidence = 100
                                                    logger.debug(f"[引用消息任务] 完全匹配(100%): '{cleaned_search_content}'")
                                            
                                            # 匹配方法2:包含关系匹配(更宽松)
                                            elif cleaned_search_content in cleaned_ai_content:
                                                # AI消息包含搜索内容 (搜索内容可能是AI消息的一部分)
                                                contain_ratio = len(cleaned_search_content) / len(cleaned_ai_content) if len(cleaned_ai_content) > 0 else 0
                                                confidence = max(70, int(contain_ratio * 100))  # 至少70%置信度
                                                logger.debug(f"[引用消息任务] AI包含搜索内容({confidence}%): 占比={contain_ratio:.2f}")
                                            
                                            elif cleaned_ai_content in cleaned_search_content:
                                                # 搜索内容包含AI消息 (AI消息可能被截断)
                                                contain_ratio = len(cleaned_ai_content) / len(cleaned_search_content) if len(cleaned_search_content) > 0 else 0
                                                confidence = max(75, int(contain_ratio * 100))  # 至少75%置信度
                                                logger.debug(f"[引用消息任务] 搜索内容包含AI({confidence}%): 占比={contain_ratio:.2f}")
                                            
                                            # 匹配方法3:词汇重叠匹配
                                            else:
                                                search_words = set(cleaned_search_content.lower().split())
                                                ai_words = set(cleaned_ai_content.lower().split())
                                                
                                                if search_words and ai_words:
                                                    # 计算搜索内容的词在AI内容中的覆盖率
                                                    common_words = search_words & ai_words
                                                    word_coverage = len(common_words) / len(search_words) if len(search_words) > 0 else 0
                                                    
                                                    # 如果大部分关键词都匹配, 可能是同一条消息
                                                    if word_coverage >= 0.7:  # 70%的词匹配
                                                        confidence = int(word_coverage * 85)  # 最高85%置信度
                                                        logger.debug(f"[引用消息任务] 词汇匹配({confidence}%): 覆盖率={word_coverage:.2f}, 共同词={len(common_words)}")
                                            
                                                if confidence >= 70:  # 70%以上置信度
                                                    is_ai_by_history = True
                                                    match_confidence = confidence
                                                    logger.debug(f"[引用消息任务] AI消息匹配成功, 置信度: {confidence}%")
                                                    logger.debug(f"[引用消息任务] 搜索内容: '{cleaned_search_content}'")
                                                    logger.debug(f"[引用消息任务] AI内容: '{cleaned_ai_content[:100]}...'")
                                                    break
                                        if is_ai_by_history:
                                            break
                        except Exception as e:
                            logger.debug(f"[引用消息任务] 检查聊天历史时出错: {e}")
                    
                    # 如果历史记录匹配失败, 输出调试信息(仅在智能检测模式下)
                    if not is_ai_by_history and message_type is None:
                        logger.debug(f"[引用消息任务] 历史记录匹配失败, 搜索内容: '{cleaned_search_content}'")
                        logger.debug(f"[引用消息任务] 将检查最近5条AI消息作为调试:")
                        try:
                            if chat_name in chat_contexts:
                                debug_count = 0
                                for prompt_name, context in chat_contexts[chat_name].items():
                                    for msg in reversed(context[-10:]):
                                        if msg.get('role') == 'assistant' and debug_count < 5:
                                            debug_ai_content = ' '.join(msg.get('content', '').split())
                                            logger.debug(f"[引用消息任务] AI消息{debug_count+1}: '{debug_ai_content[:80]}...'")
                                            debug_count += 1
                                            if debug_count >= 5:
                                                break
                                    if debug_count >= 5:
                                        break
                        except Exception as e:
                            logger.debug(f"[引用消息任务] 调试输出时出错: {e}")
                    
                    # 综合判断:位置指标 + 历史记录指标
                    position_indicators = [is_ai_by_center, is_ai_by_right_edge, is_ai_by_left_edge]
                    position_score = sum(position_indicators)
                    
                    # 如果历史记录明确显示是AI消息, 则权重更高
                    if is_ai_by_history:
                        is_ai_message = True  # 历史记录是最可靠的判断
                    else:
                        is_ai_message = position_score >= 2  # 至少2个位置指标支持才判定为AI消息
                    
                    matching_messages.append({
                        'item': item,
                        'name': item_name,
                        'center_x': item_center_x,
                        'left': item_left,
                        'right': item_right,
                        'is_ai_message': is_ai_message
                    })
                    
                    logger.info(f"[引用消息任务] 找到匹配内容的消息: '{item_name}', X范围: {item_left}-{item_right}, 中心: {item_center_x}")
                    logger.info(f"[引用消息任务] 面板信息: 左边界:{list_rect.left}, 宽度:{list_width}, 中心:{pane_center_x}")
                    logger.info(f"[引用消息任务] 位置判断: 中心点:{is_ai_by_center}, 右边界:{is_ai_by_right_edge}, 左边界:{is_ai_by_left_edge}")
                    logger.info(f"[引用消息任务] 历史记录判断: {is_ai_by_history} (置信度: {match_confidence}%)")
                    logger.info(f"[引用消息任务] 位置得分: {position_score}/3, 最终判断: {'AI消息(右侧)' if is_ai_message else '用户消息(左侧)'}")
                    
            except Exception as e:
                logger.debug(f"[引用消息任务] 检查消息项时出错: {e}")
                continue
        
        logger.info(f"[引用消息任务] 消息扫描完成, 找到 {len(matching_messages)} 个匹配的消息")
        
        # 选择最新的匹配消息
        if matching_messages:
            target_message = matching_messages[0]
            target_message_item = target_message['item']
            is_ai_message = target_message['is_ai_message']
            logger.info(f"[引用消息任务] 选择最新的匹配消息进行引用: '{target_message['name']}', 类型: {'AI消息' if is_ai_message else '用户消息'}")
        else:
            logger.warning(f"[引用消息任务] 未找到任何包含内容 '{message_content}' 的消息.")
            return
            
        # 右键点击目标消息
        message_rect = target_message_item.BoundingRectangle
        chat_window_rect = chat_window_control.BoundingRectangle
        
        message_width = message_rect.width()
        message_height = message_rect.height()
        
        # 根据消息类型选择不同的点击策略
        if is_ai_message:
            # AI消息:点击消息右侧中间偏左位置
            click_x = message_rect.right - int(message_width * 0.3)  # 从右边界往左30%
        else:
            # 用户消息:点击消息左侧中间偏右位置
            click_x = message_rect.left + int(message_width * 0.3)   # 从左边界往右30%
        
        click_y = message_rect.top + message_height // 2  # 垂直居中
        
        # 更严格的边界检查，确保点击位置在消息气泡内
        min_margin = 5  # 最小边距
        if click_x >= message_rect.right - min_margin:
            click_x = message_rect.right - min_margin
        elif click_x <= message_rect.left + min_margin:
            click_x = message_rect.left + min_margin
            
        if click_y >= message_rect.bottom - min_margin:
            click_y = message_rect.bottom - min_margin
        elif click_y <= message_rect.top + min_margin:
            click_y = message_rect.top + min_margin
        
        logger.info(f"[引用消息任务] 消息尺寸: {message_width}x{message_height}")
        logger.info(f"[引用消息任务] 消息范围: ({message_rect.left}, {message_rect.top}) - ({message_rect.right}, {message_rect.bottom})")
        logger.info(f"[引用消息任务] 点击策略: {'AI消息-右侧30%' if is_ai_message else '用户消息-左侧30%'}")
        logger.info(f"[引用消息任务] 最终点击位置: ({click_x}, {click_y})")
        
        # 右键点击消息 - 增加等待和重试机制
        logger.info("[引用消息任务] 执行右键点击...")
        pyautogui.click(x=click_x, y=click_y, button='right', duration=0.3)
        logger.info("[引用消息任务] 右键点击完成,等待菜单弹出...")
        time.sleep(0.8)  # 增加等待时间，确保菜单完全弹出
        
        # A/B计划执行引用操作
        action_completed = False
        quote_actually_successful = False
        
        # 直接使用键盘操作进行引用（删除不稳定的A计划）
        logger.info("[引用消息任务] 使用键盘操作方案: 7次[Down]到达引用选项 -> [Enter]")
        
        # 微信右键菜单:复制(默认选中) -> 需要按7次Down到达引用(第8个)
        for i in range(7):  # 按7次Down键到达引用选项
            pyautogui.press('down')
            time.sleep(0.1)
        
        pyautogui.press('enter')
        time.sleep(0.1)
        action_completed = True
        
        # 验证引用操作是否真正成功
        if action_completed:
            time.sleep(1.5)  # 增加等待时间，确保引用操作完成
            
            # 优化的引用成功检测逻辑
            try:
                # 检查输入框是否存在且可用
                input_box = chat_window_control.EditControl()
                if input_box.Exists(2.0) and input_box.IsEnabled:
                    
                    # 方法1: 尝试获取输入框内容来验证引用
                    input_content = ""
                    try:
                        # 使用多种方法尝试获取输入框内容
                        if hasattr(input_box, 'GetValuePattern') and input_box.GetValuePattern():
                            input_content = input_box.GetValuePattern().Value or ""
                        elif hasattr(input_box, 'Name'):
                            input_content = input_box.Name or ""
                        elif hasattr(input_box, 'GetLegacyIAccessiblePattern'):
                            legacy_pattern = input_box.GetLegacyIAccessiblePattern()
                            if legacy_pattern:
                                input_content = legacy_pattern.Value or ""
                        
                        logger.debug(f"[引用消息任务] 输入框当前内容: '{input_content[:100]}...' (长度: {len(input_content)})")
                        
                    except Exception as content_err:
                        logger.debug(f"[引用消息任务] 获取输入框内容时出错: {content_err}")
                        input_content = ""
                    
                    # 方法2: 检查输入框是否包含引用标记或内容变化
                    has_quote_content = False
                    
                    if input_content:
                        # 检查常见的引用格式标记
                        quote_indicators = [
                            '「' in input_content and '」' in input_content,  # 中文书名号
                            '"' in input_content and '"' in input_content,    # 中文双引号  
                            input_content.strip().startswith('「'),           # 以中文书名号开始
                            input_content.strip().startswith('"'),            # 以中文双引号开始
                            len(input_content.strip()) > 15,                  # 内容较长，可能包含引用
                            '引用' in input_content,                          # 明确包含引用字样
                            message_content[:10] in input_content,            # 包含被引用消息的部分内容
                        ]
                        
                        has_quote_content = any(quote_indicators)
                        logger.debug(f"[引用消息任务] 引用标记检查: {quote_indicators}, 结果: {has_quote_content}")
                    
                    # 方法3: 通过输入框尺寸变化判断（引用后输入框通常会变高）
                    input_box_height = 0
                    try:
                        input_rect = input_box.BoundingRectangle
                        input_box_height = input_rect.height()
                        logger.debug(f"[引用消息任务] 输入框高度: {input_box_height}px")
                        # 如果输入框高度超过正常高度（通常30-40px），可能包含引用内容
                        has_expanded_height = input_box_height > 50
                    except Exception as height_err:
                        logger.debug(f"[引用消息任务] 获取输入框高度时出错: {height_err}")
                        has_expanded_height = False
                    
                    # 综合判断引用是否成功
                    if has_quote_content:
                        quote_actually_successful = True
                        logger.info(f"[引用消息任务] ✅ 引用成功确认！检测到引用内容标记")
                    elif has_expanded_height:
                        quote_actually_successful = True
                        logger.info(f"[引用消息任务] ✅ 引用成功确认！输入框高度增加 ({input_box_height}px)")
                        
                        # 如果只是高度增加但没有内容标记，额外等待确保引用稳定
                        logger.info(f"[引用消息任务] 基于高度判断成功，额外等待确保引用内容稳定...")
                        time.sleep(2.0)  # 额外等待2秒确保引用内容完全加载
                        
                    elif input_content and len(input_content) > 5:
                        quote_actually_successful = True
                        logger.info(f"[引用消息任务] ✅ 引用成功确认！输入框有内容 (长度: {len(input_content)})")
                    else:
                        quote_actually_successful = False
                        logger.warning(f"[引用消息任务] ❌ 引用可能失败！输入框无明显引用标记")
                        logger.debug(f"[引用消息任务] 详细信息: 内容='{input_content}', 高度={input_box_height}px")
                        
                else:
                    logger.warning(f"[引用消息任务] ❌ 输入框不存在或不可用，引用失败")
                    quote_actually_successful = False
                    
            except Exception as e:
                logger.error(f"[引用消息任务] 检测引用结果时发生异常: {e}", exc_info=True)
                # 异常情况下保守判定为失败
                quote_actually_successful = False
        
        # 处理引用结果 - 无论引用是否成功，都执行附加文本添加流程
        logger.info(f"🎉 [引用消息任务] 引用操作完成！消息: '{message_content[:50]}...'")
        if quote_actually_successful:
            logger.info(f"[引用消息任务] 引用操作成功确认")
        else:
            logger.warning(f"[引用消息任务] 引用操作可能失败，但仍继续添加附加文本")
        
        logger.debug(f"[引用消息任务] Debug: additional_text='{additional_text}', type={type(additional_text)}, stripped='{additional_text.strip() if additional_text else 'None'}'")
        
        # 如果有额外文本需要添加（无论引用是否成功都执行）
        if additional_text and additional_text.strip():
            logger.info(f"[引用消息任务] 正在添加额外文本: '{additional_text[:50]}...'")
            
            # 点击输入框确保其被选中和激活
            logger.info(f"[引用消息任务] 点击输入框确保其被选中...")
            try:
                input_box = chat_window_control.EditControl()
                if input_box.Exists(2.0):
                    # 获取输入框的位置并点击
                    input_rect = input_box.BoundingRectangle
                    input_center_x = input_rect.left + input_rect.width() // 2
                    input_center_y = input_rect.top + input_rect.height() // 2
                    
                    logger.debug(f"[引用消息任务] 输入框位置: ({input_center_x}, {input_center_y})")
                    pyautogui.click(x=input_center_x, y=input_center_y)
                    time.sleep(0.3)  # 等待点击生效
                    logger.info(f"[引用消息任务] ✅ 输入框已点击选中")
                    
                    # 将光标移到末尾，确保在最后位置输入
                    pyautogui.press('end')
                    time.sleep(0.2)
                else:
                    logger.warning(f"[引用消息任务] ⚠️ 未找到输入框")
            except Exception as click_err:
                logger.warning(f"[引用消息任务] 点击输入框失败: {click_err}")
            
            # 添加附加文本
            try:
                logger.debug(f"[引用消息任务] 使用剪贴板粘贴附加文本")
                pyperclip.copy(additional_text)
                time.sleep(0.3)
                pyautogui.hotkey('ctrl', 'v')
                time.sleep(0.5)
                logger.info(f"[引用消息任务] ✅ 附加文本已添加")
            except Exception as paste_err:
                logger.warning(f"[引用消息任务] 粘贴失败，尝试逐字符输入: {paste_err}")
                try:
                    for char in additional_text:
                        if ord(char) > 127:
                            pyperclip.copy(char)
                            time.sleep(0.05)
                            pyautogui.hotkey('ctrl', 'v')
                        else:
                            auto.SendKeys(char, interval=0.03)
                    logger.info(f"[引用消息任务] ✅ 附加文本已通过逐字符方式添加")
                except Exception as type_err:
                    logger.error(f"[引用消息任务] 逐字符输入也失败: {type_err}")
            
            # 发送消息
            logger.info(f"[引用消息任务] 准备发送完整消息...")
            time.sleep(0.5)
            pyautogui.press('enter')
            logger.info(f"[引用消息任务] ✅ 消息已发送")
            
        else:
            # 没有附加文本时，如果引用成功就直接发送引用
            if quote_actually_successful:
                logger.info(f"[引用消息任务] 没有附加文本，直接发送引用消息")
                time.sleep(0.3)
                pyautogui.press('enter')
                logger.info(f"[引用消息任务] ✅ 引用消息已发送")
            else:
                logger.warning(f"[引用消息任务] 引用失败且无附加文本，跳过发送")
        
        # 引用操作完成后等待一段时间, 确保微信界面状态稳定, 避免影响后续消息发送
        time.sleep(1.5)
        return True
    except Exception as e:
        logger.error(f"[引用消息任务] 执行时发生未知严重错误", exc_info=True)
        try:
            # 如果引用过程中出错但有附加文本, 也要尝试发送
            if additional_text and additional_text.strip():
                logger.info(f"[引用消息任务] 异常情况下发送备用消息: '{additional_text[:50]}...'")
                wx.SendMsg(msg=additional_text, who=chat_name)
            else:
                custom_message = get_user_error_message(chat_name, 'operation_failure')
                error_msg = custom_message if custom_message else "抱歉, 执行引用操作时内部发生严重错误, 请检查后台日志."
                wx.SendMsg(msg=error_msg, who=chat_name)
        except Exception: 
            pass
        return False
    finally:
        uia.uiautomation.SetGlobalSearchTimeout(DEFAULT_UI_AUTOMATION_TIMEOUT)
        if chat_window_control and chat_window_control.Exists(0.1):
            chat_window_control.SetTopmost(False)
        
        logger.debug(f"[引用消息任务] 任务结束, 资源已释放, 消息发送状态已恢复, 全局超时已恢复为 {DEFAULT_UI_AUTOMATION_TIMEOUT} 秒.")

# ==================== 引用消息功能区 结束 ====================

# ==================== 管理命令处理功能区 开始 ====================

def handle_admin_commands(command, user_id, sender):
    """
    处理管理命令
    
    Args:
        command (str): 用户输入的完整命令
        user_id (str): 用户ID
        sender (str): 发送者名称
    
    Returns:
        bool: 如果命令被处理则返回True, 否则返回False
    """
    command = command.strip().lower()
    
    # /reboot - 强制重启bot (支持 /reboot 和 /rebot 两种写法)
    if command in ['/reboot', '/rebot']:
        logger.warning(f"用户 {user_id} 执行了强制重启命令")
        try:
            wx.SendMsg(msg="收到重启指令, 正在重启机器人...", who=user_id)
            time.sleep(1)  # 给消息发送一些时间
            
            # 执行重启前的清理操作
            logger.info("用户命令重启前:保存聊天上下文...")
            with queue_lock:
                save_chat_contexts()
            
            # 保存用户计时器状态
            if ENABLE_AUTO_MESSAGE:
                logger.info("用户命令重启前:保存用户计时器状态...")
                save_user_timers()
            
            if ENABLE_REMINDERS:
                logger.info("用户命令重启前:保存提醒列表...")
                with recurring_reminder_lock:
                    save_recurring_reminders()
            
            # 关闭异步HTTP日志处理器
            if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
                logger.info("用户命令重启前:关闭异步HTTP日志处理器...")
                async_http_handler.close()
            
            logger.info("用户命令重启前:执行最终临时文件清理...")
            clean_up_temp_files()
            
            logger.info("正在执行用户命令重启...")
            logger.info(f"重启参数 - sys.executable: {sys.executable}")
            logger.info(f"重启参数 - sys.argv: {sys.argv}")
            
            # 在Windows环境下使用正确的重启方式
            import subprocess
            try:
                # 使用subprocess启动新进程, 然后退出当前进程
                subprocess.Popen([sys.executable] + sys.argv)
                logger.info("新进程已启动, 准备退出当前进程...")
                
                # 给新进程一些启动时间
                time.sleep(2)
                
                # 退出当前进程
                os._exit(0)
            except Exception as exec_error:
                logger.error(f"使用subprocess重启失败, 尝试os.execv方法: {exec_error}")
                # 备选方案:使用 os.execv
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception as e:
            logger.error(f"执行用户命令重启操作时发生错误: {e}", exc_info=True)
            wx.SendMsg(msg="重启失败, 请检查日志", who=user_id)
        return True
    
    # /del - 删除当前对话的上下文
    elif command == '/del':
        logger.info(f"用户 {user_id} 执行了删除对话上下文命令")
        try:
            with queue_lock:
                if user_id in chat_contexts:
                    # 获取用户的角色名称
                    prompt_name = prompt_mapping.get(user_id, user_id)
                    if prompt_name in chat_contexts[user_id]:
                        del chat_contexts[user_id][prompt_name]
                        logger.info(f"已删除用户 {user_id} 的角色 {prompt_name} 对话上下文")
                        if not chat_contexts[user_id]:  # 如果用户没有其他角色上下文, 删除整个用户条目
                            del chat_contexts[user_id]
                    save_chat_contexts()
                    wx.SendMsg(msg="✅ 对话上下文已清除", who=user_id)
                else:
                    wx.SendMsg(msg="ℹ️ 当前没有对话上下文需要清除", who=user_id)
        except Exception as e:
            logger.error(f"删除对话上下文时发生错误: {e}", exc_info=True)
            wx.SendMsg(msg="❌ 删除对话上下文失败", who=user_id)
        return True
    
    # /memo - 核心记忆系统总结命令（仅核心记忆和核心备忘录）
    elif command == '/memo':
        logger.info(f"用户 {user_id} 执行了核心记忆总结命令")
        try:
            role_name = prompt_mapping.get(user_id, user_id)
            
            # 🔧 修复：优先检查专用的核心记忆日志文件
            core_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_core_log.txt')
            main_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
            
            # 优先使用专用核心记忆日志，如果不存在则使用主日志
            log_file = core_log_file if os.path.exists(core_log_file) else main_log_file
            
            if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
                wx.SendMsg(msg="ℹ️ 当前没有对话记录可以总结", who=user_id)
                return True
            
            # 读取日志条数 - 手动命令时更宽松的检查
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
                logs = [line.strip() for line in f if line.strip()]
            
            # 手动调用时只需要至少1条消息即可触发
            if len(logs) < 1:
                wx.SendMsg(msg="ℹ️ 当前没有对话记录可以总结", who=user_id)
                return True
            
            # 检查是否已有总结任务在进行
            with active_summary_tasks_lock:
                if user_id in active_summary_tasks:
                    wx.SendMsg(msg="⚠️ 记忆总结任务已在进行中, 请稍后再试", who=user_id)
                    return True
                active_summary_tasks.add(user_id)
            
            wx.SendMsg(msg=f"🧠 正在生成核心记忆总结（共{len(logs)}条记录）, 请稍候...", who=user_id)
            
            # 启动核心记忆总结线程
            threading.Thread(
                target=manual_core_memory_summary_threaded, 
                args=(user_id, role_name)
            ).start()
            
        except Exception as e:
            logger.error(f"执行 /memo 命令时出错: {e}", exc_info=True)
            wx.SendMsg(msg="❌ 核心记忆总结命令执行失败", who=user_id)
            with active_summary_tasks_lock:
                if user_id in active_summary_tasks:
                    active_summary_tasks.remove(user_id)
        return True

    # /diary - 日记系统总结命令（仅日记和碎碎念备忘录）
    elif command == '/diary':
        logger.info(f"用户 {user_id} 执行了日记总结命令")
        try:
            role_name = prompt_mapping.get(user_id, user_id)
            
            # 🔧 修复：优先检查专用的日记日志文件
            diary_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_diary_log.txt')
            main_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
            
            # 优先使用专用日记日志，如果不存在则使用主日志
            log_file = diary_log_file if os.path.exists(diary_log_file) else main_log_file
            
            if not os.path.exists(log_file) or os.path.getsize(log_file) == 0:
                wx.SendMsg(msg="ℹ️ 当前没有对话记录可以总结", who=user_id)
                return True
            
            # 读取日志条数 - 手动命令时更宽松的检查
            with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:  # ✅ 添加 errors='ignore'
                logs = [line.strip() for line in f if line.strip()]
            
            # 手动调用时只需要至少1条消息即可触发
            if len(logs) < 1:
                wx.SendMsg(msg="ℹ️ 当前没有对话记录可以总结", who=user_id)
                return True
            
            # 检查是否已有总结任务在进行
            with active_summary_tasks_lock:
                if user_id in active_summary_tasks:
                    wx.SendMsg(msg="⚠️ 记忆总结任务已在进行中, 请稍后再试", who=user_id)
                    return True
                active_summary_tasks.add(user_id)
            
            wx.SendMsg(msg=f"📖 正在生成日记总结（共{len(logs)}条记录）, 请稍候...", who=user_id)
            
            # 启动日记总结线程
            threading.Thread(
                target=manual_diary_summary_threaded, 
                args=(user_id, role_name)
            ).start()
            
        except Exception as e:
            logger.error(f"执行 /diary 命令时出错: {e}", exc_info=True)
            wx.SendMsg(msg="❌ 日记总结命令执行失败", who=user_id)
            with active_summary_tasks_lock:
                if user_id in active_summary_tasks:
                    active_summary_tasks.remove(user_id)
        return True
    
    # /clear[x] - 删除最近x轮chat_contexts
    elif command.startswith('/clear'):
        try:
            # 解析数字, 支持 /clear[5] 或 /clear5 格式
            import re
            match = re.search(r'/clear\[?(\d+)\]?', command)
            if match:
                rounds_to_clear = int(match.group(1))
                if rounds_to_clear <= 0:
                    wx.SendMsg(msg="❌ 清除轮数必须大于0", who=user_id)
                    return True
                
                logger.info(f"用户 {user_id} 执行了清除最近 {rounds_to_clear} 轮对话命令")
                
                with queue_lock:
                    prompt_name = prompt_mapping.get(user_id, user_id)
                    if user_id not in chat_contexts or prompt_name not in chat_contexts[user_id]:
                        wx.SendMsg(msg="ℹ️ 当前没有对话上下文可以清除", who=user_id)
                        return True
                    
                    current_context = chat_contexts[user_id][prompt_name]
                    original_length = len(current_context)
                    
                    if original_length == 0:
                        wx.SendMsg(msg="ℹ️ 当前对话上下文为空", who=user_id)
                        return True
                    
                    # 计算要删除的消息数(每轮对话包含用户消息和AI回复, 共2条消息)
                    messages_to_remove = min(rounds_to_clear * 2, original_length)
                    
                    # 从末尾删除指定数量的消息
                    chat_contexts[user_id][prompt_name] = current_context[:-messages_to_remove]
                    
                    save_chat_contexts()
                    
                    actual_rounds_cleared = messages_to_remove // 2
                    remaining_messages = len(chat_contexts[user_id][prompt_name])
                    
                    wx.SendMsg(msg=f"✅ 已清除最近 {actual_rounds_cleared} 轮对话({messages_to_remove} 条消息), 剩余 {remaining_messages} 条消息", who=user_id)
                    logger.info(f"用户 {user_id} 清除了 {actual_rounds_cleared} 轮对话")
                
            else:
                wx.SendMsg(msg="❌ 命令格式错误, 请使用 /clear[数字] 格式, 如:/clear[5]", who=user_id)
                
        except ValueError:
            wx.SendMsg(msg="❌ 请输入有效的数字, 如:/clear[5]", who=user_id)
        except Exception as e:
            logger.error(f"处理清除对话命令时发生错误: {e}", exc_info=True)
            wx.SendMsg(msg="❌ 清除对话失败", who=user_id)
        return True
      
    # /开启遥控 - 开启玩具遥控模式
    elif command in ['/开启遥控', '/starttoy']:
        reply_text = enable_remote_control()
        wx.SendMsg(reply_text, user_id)
        return True

    # /关闭遥控 - 关闭玩具遥控模式
    elif command in ['/关闭遥控', '/stoptoy']:
        reply_text = disable_remote_control()
        wx.SendMsg(reply_text, user_id)
        return True
    
    # 未识别的命令
    return False


def manual_dual_memory_summary_threaded(user_id, role_name):
    """
    手动双重记忆总结的线程化版本，用于处理新的双重记忆系统 /memo 命令
    """
    global active_summary_tasks
    try:
        # 执行日记总结
        diary_success = generate_daily_summary(user_id, datetime.now().strftime('%Y-%m-%d'))
        
        # 执行核心记忆更新 - 手动调用时强制更新，不考虑记忆轮数限制
        core_success = generate_core_memory_update(user_id, force_update=True)
        
        if diary_success and core_success:
            wx.SendMsg(msg="✅ 双重记忆总结完成！已更新日记、备忘录和核心记忆", who=user_id)
            logger.info(f"用户 {user_id} 的双重记忆总结任务完成")
        elif diary_success:
            wx.SendMsg(msg="✅ 日记总结完成！核心记忆更新失败", who=user_id)
            logger.warning(f"用户 {user_id} 的核心记忆更新失败")
        elif core_success:
            wx.SendMsg(msg="✅ 核心记忆更新完成！日记总结失败", who=user_id)
            logger.warning(f"用户 {user_id} 的日记总结失败")
        else:
            # 获取用户自定义错误提示词
            custom_message = get_user_error_message(user_id, 'double_memory_failure')
            error_msg = custom_message if custom_message else "❌ 双重记忆总结失败，请稍后重试"
            wx.SendMsg(msg=error_msg, who=user_id)
            logger.warning(f"用户 {user_id} 的双重记忆总结任务失败")
            
    except Exception as e:
        logger.error(f"手动双重记忆总结线程为用户 {user_id} 执行时出错: {e}", exc_info=True)
        wx.SendMsg(msg="❌ 双重记忆总结过程中出现错误", who=user_id)
    finally:
        # 任务完成, 从活动任务集合中移除用户
        with active_summary_tasks_lock:
            if user_id in active_summary_tasks:
                active_summary_tasks.remove(user_id)
                logger.info(f"用户 {user_id} 的双重记忆总结任务锁已释放")

def manual_core_memory_summary_threaded(user_id, role_name):
    """
    手动核心记忆总结的线程化版本，用于处理新的 /memo 命令（仅核心记忆和核心备忘录）
    """
    global active_summary_tasks
    try:
        # 仅执行核心记忆更新 - 手动调用时强制更新，不考虑记忆轮数限制
        core_success = generate_core_memory_update(user_id, force_update=True)
        
        if core_success:
            wx.SendMsg(msg="✅ 核心记忆总结完成！已更新核心记忆和核心备忘录", who=user_id)
            logger.info(f"用户 {user_id} 的核心记忆总结任务完成")
        else:
            # 获取用户自定义错误提示词
            custom_message = get_user_error_message(user_id, 'core_memory_failure')
            error_msg = custom_message if custom_message else "❌ 核心记忆总结失败，请稍后重试"
            wx.SendMsg(msg=error_msg, who=user_id)
            logger.warning(f"用户 {user_id} 的核心记忆总结任务失败")
            
    except Exception as e:
        logger.error(f"手动核心记忆总结线程为用户 {user_id} 执行时出错: {e}", exc_info=True)
        wx.SendMsg(msg="❌ 核心记忆总结过程中出现错误", who=user_id)
    finally:
        # 任务完成, 从活动任务集合中移除用户
        with active_summary_tasks_lock:
            if user_id in active_summary_tasks:
                active_summary_tasks.remove(user_id)
                logger.info(f"用户 {user_id} 的核心记忆总结任务锁已释放")

def manual_diary_summary_threaded(user_id, role_name):
    """
    手动日记总结的线程化版本，用于处理新的 /diary 命令（仅日记和碎碎念备忘录）
    """
    global active_summary_tasks
    try:
        # 仅执行日记总结
        diary_success = generate_daily_summary(user_id, datetime.now().strftime('%Y-%m-%d'))
        
        if diary_success:
            wx.SendMsg(msg="✅ 日记总结完成！已更新日记和碎碎念备忘录", who=user_id)
            logger.info(f"用户 {user_id} 的日记总结任务完成")
        else:
            # 获取用户自定义错误提示词
            custom_message = get_user_error_message(user_id, 'diary_failure')
            error_msg = custom_message if custom_message else "❌ 日记总结失败，请稍后重试"
            wx.SendMsg(msg=error_msg, who=user_id)
            logger.warning(f"用户 {user_id} 的日记总结任务失败")
            
    except Exception as e:
        logger.error(f"手动日记总结线程为用户 {user_id} 执行时出错: {e}", exc_info=True)
        wx.SendMsg(msg="❌ 日记总结过程中出现错误", who=user_id)
    finally:
        # 任务完成, 从活动任务集合中移除用户
        with active_summary_tasks_lock:
            if user_id in active_summary_tasks:
                active_summary_tasks.remove(user_id)
                logger.info(f"用户 {user_id} 的日记总结任务锁已释放")

# ==================== 管理命令处理功能区 结束 ====================

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
        
        # 读取图片内容并编码
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

def fetch_and_extract_text(url: str) -> Optional[str]:
    """
    获取给定 URL 的网页内容并提取主要文本. 

    Args:
        url (str): 要抓取的网页链接.

    Returns:
        Optional[str]: 提取并清理后的网页文本内容(限制了最大长度), 如果失败则返回 None.
    """
    try:
        # 基本 URL 格式验证 (非常基础)
        parsed_url = urlparse(url)
        if not all([parsed_url.scheme, parsed_url.netloc]):
             logger.warning(f"无效的URL格式, 跳过抓取: {url}")
             return None

        headers = {'User-Agent': REQUESTS_USER_AGENT}
        logger.info(f"开始抓取链接内容: {url}")
        response = requests.get(url, headers=headers, timeout=REQUESTS_TIMEOUT, allow_redirects=True)
        response.raise_for_status()  # 检查HTTP请求是否成功 (状态码 2xx)

        # 检查内容类型, 避免处理非HTML内容(如图片, PDF等)
        content_type = response.headers.get('Content-Type', '').lower()
        if 'html' not in content_type:
            logger.warning(f"链接内容类型非HTML ({content_type}), 跳过文本提取: {url}")
            return None

        # 使用BeautifulSoup解析HTML
        # 指定 lxml 解析器以获得更好的性能和兼容性
        soup = BeautifulSoup(response.content, 'lxml') # 使用 response.content 获取字节流, 让BS自动处理编码

        # --- 文本提取策略 ---
        # 尝试查找主要内容区域 (这部分可能需要根据常见网站结构调整优化)
        main_content_tags = ['article', 'main', '.main-content', '#content', '.post-content'] # 示例选择器
        main_text = ""
        for tag_selector in main_content_tags:
            element = soup.select_one(tag_selector)
            if element:
                main_text = element.get_text(separator='\n', strip=True)
                break # 找到一个就停止

        # 如果没有找到特定的主要内容区域, 则获取整个 body 的文本作为备选
        body_element = soup.find('body')
        if not main_text and body_element:
            main_text = body_element.get_text(separator='\n', strip=True)
        elif not main_text: # 如果连 body 都没有, 则使用整个 soup
             main_text = soup.get_text(separator='\n', strip=True)

        # 清理文本:移除过多空行
        lines = [line for line in main_text.splitlines() if line.strip()]
        cleaned_text = '\n'.join(lines)

        # 限制内容长度
        if len(cleaned_text) > MAX_WEB_CONTENT_LENGTH:
            cleaned_text = cleaned_text[:MAX_WEB_CONTENT_LENGTH] + "..." # 截断并添加省略号
            logger.info(f"网页内容已提取, 并截断至 {MAX_WEB_CONTENT_LENGTH} 字符.")
        elif cleaned_text:
            logger.info(f"成功提取网页文本内容 (长度 {len(cleaned_text)}).")
        else:
            logger.warning(f"未能从链接 {url} 提取到有效文本内容.")
            return None # 如果提取后为空, 也视为失败

        return cleaned_text

    except requests.exceptions.Timeout:
        logger.error(f"抓取链接超时 ({REQUESTS_TIMEOUT}秒): {url}")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"抓取链接时发生网络错误: {url}, 错误: {e}")
        return None
    except Exception as e:
        # 捕获其他可能的错误, 例如 BS 解析错误
        logger.error(f"处理链接时发生未知错误: {url}, 错误: {e}", exc_info=True)
        return None

def safe_read_file(file_path, encoding='utf-8'):
    """安全读取文件，处理编码问题"""
    try:
        with open(file_path, 'r', encoding=encoding) as f:
            return f.read()
    except UnicodeDecodeError as e:
        logger.warning(f"文件 {file_path} UTF-8 解码失败: {e}，尝试其他编码")
        # 尝试常见的编码
        encodings_to_try = ['gbk', 'gb2312', 'latin-1', 'cp1252']
        for enc in encodings_to_try:
            try:
                with open(file_path, 'r', encoding=enc) as f:
                    content = f.read()
                    logger.info(f"成功使用 {enc} 编码读取文件: {file_path}")
                    return content
            except (UnicodeDecodeError, LookupError):
                continue
        
        # 如果所有编码都失败，使用二进制模式并替换错误字符
        logger.warning(f"所有编码尝试失败，使用二进制模式读取: {file_path}")
        with open(file_path, 'rb') as f:
            content = f.read()
            return content.decode('utf-8', errors='replace')
    except Exception as e:
        logger.error(f"读取文件失败: {file_path}, 错误: {e}")
        raise

def safe_write_file(file_path, content, encoding='utf-8'):
    """安全写入文件，处理编码问题"""
    try:
        # 确保内容可以编码为指定编码
        if isinstance(content, str):
            content = content.encode(encoding, errors='replace').decode(encoding)
        elif isinstance(content, bytes):
            content = content.decode('utf-8', errors='replace')
            
        with open(file_path, 'w', encoding=encoding) as f:
            f.write(content)
    except Exception as e:
        logger.error(f"写入文件失败: {file_path}, 错误: {e}")
        raise

# 辅助函数:将用户消息记录到记忆日志 (如果启用)
def log_user_message_to_memory(username, original_content):
    """将用户的原始消息记录到记忆日志文件，并检查是否需要触发双重记忆总结。"""
    if ENABLE_MEMORY:
        try:
            prompt_name = prompt_mapping.get(username, username)
            log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{username}_{prompt_name}_log.txt')
            
            # 安全处理消息内容，确保能够正确编码为UTF-8
            try:
                if isinstance(original_content, bytes):
                    # 如果是字节数据，尝试解码为字符串
                    cleaned_content = original_content.decode('utf-8', errors='replace').replace('\n', ' ')
                else:
                    # 如果是字符串，先确保其可以编码为UTF-8
                    cleaned_content = str(original_content).encode('utf-8', errors='replace').decode('utf-8').replace('\n', ' ')
            except Exception as e:
                # 如果仍然失败，使用安全的fallback
                logger.warning(f"处理消息内容编码时出错: {e}，使用fallback处理")
                cleaned_content = repr(original_content).replace('\n', ' ')
                
            log_entry = f"{datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')} | [{username}] {cleaned_content}\n"
            
            os.makedirs(os.path.dirname(log_file), exist_ok=True)
            
            # 使用安全写入函数
            try:
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(log_entry)
            except UnicodeEncodeError as e:
                logger.warning(f"UTF-8编码写入失败: {e}，尝试安全模式")
                # 确保log_entry可以安全编码
                safe_log_entry = log_entry.encode('utf-8', errors='replace').decode('utf-8')
                with open(log_file, 'a', encoding='utf-8') as f:
                    f.write(safe_log_entry)
            
            # 同时写入到专用的日记和核心记忆日志文件
            diary_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{username}_{prompt_name}_diary_log.txt')
            core_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{username}_{prompt_name}_core_log.txt')
            
            try:
                # 使用相同的安全写入方式
                try:
                    with open(diary_log_file, 'a', encoding='utf-8') as f:
                        f.write(log_entry)
                    with open(core_log_file, 'a', encoding='utf-8') as f:
                        f.write(log_entry)
                except UnicodeEncodeError as e:
                    logger.warning(f"专用日志文件UTF-8编码写入失败: {e}，使用安全模式")
                    safe_log_entry = log_entry.encode('utf-8', errors='replace').decode('utf-8')
                    with open(diary_log_file, 'a', encoding='utf-8') as f:
                        f.write(safe_log_entry)
                    with open(core_log_file, 'a', encoding='utf-8') as f:
                        f.write(safe_log_entry)
            except Exception as e:
                logger.warning(f"写入专用日志文件失败: {e}")
                
            # === 双重记忆系统自动触发检查 ===
            # 注意：核心记忆已改为 AI 主动标记触发（[UPDATE_CORE] 标签），
            # 不再需要按轮数自动触发。保留 /memo 手动命令作为兜底。
            # 以下旧代码已禁用：
            # if check_core_memory_update_needed(username):
            #     ...
                    
                    
        except Exception as write_err:
             logger.error(f"写入用户 {username} 的记忆日志失败: {write_err}")

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
    online_info = None

    # [核心] 处理用户消息并生成回复

    try:
        if ENABLE_ONLINE_API:
            search_content = needs_online_search(merged_message, user_id)
            if search_content:
                logger.info(f"尝试为用户 {user_id} 执行在线搜索...")
                merged_message = f"用户原始信息:\n{merged_message}\n\n需要进行联网搜索的信息:\n{search_content}"
                online_info = get_online_model_response(merged_message, user_id)

                if online_info:
                    logger.info(f"成功获取在线信息, 为用户 {user_id} 准备最终回复...")
                    final_prompt = f"""
用户的原始问题是:
"{merged_message}"

根据以下联网搜索到的参考信息:
---
{online_info}
---

请结合你的角色设定, 以自然的方式回答用户的原始问题.请直接给出回答内容, 不要提及你是联网搜索的.
"""
                    reply = get_deepseek_response(final_prompt, user_id, store_context=True)
                else:
                    logger.warning(f"在线搜索未能获取有效信息, 用户: {user_id}.将按常规流程处理.")
                    pass

        if reply is None:
            logger.info(f"为用户 {user_id} 执行常规回复(无联网信息).")
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

def send_emoji(tag: str) -> Optional[str]:
    """根据标签名发送对应表情包"""
    if not tag:
        return None
        
    emoji_folder = os.path.join(EMOJI_DIR, tag)
    
    try:
        # 获取文件夹中的所有表情文件
        emoji_files = [
            f for f in os.listdir(emoji_folder)
            if f.lower().endswith(('.png', '.jpg', '.jpeg', '.gif'))
        ]
        
        if not emoji_files:
            logger.warning(f"表情文件夹 {tag} 为空或不存在")
            return None

        # 随机选择并返回表情路径
        selected_emoji = random.choice(emoji_files)
        return os.path.join(emoji_folder, selected_emoji)

    except FileNotFoundError:
        logger.error(f"表情文件夹不存在: {emoji_folder}")
    except Exception as e:
        logger.error(f"表情发送失败: {str(e)}")
    
    return None


def clean_up_temp_files ():
    if os.path.isdir("wxautox文件下载"):
        try:
            shutil.rmtree("wxautox文件下载")
        except Exception as e:
            logger.error(f"删除目录 wxautox文件下载 失败: {str(e)}")
            return
        logger.info(f"目录 wxautox文件下载 已成功删除")
    else:
        logger.info(f"目录 wxautox文件下载 不存在, 无需删除")

def append_to_memory_section(user_id, role_name, summary):
    """
    将日记内容追加到用户的.md文件中
    """
    try:
        prompts_dir = os.path.join(root_dir, 'prompts')
        user_file_path = os.path.join(prompts_dir, f'{role_name}.md')

        if not os.path.exists(user_file_path):
            logger.error(f"无法找到用户 {user_id} 的角色设定文件: {user_file_path}")
            return
            
        with open(user_file_path, 'r+', encoding='utf-8') as file:
            content = file.read()
            
            # 清理summary, 移除所有可能的标签
            cleaned_summary = re.sub(r'</?thinking>', '', summary).strip()
            
            # 准备一个完整的, 格式绝对正确的日记条目
            current_time_str = datetime.now().strftime("%Y-%m-%d %A %H:%M")
            diary_entry = f"""## 日记 [{current_time_str}]
**摘要**: {cleaned_summary}"""

            # 移动到文件末尾准备写入
            file.seek(0, 2)
            
            # 在写入前, 先判断文件末尾是否已经有内容.
            # 如果有内容, 并且末尾不是换行符, 就先写入两个换行符来分隔.
            if content.strip() and not content.endswith('\n'):
                file.write(f"\n\n{diary_entry}")
            else:
                # 如果文件是空的, 或者末尾已经是换行符, 就直接追加
                file.write(f"{diary_entry}")
            
            logger.info(f"已将新日记追加到 {role_name}.md 的末尾.")

    except Exception as e:
        logger.error(f"为用户 {user_id} ({role_name}) 追加日记到 .md 文件失败: {e}", exc_info=True)

def is_quiet_time():
    current_time = datetime.now().time()
    if quiet_time_start is None or quiet_time_end is None:
        return False
    if quiet_time_start <= quiet_time_end:
        return quiet_time_start <= current_time <= quiet_time_end
    else:
        return current_time >= quiet_time_start or current_time <= quiet_time_end

# ===============================
# 新双重记忆系统核心函数
# ===============================

def get_user_memory_key(user_id):
    """获取用户记忆键值，格式：用户ID_角色名"""
    role_name = prompt_mapping.get(user_id, user_id)
    role_name_without_ext = os.path.splitext(role_name)[0]
    return f"{user_id}_{role_name_without_ext}"

def get_user_error_message(username, error_type):
    """获取用户自定义的错误提示词"""
    try:
        error_dir = 'User_Error_Messages'
        if not os.path.exists(error_dir):
            return None
        
        # 使用memory_key格式：用户ID_角色名
        memory_key = get_user_memory_key(username)
        error_file = os.path.join(error_dir, f'{memory_key}_{error_type}_error.txt')
        if os.path.exists(error_file):
            with open(error_file, 'r', encoding='utf-8') as f:
                return f.read().strip()
        return None
    except Exception as e:
        logger.error(f"获取用户 {username} 的 {error_type} 错误提示词失败: {str(e)}")
        return None

def get_user_memory_prompt(username, prompt_type):
    """获取用户的记忆处理提示词"""
    try:
        prompt_dir = 'User_Memory_Prompts'
        
        # 首先尝试获取用户特定的提示词
        prompt_file = os.path.join(prompt_dir, f'{username}_{prompt_type}_prompt.txt')
        
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt_content = f.read()
                logger.info(f"使用用户特定的{prompt_type}提示词 ({username}_{prompt_type}_prompt.txt): {prompt_content[:100]}{'...' if len(prompt_content) > 100 else ''}")
                return prompt_content
        
        # 如果没有用户特定的提示词，尝试获取全局提示词
        global_prompt_file = os.path.join(prompt_dir, f'global_{prompt_type}_prompt.txt')
        if os.path.exists(global_prompt_file):
            with open(global_prompt_file, 'r', encoding='utf-8') as f:
                prompt_content = f.read()
                logger.info(f"使用全局{prompt_type}提示词 (global_{prompt_type}_prompt.txt): {prompt_content[:100]}{'...' if len(prompt_content) > 100 else ''}")
                return prompt_content
        
        # 如果都没有，返回默认提示词
        default_prompts = {
            'core_memory': '请以客观的视角，用中文总结{role_name}与{user_id}的对话。通过分析"原始核心记忆"和"最近的对话"，来扩充或修改现有的核心记忆。请严格遵守规范：1.保留原始核心记忆，除非你认为对其进行简化后不影响信息量或某些原始核心记忆需要更新（例如：用户改变了长期偏好或自我认知，则更新原始核心记忆中相关的部分）。2.将生成内容添加在原始核心记忆（或者被你进行过调整的原始核心记忆）的后面。3.若你认为当前上下文并不需要生成新的核心记忆，保留原始核心记忆即可。4.若没有信息表明原始核心记忆需要修改/删除，请务必保留原始核心记忆，并紧接其后面生成新的记忆内容。生成内容要求：1.严格控制字数在200-300字内，尽可能精简，prompt中已经有的内容无需加入核心记忆，每次合并整理相似的条目，避免重复。2.记录关系中的重大里程碑事件如纪念日, 两人之间的长期约定；要求简洁概括, 不自行编造关于用户的未提及的事件, 不得编造虚假内容，保留对未来对话至关重要的、反映用户长期特质与关系本质的信息。3.按优先级提取：用户长期身份与核心价值观 > 用户稳定的偏好/禁忌 > 重要的共同历史里程碑 > 从互动中提炼出的长期行为模式与洞察。4.使用第三视角撰写，保持客观地记录对话记忆。5.使用极简句式，省略不必要的修饰词，禁止使用颜文字和括号描述动作。6.核心记忆应记录事件的本质与影响，而非具体日期等临时信息；日期类信息由备忘录负责，核心记忆仅保留其象征意义。7.信息应当是从你的角度了解到的用户信息。8.格式为简洁的要点，可用分号分隔不同信息。',
            'diary': f'以{role_name}的第一人称视角，用中文撰写一篇日记。日记需基于与{user_id}的对话内容，进行情感化、叙事化的总结。日记撰写要求：1.严格使用第一人称“我”进行叙述。采用私人日记的口吻，语言需自然、亲切并符合{role_name}人设与{user_id}。禁止使用客观汇报或列表式文体。2.需涵盖今日互动中的关键事件与值得回顾的日常琐事。需将事件整合为一个连贯的、有故事性的叙事，并阐述当时的想法与感受。对关键事件进行详细描述；对日常琐事进行概括性提炼，捕捉其带来的细微情绪或趣味性。3.日记必须包含：陈述今天的整体情绪状态及原因、描述今日交流中留下印象的内容，包括重要的对话和有趣的琐事、基于今日的互动，总结今日或表达对明天的期望或计划。4.全文控制在300至500字之间。5.输出格式： 直接以日期开头，并开始书写日记正文。无需任何额外标题或说明。',
            'memo_fragments': f'请从{{role_name}}的第一人称视角，用中文总结与{{user_id}}的当前对话上下文，来更新碎碎念备忘录。\n请严格遵守规范：\n1.保留备忘录中所有仍未过期或未完成的信息。\n2.仅对过时信息进行删除（如约定已完成、临时状态已改变），或用新信息覆盖旧信息。所有修改必须是基于用户明确提及的内容。\n3.将生成的新内容添加在现有备忘录（或经你调整后的备忘录）的后面。\n4.若最新对话不包含需要备忘录记录的信息，则保留现有备忘录不变。\n5.备忘录内容具有时效性，应定期清理已解决或过时的条目，确保简洁性。\n生成内容要求：\n1.必须从{{role_name}}的第一人称主观视角撰写。使用随意、口语化的日记口吻，可以包含语气词、颜文字、emoji、吐槽和内心戏。\n2. 每条记录必须包含"客观事实"和"主观评论"两部分。客观事实： 简要记录事件或用户状态。主观评论： 在事实后，写出你的吐槽、感受或联想。使用"编号. 内容"的格式进行罗列，每条记录包括主观评论在30字以内。\n3.记录短期、临时的对话内容、用户状态、让你有感触或想吐槽的点。在记录事实之外还要捕捉情绪和趣味性。\n4.避免官方用语，展现{{role_name}}的性格。可以是幽默、可爱、无奈、感慨等任何符合角色设定的风格。\n5.输出示例：1.宝宝又在深夜放毒，说想吃烧烤了，可恶，我也好想吃…\\n2.宝宝夸我今天出的主意棒，我果然还是值得依赖的吧。\\n3.宝宝中午纠结了半小时吃什么，最后居然选了泡面，哎，她高兴就好。\\n4.宝宝终于完成了她的作业，这下可以更多地找她说话了。\n6.输出格式：仅输出更新后的备忘录内容本身（即编号列表），无需任何额外解释。',
            'core_memo': f'请以绝对客观的视角，用中文总结{{role_name}}与{{user_id}}的当前对话上下文。\n通过分析"现有备忘录"和"最新对话"，来更新现有的备忘录内容。\n请严格遵守规范：\n1.保留现有备忘录中所有仍未过期或未完成的信息。\n2.仅对过时信息进行删除（如约定已完成、临时状态已改变），或用新信息覆盖旧信息。所有修改必须是基于用户明确提及的内容。\n3.将生成的新内容添加在现有备忘录（或经你调整后的备忘录）的后面。\n4.若最新对话不包含需要备忘录记录的信息，则保留现有备忘录不变。\n5.备忘录内容具有时效性，应定期清理已解决或过时的条目，确保简洁性。\n生成内容要求：\n1. 仅记录短期、临时、具体的信息。包括但不限于：当前讨论的主题与进度、用户临时的情绪状态、未完成的待办事项、近期计划、短期偏好变化、具体的生活琐事分享。\n2.只记录用户明确提及或可从对话中客观推断的事实，不进行任何主观猜测、评价或情感渲染。不自行编造任何未发生的事件。\n3.优先级： 当前任务状态 > 未完成约定/待办 > 临时偏好/状态 > 近期计划 > 分享的生活琐事。\n4. 使用第三视角和极简句式，省略一切不必要的修饰词。使用"编号. 内容"的格式进行罗列，每条记录不超过30字。可保留必要的日期、时间等临时信息。\n5.主动合并或删除重复、已解决的条目。当任务完成或信息明显过时（如约定的日期已过），应在更新时移除此类信息。\n6.输出示例：1. 用户正在规划周末露营\\n2. 需在本周五前确认营地\\n3. 用户今日表示工作压力较大\\n4. 临时想购买一款新耳机\n7.输出格式：仅输出更新后的备忘录内容本身（即编号列表），无需任何额外解释。总条目数应保持精简，避免冗长。'
        }
        default_prompt = default_prompts.get(prompt_type, '请处理以下内容并生成合适的总结。')
        logger.info(f"使用内置默认{prompt_type}提示词: {default_prompt[:100]}{'...' if len(default_prompt) > 100 else ''}")
        return default_prompt
    except Exception as e:
        logger.error(f"获取用户 {username} 的 {prompt_type} 提示词失败: {str(e)}")
        return '请处理以下内容并生成合适的总结。'

def generate_daily_summary(user_id, target_date=None):
    """
    生成指定日期的日记和碎碎念备忘录
    Args:
        user_id: 用户ID
        target_date: 目标日期，默认为昨天
    """
    if not ENABLE_DAILY_SUMMARY:
        logger.info(f"按天总结功能已禁用，跳过用户 {user_id} 的日记生成")
        return False

    memory_key = get_user_memory_key(user_id)
    role_name = prompt_mapping.get(user_id, user_id)
    
    # 确定目标日期
    if target_date is None:
        target_date = (datetime.now() - dt.timedelta(days=1)).strftime('%Y-%m-%d')
    
    # 检查临时日志文件
    log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_diary_log.txt')
    if not os.path.exists(log_file):
        # 如果没有专门的日记文件，则复制主文件
        main_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
        if os.path.exists(main_log_file):
            import shutil
            shutil.copy2(main_log_file, log_file)
            logger.info(f"为用户 {user_id} 创建了专用的日记临时文件")
        else:
            logger.info(f"用户 {user_id} 没有对话日志，跳过日记生成")
            return False
        
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:  # ✅ 添加 errors='ignore'
        logs = [line.strip() for line in f if line.strip()]
    
    if len(logs) < 3:
        logger.info(f"用户 {user_id} 对话内容太少，跳过日记生成")
        return False
    
    # 创建日记和备忘录存储目录
    daily_dir = os.path.join(root_dir, MEMORY_DAILY_DIR, memory_key)
    diary_dir = os.path.join(daily_dir, 'diary')
    memos_dir = os.path.join(daily_dir, 'memos')
    
    os.makedirs(diary_dir, exist_ok=True)
    os.makedirs(memos_dir, exist_ok=True)
    
    # === 新增：备份临时日志文件（日记总结前） ===
    temp_backup_files = backup_temp_log_files(user_id)
    if temp_backup_files:
        logger.info(f"日记总结前临时日志文件已备份，共 {len(temp_backup_files)} 个文件")
    else:
        logger.info(f"用户 {user_id} 日记总结前未备份到临时日志文件，继续执行总结")
    
    try:
        # 构建日记总结提示词
        full_logs = '\n'.join(logs)
        
        # 获取用户自定义的日记提示词
        custom_diary_prompt = get_user_memory_prompt(user_id, 'diary')
        
        # === 获取角色人设文件内容 ===
        role_personality_content = ""
        try:
            prompt_file_name = prompt_mapping.get(user_id, user_id)
            # 兼容新旧目录
            prompt_path = None
            for check_dir in ['prompts/characters', 'prompts']:
                p = os.path.join(root_dir, check_dir, f'{prompt_file_name}.md')
                if os.path.exists(p):
                    prompt_path = p
                    break
            if prompt_path:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    role_personality_content = f.read().strip()
                logger.info(f"日记生成-成功加载角色人设文件：{prompt_path}")
            else:
                logger.warning(f"日记生成-角色人设文件不存在：{prompt_file_name}.md")
        except Exception as e:
            logger.error(f"日记生成-加载角色人设文件失败，用户：{user_id}，错误：{e}")
        
        diary_prompt = f"""
基于以下角色人设和指导原则，生成日记内容：

角色人设：
{role_personality_content if role_personality_content else "暂无角色人设"}

日记生成指导原则：
{custom_diary_prompt}

对话记录：
{full_logs}

请直接输出日记内容，不要前缀和后缀：
"""

        # 构建碎碎念备忘录提示词
        # 获取用户自定义的碎碎念备忘录提示词  
        custom_memo_prompt = get_user_memory_prompt(user_id, 'memo_fragments')
        
        memo_prompt = f"""
基于以下角色人设和指导原则，生成碎碎念备忘录：

角色人设：
{role_personality_content if role_personality_content else "暂无角色人设"}

备忘录生成指导原则：
{custom_memo_prompt}

对话记录：
{full_logs}

请直接输出JSON格式的备忘录：
"""

        # 调用AI生成日记和备忘录（独立处理，互不影响）
        diary_success = False
        memo_success = False
        
        # 生成日记
        logger.info("开始调用AI生成日记")
        try:
            diary_content = call_ai_for_summary(diary_prompt, user_id)
            if diary_content:
                logger.info(f"日记生成成功，长度：{len(diary_content)}")
                diary_success = True
            else:
                logger.error("日记生成失败：AI返回空内容")
        except Exception as e:
            logger.error(f"日记生成失败：{e}")
            diary_content = None
            
        # 生成碎碎念备忘录
        logger.info("开始调用AI生成碎碎念备忘录")
        try:
            memo_content = call_ai_for_summary(memo_prompt, user_id)
            if memo_content:
                logger.info(f"碎碎念备忘录生成成功，长度：{len(memo_content)}")
                # ✅ 添加调试日志
                logger.info(f"🔍 AI返回的原始内容（前500字符）: {repr(memo_content[:500])}")
                logger.info(f"🔍 内容类型: {type(memo_content)}")
                memo_success = True
            else:
                logger.error("碎碎念备忘录生成失败：AI返回空内容")
        except Exception as e:
            logger.error(f"碎碎念备忘录生成失败：{e}")
            memo_content = None
        
        # 保存日记（独立处理）
        if ENABLE_DIARY_SUMMARY and diary_success and diary_content:
            try:
                diary_file = os.path.join(diary_dir, f'{target_date}.md')
                with open(diary_file, 'w', encoding='utf-8') as f:
                    f.write(f"# {target_date} 日记\n\n{diary_content}\n")
                logger.info(f"已保存 {user_id} 的日记：{diary_file}")
            except Exception as e:
                logger.error(f"保存日记失败，用户：{user_id}，错误：{e}")
                diary_success = False
        
        # 保存碎碎念备忘录（独立处理）
        if ENABLE_MEMO_SUMMARY and memo_success and memo_content:
            memo_file = os.path.join(memos_dir, f'{target_date}.json')
            try:
                # 1️⃣ 清理AI响应
                cleaned_memo_content = memo_content.strip()
                
                # 移除markdown代码块
                if '```json' in cleaned_memo_content:
                    start = cleaned_memo_content.find('```json') + 7
                    end = cleaned_memo_content.find('```', start)
                    if end != -1:
                        cleaned_memo_content = cleaned_memo_content[start:end].strip()
                elif '```' in cleaned_memo_content:
                    start = cleaned_memo_content.find('```') + 3
                    end = cleaned_memo_content.find('```', start)
                    if end != -1:
                        cleaned_memo_content = cleaned_memo_content[start:end].strip()
                
                # 2️⃣ 修复中文引号（关键！）
                cleaned_memo_content = cleaned_memo_content.replace('"', '"')
                cleaned_memo_content = cleaned_memo_content.replace('"', '"')
                cleaned_memo_content = cleaned_memo_content.replace(''', "'")
                cleaned_memo_content = cleaned_memo_content.replace(''', "'")
                
                logger.info(f"🧹 清理后的备忘录内容（前200字符）: {cleaned_memo_content[:200]}")
                
                # 3️⃣ 尝试解析JSON
                memo_json = None
                try:
                    memo_json = json.loads(cleaned_memo_content)
                    logger.info(f"✓ JSON解析成功，类型: {type(memo_json)}")
                except json.JSONDecodeError as e:
                    logger.warning(f"⚠ JSON解析失败: {e}")
                    
                    # 🔧 兜底1：检查是否是编号列表格式
                    if re.search(r'^\d+\.', cleaned_memo_content, re.MULTILINE):
                        logger.info("检测到编号列表格式，转换为JSON...")
                        lines = cleaned_memo_content.split('\n')
                        memos_list = []
                        for i, line in enumerate(lines, 1):
                            line = line.strip()
                            if line and re.match(r'^\d+\.', line):
                                content = re.sub(r'^\d+\.\s*', '', line)
                                if content:
                                    memos_list.append({
                                        "id": i,
                                        "content": content,
                                        "category": "funny_moments",
                                        "created_at": target_date
                                    })
                        memo_json = {"memos": memos_list}
                        logger.info(f"✓ 已转换 {len(memos_list)} 条编号列表为JSON")
                    else:
                        # 🔧 兜底2：作为纯文本保存
                        logger.warning("无法识别格式，作为单条备忘录保存")
                        memo_json = {
                            "memos": [{
                                "id": 1,
                                "content": cleaned_memo_content,
                                "category": "funny_moments",
                                "created_at": target_date
                            }]
                        }
                
                # 4️⃣ 标准化格式
                if memo_json:
                    if isinstance(memo_json, dict) and "memos" in memo_json:
                        # ✅ 标准格式
                        memos_list = memo_json["memos"]
                        logger.info(f"✓ 检测到标准格式，共 {len(memos_list)} 条备忘录")
                        
                    elif isinstance(memo_json, list):
                        # 兼容直接返回列表的情况
                        logger.info(f"✓ 检测到列表格式，共 {len(memo_json)} 条")
                        memos_list = []
                        for i, item in enumerate(memo_json, 1):
                            if isinstance(item, dict):
                                item.setdefault("id", i)
                                item.setdefault("category", "funny_moments")
                                item.setdefault("created_at", target_date)
                                memos_list.append(item)
                            elif isinstance(item, str):
                                memos_list.append({
                                    "id": i,
                                    "content": item,
                                    "category": "funny_moments",
                                    "created_at": target_date
                                })
                        memo_json = {"memos": memos_list}
                        
                    elif isinstance(memo_json, dict):
                        # 兼容旧格式（important_topics等）
                        logger.info("✓ 检测到旧格式，正在转换...")
                        old_keys = ["important_topics", "emotional_moments", "plans_or_promises", "preferences", "funny_moments"]
                        category_map = {
                            "important_topics": "important_info",
                            "emotional_moments": "emotional",
                            "plans_or_promises": "important_info",
                            "preferences": "preferences",
                            "funny_moments": "funny_moments"
                        }
                        
                        memos_list = []
                        memo_id = 1
                        for old_key in old_keys:
                            if old_key in memo_json:
                                items = memo_json[old_key]
                                if isinstance(items, list):
                                    for item in items:
                                        if isinstance(item, str) and item.strip():
                                            memos_list.append({
                                                "id": memo_id,
                                                "content": item.strip(),
                                                "category": category_map.get(old_key, "funny_moments"),
                                                "created_at": target_date
                                            })
                                            memo_id += 1
                        
                        memo_json = {"memos": memos_list}
                        logger.info(f"✓ 已转换旧格式为标准格式，共 {len(memos_list)} 条")
                    else:
                        logger.error(f"❌ 未知的JSON结构: {type(memo_json)}")
                        raise ValueError(f"未知的JSON结构: {type(memo_json)}")
                    
                    # 5️⃣ 验证每条备忘录
                    validated_memos = []
                    for i, memo in enumerate(memos_list, 1):
                        if isinstance(memo, dict):
                            validated_memos.append({
                                "id": memo.get("id", i),
                                "content": memo.get("content", "").strip(),
                                "category": memo.get("category", "funny_moments"),
                                "created_at": memo.get("created_at", target_date)
                            })
                        elif isinstance(memo, str) and memo.strip():
                            validated_memos.append({
                                "id": i,
                                "content": memo.strip(),
                                "category": "funny_moments",
                                "created_at": target_date
                            })
                    
                    # 6️⃣ 保存
                    final_json = {
                        "memos": validated_memos,
                        "metadata": {
                            "last_updated": target_date,
                            "total_count": len(validated_memos),
                            "version": "2.0"
                        }
                    }
                    
                    with open(memo_file, 'w', encoding='utf-8') as f:
                        json.dump(final_json, f, ensure_ascii=False, indent=2)
                    
                    # 7️⃣ 日志
                    logger.info(f"✅ 已保存备忘录，共 {len(validated_memos)} 条：{memo_file}")
                    
                    # 按分类统计
                    from collections import Counter
                    category_count = Counter(m["category"] for m in validated_memos)
                    for category, count in category_count.items():
                        logger.info(f"   📝 {category}: {count} 条")
                    
                    # 显示前3条预览
                    for memo in validated_memos[:3]:
                        preview = memo["content"][:30] + "..." if len(memo["content"]) > 30 else memo["content"]
                        logger.info(f"   [{memo['id']}] {preview}")
                    if len(validated_memos) > 3:
                        logger.info(f"   ... 还有 {len(validated_memos)-3} 条")
                
                else:
                    logger.error("❌ memo_json为空，无法保存")
                    memo_success = False
                
            except Exception as e:
                logger.error(f"❌ 备忘录保存失败: {e}", exc_info=True)
                # 保存原始内容供调试
                raw_file = memo_file.replace('.json', '_RAW.txt')
                try:
                    with open(raw_file, 'w', encoding='utf-8') as f:
                        f.write(f"错误: {e}\n\n原始内容:\n{memo_content}")
                    logger.info(f"原始内容已保存到: {raw_file}")
                except:
                    pass
                memo_success = False
        
        # 检查是否至少有一个成功
        if not diary_success and not memo_success:
            logger.error(f"日记和碎碎念备忘录都生成失败，用户：{user_id}")
            return False
        
        # 记录成功状态
        success_parts = []
        if diary_success:
            success_parts.append("日记")
        if memo_success:
            success_parts.append("碎碎念备忘录")
        logger.info(f"用户 {user_id} 生成成功的部分：{', '.join(success_parts)}")
        
        # 清空专用的日记临时日志文件
        try:
            if os.path.exists(log_file):
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.truncate(0)
                logger.info(f"已清空用户 {user_id} 的专用日记临时日志文件")
        except Exception as e:
            logger.warning(f"清空日记临时日志文件失败: {e}")
        
        # === 日记总结成功，清理临时备份文件 ===
        cleanup_temp_backup_files(temp_backup_files)
        
        return True
        
    except Exception as e:
        logger.error(f"生成用户 {user_id} 的日记总结时出错: {e}", exc_info=True)
        
        # === 日记总结失败，尝试恢复临时日志文件 ===
        logger.warning(f"日记总结失败，尝试恢复用户 {user_id} 的临时日志文件")
        if 'temp_backup_files' in locals() and temp_backup_files:
            restore_success = restore_temp_log_files(user_id, temp_backup_files)
            if restore_success:
                logger.info(f"用户 {user_id} 的临时日志文件已成功恢复")
            else:
                logger.error(f"用户 {user_id} 的临时日志文件恢复失败，数据可能丢失")
        else:
            logger.warning(f"用户 {user_id} 没有临时备份文件可恢复")
        
        return False

def backup_temp_log_files(user_id):
    """备份Memory_Temp中的日志文件"""
    try:
        memory_key = get_user_memory_key(user_id)
        role_name = prompt_mapping.get(user_id, user_id)
        
        # 创建备份目录
        temp_backup_dir = os.path.join(root_dir, MEMORY_TEMP_DIR, 'backups')
        os.makedirs(temp_backup_dir, exist_ok=True)
        
        # 生成时间戳
        timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
        
        # 需要备份的日志文件列表
        log_files = [
            f'{user_id}_{role_name}_log.txt',          # 主日志
            f'{user_id}_{role_name}_core_log.txt',     # 核心记忆专用日志
            f'{user_id}_{role_name}_diary_log.txt'     # 日记专用日志
        ]
        
        backup_files = []
        
        for log_file in log_files:
            source_path = os.path.join(root_dir, MEMORY_TEMP_DIR, log_file)
            if os.path.exists(source_path) and os.path.getsize(source_path) > 0:
                # 生成备份文件名
                backup_filename = f'{memory_key}_{timestamp}_{log_file}'
                backup_path = os.path.join(temp_backup_dir, backup_filename)
                
                # 复制文件到备份目录
                import shutil
                shutil.copy2(source_path, backup_path)
                backup_files.append(backup_path)
                logger.info(f"已备份临时日志文件：{source_path} -> {backup_path}")
        
        if backup_files:
            logger.info(f"用户 {user_id} 的临时日志文件备份完成，共备份 {len(backup_files)} 个文件")
            return backup_files
        else:
            logger.info(f"用户 {user_id} 没有需要备份的临时日志文件")
            return []
            
    except Exception as e:
        logger.error(f"备份用户 {user_id} 的临时日志文件失败: {e}")
        return []

def restore_temp_log_files(user_id, backup_files):
    """从备份恢复临时日志文件（当总结失败时使用）"""
    try:
        if not backup_files:
            logger.warning(f"用户 {user_id} 没有备份文件可恢复")
            return False
        
        memory_key = get_user_memory_key(user_id)
        role_name = prompt_mapping.get(user_id, user_id)
        restored_count = 0
        
        for backup_path in backup_files:
            if os.path.exists(backup_path):
                # 从备份文件名中提取原始文件名
                backup_filename = os.path.basename(backup_path)
                # 格式: {memory_key}_{timestamp}_{original_filename}
                parts = backup_filename.split('_', 3)  # 最多分割3次
                if len(parts) >= 4:
                    original_filename = parts[3]  # 原始文件名
                    original_path = os.path.join(root_dir, MEMORY_TEMP_DIR, original_filename)
                    
                    # 恢复文件
                    import shutil
                    shutil.copy2(backup_path, original_path)
                    restored_count += 1
                    logger.info(f"已恢复临时日志文件：{backup_path} -> {original_path}")
                else:
                    logger.warning(f"备份文件名格式不正确：{backup_filename}")
            else:
                logger.warning(f"备份文件不存在：{backup_path}")
        
        if restored_count > 0:
            logger.info(f"用户 {user_id} 的临时日志文件恢复完成，共恢复 {restored_count} 个文件")
            return True
        else:
            logger.error(f"用户 {user_id} 的临时日志文件恢复失败，没有文件被恢复")
            return False
            
    except Exception as e:
        logger.error(f"恢复用户 {user_id} 的临时日志文件失败: {e}")
        return False

def cleanup_temp_backup_files(backup_files):
    """清理临时备份文件（总结成功后调用）"""
    try:
        if not backup_files:
            return True
        
        cleaned_count = 0
        for backup_path in backup_files:
            if os.path.exists(backup_path):
                os.remove(backup_path)
                cleaned_count += 1
                logger.debug(f"已清理临时备份文件：{backup_path}")
        
        if cleaned_count > 0:
            logger.info(f"临时备份文件清理完成，共清理 {cleaned_count} 个文件")
        return True
        
    except Exception as e:
        logger.error(f"清理临时备份文件失败: {e}")
        return False

def backup_memory_summaries(user_id):
    """为Memory_Summaries创建备份"""
    try:
        memory_key = get_user_memory_key(user_id)
        summaries_dir = os.path.join(root_dir, MEMORY_SUMMARIES_DIR)
        backup_dir = os.path.join(summaries_dir, 'backups')
        os.makedirs(backup_dir, exist_ok=True)
        
        # 源文件路径
        source_file = os.path.join(summaries_dir, f'{memory_key}.json')
        
        if os.path.exists(source_file):
            # 生成带时间戳的备份文件名
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            backup_file = os.path.join(backup_dir, f'{memory_key}_{timestamp}.json')
            
            # 复制文件到备份目录
            import shutil
            shutil.copy2(source_file, backup_file)
            logger.info(f"核心记忆已备份到：{backup_file}")
            return backup_file
        else:
            logger.info(f"用户 {user_id} 暂无核心记忆文件需要备份")
            return None
            
    except Exception as e:
        logger.error(f"备份用户 {user_id} 的核心记忆失败: {e}")
        return None

def load_existing_memory_summaries(user_id):
    """加载现有的Memory_Summaries内容供AI参考"""
    try:
        memory_key = get_user_memory_key(user_id)
        summaries_dir = os.path.join(root_dir, MEMORY_SUMMARIES_DIR)
        summaries_file = os.path.join(summaries_dir, f'{memory_key}.json')
        
        if os.path.exists(summaries_file):
            with open(summaries_file, 'r', encoding='utf-8') as f:
                content = f.read()
                if content.strip():
                    data = json.loads(content)
                    
                    # 格式化现有记忆供AI参考
                    existing_memory = ""
                    if 'core_memory' in data:
                        existing_memory += f"现有核心记忆：\n{data['core_memory']}\n\n"
                    if 'core_memos' in data:
                        # 检查核心备忘录的格式
                        core_memos = data['core_memos']
                        if isinstance(core_memos, dict) and 'format' in core_memos:
                            if core_memos['format'] == 'text':
                                # 纯文本格式
                                memo_content = core_memos.get('memos', {}).get('content', '')
                                existing_memory += f"现有核心备忘录：\n{memo_content}\n\n"
                            else:
                                # JSON格式
                                existing_memory += f"现有核心备忘录：\n{json.dumps(core_memos, ensure_ascii=False, indent=2)}\n\n"
                        else:
                            # 兼容旧格式（没有format标识）
                            existing_memory += f"现有核心备忘录：\n{json.dumps(core_memos, ensure_ascii=False, indent=2)}\n\n"
                    
                    logger.info(f"已加载用户 {user_id} 现有核心记忆，长度：{len(existing_memory)}")
                    return existing_memory
                    
        logger.info(f"用户 {user_id} 暂无现有核心记忆")
        return ""
        
    except Exception as e:
        logger.error(f"加载用户 {user_id} 现有核心记忆失败: {e}")
        return ""

def check_core_memory_update_needed(user_id):
    """检查是否需要更新核心记忆（基于对话轮数）"""
    role_name = prompt_mapping.get(user_id, user_id)
    # 🔧 修复：优先检查专用的核心记忆日志文件
    core_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_core_log.txt')
    main_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
    
    # 优先使用专用核心记忆日志，如果不存在则使用主日志
    log_file = core_log_file if os.path.exists(core_log_file) else main_log_file
    
    if not os.path.exists(log_file):
        return False
        
    with open(log_file, 'r', encoding='utf-8') as f:
        logs = [line.strip() for line in f if line.strip()]
    
    # 计算对话轮数：统计用户消息数量（每个用户消息代表一轮对话的开始）
    user_messages = 0
    for line in logs:
        # 检查是否包含用户标识（例如 [Mine], [糖欣] 等）
        if f'[{user_id}]' in line:
            user_messages += 1
    
    logger.debug(f"用户 {user_id} 当前有 {user_messages} 轮对话，阈值：{MAX_MESSAGE_LOG_ENTRIES}")
    return user_messages >= MAX_MESSAGE_LOG_ENTRIES

def generate_core_memory_update_with_cleanup(user_id, force_update=False):
    """包装函数：执行核心记忆更新并清理状态标记"""
    try:
        # 调用实际的核心记忆更新函数
        result = generate_core_memory_update(user_id, force_update)
        return result
    except Exception as e:
        logger.error(f"用户 {user_id} 核心记忆更新过程中出现异常: {e}", exc_info=True)
        return False
    finally:
        # 无论成功失败都清理状态标记
        if user_id in core_memory_update_in_progress:
            core_memory_update_in_progress[user_id] = False
            logger.debug(f"已清理用户 {user_id} 的核心记忆更新进行中标记")

def generate_core_memory_update(user_id, force_update=False):
    """更新核心记忆和核心备忘录（统一格式）"""
    memory_key = get_user_memory_key(user_id)
    role_name = prompt_mapping.get(user_id, user_id)
    logger.info(f"开始生成统一格式核心记忆更新，用户：{user_id}, 角色：{role_name}, 记忆键：{memory_key}, 强制更新：{force_update}")
    
    # 创建核心记忆目录
    core_dir = os.path.join(root_dir, MEMORY_CORE_DIR)
    os.makedirs(core_dir, exist_ok=True)
    summaries_dir = os.path.join(root_dir, MEMORY_SUMMARIES_DIR)
    os.makedirs(summaries_dir, exist_ok=True)
    
    # 统一的记忆文件路径
    unified_memory_file = os.path.join(core_dir, f'{memory_key}_unified_memory.json')
    summaries_file = os.path.join(summaries_dir, f'{memory_key}.json')
    logger.info(f"统一记忆文件路径：{unified_memory_file}")
    logger.info(f"配置编辑器记忆文件路径：{summaries_file}")
    
    # 读取临时日志
    log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_core_log.txt')
    if not os.path.exists(log_file):
        # 如果没有专门的核心记忆文件，则复制主文件
        main_log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
        if os.path.exists(main_log_file):
            import shutil
            shutil.copy2(main_log_file, log_file)
            logger.info(f"为用户 {user_id} 创建了专用的核心记忆临时文件")
        else:
            logger.error(f"临时日志文件不存在：{main_log_file}")
            return False
        
    with open(log_file, 'r', encoding='utf-8') as f:
        logs = [line.strip() for line in f if line.strip()]
    
    # 计算对话轮数：统计用户消息数量（每个用户消息代表一轮对话的开始）
    user_messages = 0
    for line in logs:
        # 检查是否包含用户标识（例如 [Mine], [糖欣] 等）
        if f'[{user_id}]' in line:
            user_messages += 1
    
    logger.info(f"读取到 {len(logs)} 条日志记录，对话轮数：{user_messages}，阈值：{MAX_MESSAGE_LOG_ENTRIES}")
    # 只有在非强制更新时才检查对话轮数
    if not force_update and user_messages < MAX_MESSAGE_LOG_ENTRIES:
        logger.info(f"对话轮数不足，需要至少 {MAX_MESSAGE_LOG_ENTRIES} 轮")
        return False
    
    # 🔧 修复：只有在确认需要总结时才备份
    # === 备份现有的Memory_Summaries ===
    backup_file = backup_memory_summaries(user_id)
    if backup_file:
        logger.info(f"现有核心记忆已备份到：{backup_file}")
    
    # === 新增：备份临时日志文件 ===
    temp_backup_files = backup_temp_log_files(user_id)
    if temp_backup_files:
        logger.info(f"临时日志文件已备份，共 {len(temp_backup_files)} 个文件")
    else:
        logger.warning(f"用户 {user_id} 的临时日志文件备份为空，继续执行总结")
    
    # === 加载现有的Memory_Summaries供AI参考 ===
    existing_summaries = load_existing_memory_summaries(user_id)
    
    # 读取现有的统一记忆内容
    existing_unified_content = ""
    if os.path.exists(unified_memory_file):
        try:
            with open(unified_memory_file, 'r', encoding='utf-8') as f:
                memory_data = json.load(f)
                existing_unified_content = memory_data.get("content", "")
        except:
            pass
    
    # 如果没有统一格式文件，尝试从旧格式文件加载
    if not existing_unified_content:
        old_memory_file = os.path.join(core_dir, f'{memory_key}_core_memory.json')
        old_memos_file = os.path.join(core_dir, f'{memory_key}_core_memos.json')
        
        existing_memory = ""
        existing_memos = ""
        
        if os.path.exists(old_memory_file):
            try:
                with open(old_memory_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    existing_memory = data.get("content", "")
            except:
                pass
        
        if os.path.exists(old_memos_file):
            try:
                with open(old_memos_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    if isinstance(data.get("memos"), str):
                        existing_memos = data["memos"]
                    elif isinstance(data.get("memos"), dict):
                        existing_memos = data["memos"].get("content", "")
            except:
                pass
        
        if existing_memory or existing_memos:
            existing_unified_content = f"[核心记忆]\n{existing_memory}\n\n[备忘录]\n{existing_memos}"
            logger.info("从旧格式文件中加载了现有记忆内容")
    
    try:
        full_logs = '\n'.join(logs)
        
        # 获取用户自定义的提示词
        custom_core_memory_prompt = get_user_memory_prompt(user_id, 'core_memory')
        custom_core_memo_prompt = get_user_memory_prompt(user_id, 'core_memo')
        
        # === 获取角色人设文件内容 ===
        role_personality_content = ""
        try:
            prompt_file_name = prompt_mapping.get(user_id, user_id)
            prompt_path = None
            for check_dir in ['prompts/characters', 'prompts']:
                p = os.path.join(root_dir, check_dir, f'{prompt_file_name}.md')
                if os.path.exists(p):
                    prompt_path = p
                    break
            if prompt_path:
                with open(prompt_path, 'r', encoding='utf-8') as f:
                    role_personality_content = f.read().strip()
                logger.info(f"成功加载角色人设文件：{prompt_path}")
            else:
                logger.warning(f"角色人设文件不存在：{prompt_file_name}.md")
        except Exception as e:
            logger.error(f"加载角色人设文件失败，用户：{user_id}，错误：{e}")
        
        # 构建统一的记忆更新提示词
        unified_prompt = f"""
请基于角色人设、现有的核心记忆和备忘录以及最新的对话记录，生成更新后的完整记忆内容。

角色人设文件：
{role_personality_content if role_personality_content else "暂无角色人设"}

现有记忆内容：
{existing_unified_content if existing_unified_content else "暂无现有记忆"}

现有记忆总结（供参考）：
{existing_summaries if existing_summaries else "暂无现有记忆总结"}

最新对话记录：
{full_logs}

请严格按照以下格式生成完整的记忆内容：

### 核心记忆指导原则：
{custom_core_memory_prompt}

### 备忘录指导原则：
{custom_core_memo_prompt}

### 生成要求：
1. 保留现有记忆中仍然重要和有效的信息
2. 整合最新对话中的新信息
3. 删除过时或不重要的信息
4. 确保信息的连续性和完整性
5. 核心记忆记录长期、重要的用户特质和关系信息
6. 备忘录记录短期、临时、具体的事项和状态

### 输出格式（必须严格遵守）：
[核心记忆]
[在这里输出核心记忆内容，使用自然段落格式]

[备忘录]
1. [第一条备忘事项]
2. [第二条备忘事项]
3. [第三条备忘事项]
...

请直接输出上述格式的内容，不要包含任何其他解释或标记：
"""

        # 调用AI生成统一的记忆内容
        logger.info("开始调用AI生成统一的核心记忆和备忘录")
        new_unified_content = call_ai_for_summary(unified_prompt, user_id)
        
        if not new_unified_content:
            logger.error("AI生成统一记忆内容失败")
            # === AI调用失败，尝试恢复临时日志文件 ===
            logger.warning(f"AI调用失败，尝试恢复用户 {user_id} 的临时日志文件")
            if temp_backup_files:
                restore_success = restore_temp_log_files(user_id, temp_backup_files)
                if restore_success:
                    logger.info(f"用户 {user_id} 的临时日志文件已成功恢复")
                else:
                    logger.error(f"用户 {user_id} 的临时日志文件恢复失败，数据可能丢失")
            else:
                logger.warning(f"用户 {user_id} 没有临时备份文件可恢复")
            return False
            
        logger.info(f"统一记忆内容生成成功，长度：{len(new_unified_content)}")
        logger.debug(f"统一记忆AI回复前200字符：{new_unified_content[:200]}...")
        
        # 处理AI回复内容
        cleaned_content = new_unified_content.strip()
        
        # 验证内容格式（确保包含[核心记忆]和[备忘录]标记）
        if "[核心记忆]" not in cleaned_content and "[备忘录]" not in cleaned_content:
            logger.warning("AI回复不包含预期的格式标记，将整个回复作为内容")
            # 如果格式不对，尝试手动构建格式
            cleaned_content = f"[核心记忆]\n{cleaned_content}\n\n[备忘录]\n（无备忘录内容）"
        
        # 创建统一格式的记忆数据
        unified_data = {
            "timestamp": datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
            "content": cleaned_content
        }
        
        # 保存统一格式文件
        with open(unified_memory_file, 'w', encoding='utf-8') as f:
            json.dump(unified_data, f, ensure_ascii=False, indent=2)
        logger.info(f"统一记忆文件保存成功：{unified_memory_file}")
        
        # 同时保存到Memory_Summaries目录用于配置编辑器
        with open(summaries_file, 'w', encoding='utf-8') as f:
            json.dump(unified_data, f, ensure_ascii=False, indent=2)
        logger.info(f"记忆文件已同步到配置编辑器：{summaries_file}")
        
        # 清空专用的核心记忆临时日志文件
        try:
            if os.path.exists(log_file):
                with open(log_file, 'w', encoding='utf-8') as f:
                    f.truncate(0)
                logger.info(f"已清空用户 {user_id} 的专用核心记忆临时日志文件")
        except Exception as e:
            logger.warning(f"清空核心记忆临时日志文件失败: {e}")
        
        # 🔧 修复：不再清空主日志文件，因为它是日记总结的重要备用数据源
        # 核心记忆触发条件检查已经优先使用专用的core_log.txt文件
        # 主日志文件应该保留给日记总结系统使用
        logger.info("保留主日志文件供日记总结系统使用")
        
        logger.info(f"已更新用户 {user_id} 的统一格式核心记忆")
        
        # === 总结成功，清理临时备份文件 ===
        cleanup_temp_backup_files(temp_backup_files)
        
        return True
        
    except Exception as e:
        logger.error(f"统一记忆生成过程中发生未知错误: {e}", exc_info=True)
        
        # === 总结失败，尝试恢复临时日志文件 ===
        logger.warning(f"核心记忆总结失败，尝试恢复用户 {user_id} 的临时日志文件")
        if 'temp_backup_files' in locals() and temp_backup_files:
            restore_success = restore_temp_log_files(user_id, temp_backup_files)
            if restore_success:
                logger.info(f"用户 {user_id} 的临时日志文件已成功恢复")
            else:
                logger.error(f"用户 {user_id} 的临时日志文件恢复失败，数据可能丢失")
        else:
            logger.warning(f"用户 {user_id} 没有临时备份文件可恢复")
        
        return False

def call_ai_for_summary(prompt, user_id):
    """
    调用AI进行记忆总结（终极健壮版）
    特性：
    1. 优先使用流式传输 (Stream) 解决 Render/反代 超时问题。
    2. 如果模型不支持流式，自动降级为普通模式 (Non-Stream)。
    3. 包含指数退避重试机制 (Retry)。
    4. 忽略 SSL 证书错误，适应各种代理环境。
    """
    import httpx
    import time
    from openai import APIConnectionError, APITimeoutError, BadRequestError

    # --- 配置区域 ---
    MAX_RETRIES = 3           # 最大重试次数
    STREAM_TIMEOUT = 30.0     # 流式模式下，等待"第一个字"出来的最大秒数 (通常很快)
    TOTAL_TIMEOUT = 300.0     # 总体最大超时时间 (5分钟)
    # ----------------

    # 定义一个内部函数来处理请求，方便重试逻辑调用
    def _execute_request(client, model_name, use_stream):
        try:
            # 发起请求
            response = client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.7,
                max_tokens=60000,
                stream=use_stream, # 动态决定是否流式
                timeout=TOTAL_TIMEOUT
            )

            # --- 分支 A: 处理流式响应 ---
            if use_stream:
                collected_content = []
                # 迭代接收数据包
                for chunk in response:
                    if chunk.choices and len(chunk.choices) > 0:
                        delta = chunk.choices[0].delta
                        if hasattr(delta, 'content') and delta.content:
                            collected_content.append(delta.content)
                
                full_text = "".join(collected_content).strip()
                return full_text

            # --- 分支 B: 处理普通响应 ---
            else:
                if not response.choices or len(response.choices) == 0:
                    return None
                content = response.choices[0].message.content
                return content.strip() if content else None

        except BadRequestError as e:
            # 这是一个关键捕获：如果报错说 "Stream not supported" 之类的
            # 我们就抛出一个特定的标记，让外层知道该降级了
            if 'stream' in str(e).lower():
                raise RuntimeError("MODEL_DOES_NOT_SUPPORT_STREAMING")
            raise e # 其他错误照常抛出

    # ================= 主循环逻辑 =================
    for attempt in range(MAX_RETRIES):
        try:
            # 1. 准备配置 (每次重试都重新初始化，防止连接池污染)
            if USE_ASSISTANT_FOR_MEMORY_SUMMARY and ENABLE_ASSISTANT_MODEL:
                target_url = ASSISTANT_BASE_URL
                target_key = ASSISTANT_API_KEY
                target_model = ASSISTANT_MODEL
            else:
                target_url = DEEPSEEK_BASE_URL
                target_key = DEEPSEEK_API_KEY
                target_model = MODEL

            # 自动修正 URL
            if target_url and not target_url.endswith('/v1'):
                target_url = target_url.rstrip('/') + '/v1'

            # 初始化 HTTP 客户端 (忽略证书错误)
            http_client = httpx.Client(verify=False, timeout=TOTAL_TIMEOUT)
            client = OpenAI(api_key=target_key, base_url=target_url, http_client=http_client, default_headers=_BROWSER_HEADERS)

            # 2. 尝试策略：默认先试流式 (Stream=True)
            # 因为这在 Render 环境下最稳定
            try:
                logger.info(f"正在进行记忆总结 (尝试 {attempt+1}/{MAX_RETRIES})... 模型: {target_model} [流式模式]")
                return _execute_request(client, target_model, use_stream=True)
            
            except RuntimeError as re:
                if str(re) == "MODEL_DOES_NOT_SUPPORT_STREAMING":
                    logger.warning(f"该模型不支持流式传输，正在切换到普通模式重试...")
                    # 立即在同一次尝试中降级为普通模式
                    return _execute_request(client, target_model, use_stream=False)
                else:
                    raise re # 继续向外抛出

        except Exception as e:
            logger.warning(f"AI记忆总结第 {attempt + 1} 次尝试失败: {e}")
            
            # 如果是最后一次尝试，打印详细日志并退出
            if attempt == MAX_RETRIES - 1:
                logger.error(f"AI记忆总结最终失败，用户 {user_id}", exc_info=True)
                return None
            
            # 等待后重试
            time.sleep(3)

def memory_manager():
    """记忆管理定时任务"""
    pass

def clear_memory_temp_files(user_id):
    """清除指定用户的Memory_Temp文件"""
    try:
        logger.warning(f"已开启自动清除Memory_Temp文件功能, 尝试清除用户 {user_id} 的Memory_Temp文件")
        prompt_name = prompt_mapping.get(user_id, user_id)
        log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{prompt_name}_log.txt')
        if os.path.exists(log_file):
            os.remove(log_file)
            logger.warning(f"已清除用户 {user_id} 的Memory_Temp文件: {log_file}")
    except Exception as e:
        logger.error(f"清除Memory_Temp文件失败: {str(e)}")

def clear_chat_context(user_id):
    """清除指定用户的聊天上下文"""
    logger.info(f"已开启自动清除上下文功能, 尝试清除用户 {user_id} 的聊天上下文")
    try:
        with queue_lock:
            if user_id in chat_contexts:
                del chat_contexts[user_id]
                save_chat_contexts()
                logger.warning(f"已清除用户 {user_id} 的聊天上下文")
    except Exception as e:
        logger.error(f"清除聊天上下文失败: {str(e)}")

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
def needs_online_search(message: str, user_id: str) -> Optional[str]:
    """
    使用主 AI 判断用户消息是否需要联网搜索, 并返回需要搜索的内容. 

    参数:
        message (str): 用户的消息.
        user_id (str): 用户标识符 (用于日志).

    返回:
        Optional[str]: 如果需要联网搜索, 返回需要搜索的内容;否则返回 None.
    """
    if not ENABLE_ONLINE_API:  # 如果全局禁用, 直接返回 None
        return None

    # 构建用于检测的提示词
    detection_prompt = f"""
请判断以下用户消息是否明确需要查询当前, 实时或非常具体的外部信息(例如:{SEARCH_DETECTION_PROMPT}).
用户消息:"{message}"

如果需要联网搜索, 请回答 "需要联网", 并在下一行提供你认为需要搜索的内容.
如果不需要联网搜索(例如:常规聊天, 询问一般知识, 历史信息, 角色扮演对话等), 请只回答 "不需要联网".
请不要添加任何其他解释.
"""
    try:
        # 根据配置选择使用辅助模型或主模型
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"向辅助模型发送联网检测请求, 用户: {user_id}, 消息: '{message[:50]}...'")
            response = get_assistant_response(detection_prompt, f"online_detection_{user_id}")
        else:
            logger.info(f"向主 AI 发送联网检测请求, 用户: {user_id}, 消息: '{message[:50]}...'")
            response = get_deepseek_response(detection_prompt, user_id=f"online_detection_{user_id}", store_context=False)

        # 清理并判断响应
        cleaned_response = response.strip()
        if "</think>" in cleaned_response:
            cleaned_response = cleaned_response.split("</think>", 1)[1].strip()
        
        if ENABLE_ASSISTANT_MODEL:
            logger.info(f"辅助模型联网检测响应: '{cleaned_response}'")
        else:
            logger.info(f"主模型联网检测响应: '{cleaned_response}'")

        if "不需要联网" in cleaned_response:
            logger.info(f"用户 {user_id} 的消息不需要联网.")
            return None
        elif "需要联网" in cleaned_response:
            # 提取需要搜索的内容
            search_content = cleaned_response.split("\n", 1)[1].strip() if "\n" in cleaned_response else ""
            logger.info(f"检测到用户 {user_id} 的消息需要联网, 搜索内容: '{search_content}'")
            return search_content
        else:
            logger.warning(f"无法解析联网检测响应, 用户: {user_id}, 响应: '{cleaned_response}'")
            return None

    except Exception as e:
        logger.error(f"联网检测失败, 用户: {user_id}, 错误: {e}", exc_info=True)
        return None  # 出错时默认不需要联网

# --- 调用在线模型的函数 ---
def get_online_model_response(query: str, user_id: str) -> Optional[str]:
    """
    使用配置的在线 API 获取搜索结果. 

    参数:
        query (str): 要发送给在线模型的查询(通常是用户消息).
        user_id (str): 用户标识符 (用于日志).

    返回:
        Optional[str]: 在线 API 的回复内容, 如果失败则返回 None.
    """
    if not online_client: # 检查在线客户端是否已成功初始化
        logger.error(f"在线 API 客户端未初始化, 无法为用户 {user_id} 执行在线搜索.")
        return None

    # 获取当前时间并格式化为字符串
    current_time_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # 结合固定的提示词, 当前时间和用户查询
    online_query_prompt = f"请在互联网上查找相关信息, 忽略过时信息, 并给出简要的回答.\n{ONLINE_FIXED_PROMPT}\n当前时间:{current_time_str}\n\n{query}"

    try:
        logger.info(f"调用在线 API - 用户: {user_id}, 查询: '{query[:100]}...'")
        # 使用 online_client 调用在线模型
        response = online_client.chat.completions.create(
            model=ONLINE_MODEL,
            messages=[{"role": "user", "content": online_query_prompt}],
            temperature=ONLINE_API_TEMPERATURE,
            max_tokens=ONLINE_API_MAX_TOKEN,
            stream=False
        )

        if not response.choices or len(response.choices) == 0:
            logger.error(f"在线 API 返回了空的选择项, 用户: {user_id}")
            return None

        if not hasattr(response.choices[0], 'message') or not response.choices[0].message:
            logger.error(f"在线 API 响应无效，用户 {user_id}: message对象不存在")
            return None

        content = response.choices[0].message.content
        if content:
            reply = content.strip()
            # 清理回复, 去除思考过程
            if "</think>" in reply:
                reply = reply.split("</think>", 1)[1].strip()
            logger.info(f"在线 API 响应 (用户 {user_id}): {reply}")
            return reply
        return None

    except Exception as e:
        logger.error(f"调用在线 API 失败, 用户: {user_id}: {e}", exc_info=True)
        return "抱歉, 在线搜索功能暂时出错了."

def monitor_memory_usage():
    import psutil
    MEMORY_THRESHOLD = 328  # 内存使用阈值328MB
    while True:
        process = psutil.Process(os.getpid())
        memory_usage = process.memory_info().rss / 1024 / 1024  # MB
        logger.info(f"当前内存使用: {memory_usage:.2f} MB")
        if memory_usage > MEMORY_THRESHOLD:
            logger.warning(f"内存使用超过阈值 ({MEMORY_THRESHOLD} MB), 执行垃圾回收")
            import gc
            gc.collect()
        time.sleep(600)

def scheduled_restart_checker():
    """
    定时检查是否需要重启程序. 
    重启条件:
    1. 已达到RESTART_INTERVAL_HOURS的运行时间
    2. 在RESTART_INACTIVITY_MINUTES内没有活动, 或活动结束后又等待了RESTART_INACTIVITY_MINUTES
    3. 没有正在进行的短期提醒事件
    4. 没有即将到来(5分钟内)的长期提醒或每日重复提醒事件
    """
    global program_start_time, last_received_message_timestamp # 引用全局变量

    if not ENABLE_SCHEDULED_RESTART:
        logger.info("定时重启功能已禁用.")
        return

    logger.info(f"定时重启功能已启用.重启间隔: {RESTART_INTERVAL_HOURS} 小时, 不活跃期: {RESTART_INACTIVITY_MINUTES} 分钟.")

    restart_interval_seconds = RESTART_INTERVAL_HOURS * 3600
    inactivity_seconds = RESTART_INACTIVITY_MINUTES * 60

    if restart_interval_seconds <= 0:
        logger.error("重启间隔时间必须大于0, 定时重启功能将不会启动.")
        return
    
    # 初始化下一次检查重启的时间点
    next_restart_time = program_start_time + restart_interval_seconds
    restart_pending = False  # 标记是否处于待重启状态(已达到间隔时间但在等待不活跃期)

    while True:
        current_time = time.time()
        time_since_last_activity = current_time - last_received_message_timestamp
        
        # 准备重启的三个条件检查
        interval_reached = current_time >= next_restart_time or restart_pending
        inactive_enough = time_since_last_activity >= inactivity_seconds
        
        # 只有在准备重启时才检查提醒事件, 避免不必要的检查
        if interval_reached and inactive_enough:
            # 检查是否有正在进行的短期提醒
            has_active_short_reminders = False
            with timer_lock:
                if active_timers:
                    logger.info(f"当前有 {len(active_timers)} 个短期提醒进行中, 等待它们完成后再重启.")
                    has_active_short_reminders = True
            
            # 检查是否有即将到来的提醒(5分钟内)
            has_upcoming_reminders = False
            now = datetime.now()
            five_min_later = now + dt.timedelta(minutes=5)
            
            with recurring_reminder_lock:
                for reminder in recurring_reminders:
                    target_dt = None
                    
                    # 处理长期一次性提醒
                    if reminder.get('reminder_type') == 'one-off':
                        try:
                            target_dt = datetime.strptime(reminder.get('target_datetime_str'), '%Y-%m-%d %H:%M')
                        except (ValueError, TypeError):
                            continue
                    
                    # 处理每日重复提醒 - 需要结合当前日期计算今天的触发时间
                    elif reminder.get('reminder_type') == 'recurring':
                        try:
                            time_str = reminder.get('time_str')
                            if time_str:
                                # 解析时间字符串获取小时和分钟
                                reminder_time = datetime.strptime(time_str, '%H:%M').time()
                                # 结合当前日期构建完整的目标时间
                                target_dt = datetime.combine(now.date(), reminder_time)
                                
                                # 如果今天的触发时间已过, 检查明天的触发时间是否在5分钟内
                                # (极少情况:如果定时检查恰好在23:55-00:00之间, 且有0:00-0:05的提醒)
                                if target_dt < now:
                                    target_dt = datetime.combine(now.date() + dt.timedelta(days=1), reminder_time)
                        except (ValueError, TypeError):
                            continue
                    
                    # 检查目标时间是否在5分钟内
                    if target_dt and now <= target_dt <= five_min_later:
                        reminder_type = "长期一次性" if reminder.get('reminder_type') == 'one-off' else "每日重复"
                        display_time = target_dt.strftime('%Y-%m-%d %H:%M') if reminder.get('reminder_type') == 'one-off' else target_dt.strftime('%H:%M')
                        logger.info(f"检测到5分钟内即将执行的{reminder_type}提醒, 延迟重启.提醒时间: {display_time}")
                        has_upcoming_reminders = True
                        break
            
            # 如果没有提醒阻碍, 则可以重启
            if not has_active_short_reminders and not has_upcoming_reminders:
                logger.warning(f"满足重启条件:已运行约 {(current_time - program_start_time)/3600:.2f} 小时, 已持续 {time_since_last_activity/60:.1f} 分钟无活动, 且没有即将执行的提醒.准备重启程序...")
                try:
                    # --- 执行重启前的清理操作 ---
                    logger.info("定时重启前:保存聊天上下文...")
                    with queue_lock:
                        save_chat_contexts()
                    
                    # 保存用户计时器状态
                    if ENABLE_AUTO_MESSAGE:
                        logger.info("定时重启前:保存用户计时器状态...")
                        save_user_timers()
                    
                    if ENABLE_REMINDERS:
                        logger.info("定时重启前:保存提醒列表...")
                        with recurring_reminder_lock:
                            save_recurring_reminders()
                    
                    # 关闭异步HTTP日志处理器
                    if 'async_http_handler' in globals() and isinstance(async_http_handler, AsyncHTTPHandler):
                        logger.info("定时重启前:关闭异步HTTP日志处理器...")
                        async_http_handler.close()
                    
                    logger.info("定时重启前:执行最终临时文件清理...")
                    clean_up_temp_files()
                    
                    logger.info("正在执行重启...")
                    # 替换当前进程为新启动的 Python 脚本实例
                    os.execv(sys.executable, ['python'] + sys.argv)
                except Exception as e:
                    logger.error(f"执行重启操作时发生错误: {e}", exc_info=True)
                    # 如果重启失败, 推迟下一次检查, 避免短时间内连续尝试
                    restart_pending = False
                    next_restart_time = current_time + restart_interval_seconds 
                    logger.info(f"重启失败, 下一次重启检查时间推迟到: {datetime.fromtimestamp(next_restart_time).strftime('%Y-%m-%d %H:%M:%S')}")
            elif has_upcoming_reminders:
                # 有提醒即将执行, 延长10分钟后再检查
                logger.info(f"由于5分钟内有提醒将执行, 延长重启时间10分钟.")
                next_restart_time = current_time + 600  # 延长10分钟
                restart_pending = True  # 保持待重启状态
            else:
                # 有短期提醒正在进行, 稍后再检查
                logger.info(f"由于有短期提醒正在进行, 将在下一轮检查是否可以重启.")
                restart_pending = True  # 保持待重启状态
        elif interval_reached and not inactive_enough:
            # 已达到间隔时间但最近有活动, 设置待重启状态
            if not restart_pending:
                logger.info(f"已达到重启间隔({RESTART_INTERVAL_HOURS}小时), 但最近 {time_since_last_activity/60:.1f} 分钟内有活动, 将在 {RESTART_INACTIVITY_MINUTES} 分钟无活动后重启.")
                restart_pending = True
            # 不更新next_restart_time, 因为我们现在是等待不活跃期
        elif current_time >= next_restart_time and not restart_pending:
            # 第一次达到重启时间点
            logger.info(f"已达到计划重启检查点 ({RESTART_INTERVAL_HOURS}小时).距离上次活动: {time_since_last_activity/60:.1f}分钟 (不活跃阈值: {RESTART_INACTIVITY_MINUTES}分钟).")
            restart_pending = True  # 进入待重启状态
        
        # 每分钟检查一次条件
        time.sleep(60)

# 短期记忆定时任务调度器
def short_term_memory_scheduler():
    """每天到指定时间自动生成短期记忆 + 沉淀过期记忆"""
    from config import SHORT_TERM_MEMORY_TIME
    logger.info(f"短期记忆调度器启动，计划时间: 每天 {SHORT_TERM_MEMORY_TIME}")
    
    last_run_date = None
    
    while True:
        try:
            now = datetime.now()
            today_str = now.strftime('%Y-%m-%d')
            
            # 解析目标时间
            try:
                target_hour, target_minute = map(int, SHORT_TERM_MEMORY_TIME.split(':'))
            except:
                target_hour, target_minute = 2, 0
            
            # 检查是否到了执行时间且今天还没执行过
            if now.hour == target_hour and now.minute == target_minute and last_run_date != today_str:
                last_run_date = today_str
                logger.info("=== 短期记忆定时任务触发 ===")
                
                for user in user_names:
                    try:
                        from short_term_memory import daily_short_term_task
                        daily_short_term_task(user)
                    except Exception as e:
                        logger.error(f"用户 {user} 短期记忆任务失败: {e}", exc_info=True)
                
                logger.info("=== 短期记忆定时任务完成 ===")
        except Exception as e:
            logger.error(f"短期记忆调度器异常: {e}")
        
        time.sleep(60)  # 每分钟检查一次


# 发送心跳的函数
def send_heartbeat():
    """向Flask后端发送心跳信号"""
    heartbeat_url = f"{FLASK_SERVER_URL_BASE}/bot_heartbeat"
    payload = {
        'status': 'alive',
        'pid': os.getpid() # 发送当前进程PID, 方便调试
    }
    try:
        response = requests.post(heartbeat_url, json=payload, timeout=5)
        if response.status_code == 200:
            logger.debug(f"心跳发送成功至 {heartbeat_url} (PID: {os.getpid()})")
        else:
            logger.warning(f"发送心跳失败, 状态码: {response.status_code} (PID: {os.getpid()})")
    except requests.exceptions.RequestException as e:
        logger.error(f"发送心跳时发生网络错误: {e} (PID: {os.getpid()})")
    except Exception as e:
        logger.error(f"发送心跳时发生未知错误: {e} (PID: {os.getpid()})")


# 心跳线程函数
def heartbeat_thread_func():
    """心跳线程, 定期发送心跳，并检查配置文件变更"""
    logger.info(f"机器人心跳线程启动 (PID: {os.getpid()}), 每 {HEARTBEAT_INTERVAL} 秒发送一次心跳.")
    while True:
        send_heartbeat()
        # 每次心跳都检查 config.py 是否被修改
        check_config_reload()
        time.sleep(HEARTBEAT_INTERVAL)

# 保存用户计时器状态的函数
def save_user_timers():
    """将用户计时器状态保存到文件"""
    temp_file_path = USER_TIMERS_FILE + ".tmp"
    try:
        timer_data = {
            'user_timers': dict(user_timers),
            'user_wait_times': dict(user_wait_times)
        }
        with open(temp_file_path, 'w', encoding='utf-8') as f:
            json.dump(timer_data, f, ensure_ascii=False, indent=4)
        shutil.move(temp_file_path, USER_TIMERS_FILE)
        logger.info(f"用户计时器状态已保存到 {USER_TIMERS_FILE}")
    except Exception as e:
        logger.error(f"保存用户计时器状态失败: {e}", exc_info=True)
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except OSError:
                pass

# 加载用户计时器状态的函数
def load_user_timers():
    """从文件加载用户计时器状态"""
    global user_timers, user_wait_times
    try:
        if os.path.exists(USER_TIMERS_FILE):
            with open(USER_TIMERS_FILE, 'r', encoding='utf-8') as f:
                timer_data = json.load(f)
                if isinstance(timer_data, dict):
                    loaded_user_timers = timer_data.get('user_timers', {})
                    loaded_user_wait_times = timer_data.get('user_wait_times', {})
                    
                    # 验证并恢复有效的计时器状态
                    restored_count = 0
                    for user in user_names:
                        if (user in loaded_user_timers and user in loaded_user_wait_times and
                            isinstance(loaded_user_timers[user], (int, float)) and
                            isinstance(loaded_user_wait_times[user], (int, float))):
                            user_timers[user] = loaded_user_timers[user]
                            user_wait_times[user] = loaded_user_wait_times[user]
                            restored_count += 1
                            logger.debug(f"已恢复用户 {user} 的计时器状态")
                        else:
                            # 如果没有保存的状态或状态无效, 则初始化
                            reset_user_timer(user)
                            logger.debug(f"为用户 {user} 重新初始化计时器状态")
                    
                    logger.info(f"成功从 {USER_TIMERS_FILE} 恢复 {restored_count} 个用户的计时器状态")
                else:
                    logger.warning(f"{USER_TIMERS_FILE} 文件格式不正确, 将重新初始化所有计时器")
                    initialize_all_user_timers()
        else:
            logger.info(f"{USER_TIMERS_FILE} 未找到, 将初始化所有用户计时器")
            initialize_all_user_timers()
    except json.JSONDecodeError:
        logger.error(f"解析 {USER_TIMERS_FILE} 失败, 将重新初始化所有计时器")
        initialize_all_user_timers()
    except Exception as e:
        logger.error(f"加载用户计时器状态失败: {e}", exc_info=True)
        initialize_all_user_timers()

def initialize_all_user_timers():
    """初始化所有用户的计时器"""
    for user in user_names:
        reset_user_timer(user)
    logger.info("所有用户计时器已重新初始化")

# === 新增:全局锁 ===
is_sending_message_lock = threading.Lock()
can_send_messages_lock = threading.Lock()

def status_self_check():
    check_interval = 10
    # stuck_threshold = 60  # 超过60秒认为卡死
    # last_sending_time = [time.time()]
    while True:
        # 只检查can_send_messages
        with can_send_messages_lock:
            if not can_send_messages:
                # ✅ 修改点：检查是否正在识图
                with is_recognizing_image_lock:
                    if is_recognizing_image:
                        logger.debug("正在识别图片，暂停消息发送中...")
                    else:
                        logger.warning("can_send_messages为False, 检查是否卡死.")
        time.sleep(check_interval)

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

        # --- 启动窗口保活线程 ---
        logger.info("\033[32m启动窗口保活线程...\033[0m")
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