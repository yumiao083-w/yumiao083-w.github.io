# -*- coding: utf-8 -*-

# ***********************************************************************
# Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot.
# WeChatBot is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
# 
# WeChatBot is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with WeChatBot.  If not, see <http://www.gnu.org/licenses/>.
# ***********************************************************************

from flask import Flask, render_template, request, redirect, url_for, jsonify, session, Response
import re
import ast
import os
import subprocess
import psutil
import openai
import requests as http_requests
import tempfile
import shutil
from filelock import FileLock
from functools import wraps
import webbrowser
from threading import Timer
from flask import Flask
import logging
from queue import Queue, Empty
import time
import json
import threading
from datetime import datetime

app = Flask(__name__)

def safe_type_convert(value, target_type, default_value=None, field_name=""):
    """
    安全的类型转换函数，防止整数转换为字符串
    
    Args:
        value: 要转换的值
        target_type: 目标类型 (int, float, bool)
        default_value: 转换失败时的默认值
        field_name: 字段名，用于日志记录
    
    Returns:
        转换后的值或默认值
    """
    try:
        str_value = str(value).strip()
        
        if target_type == int:
            if str_value and str_value.isdigit():
                return int(str_value)
            elif str_value == '':
                return 0 if default_value is None else default_value
            else:
                if field_name:
                    app.logger.warning(f"配置项 {field_name} 的值 '{value}' 包含非数字字符，使用默认值。")
                return default_value if default_value is not None else 0
                
        elif target_type == float:
            if str_value:
                import re
                if re.match(r'^-?\d+(\.\d+)?$', str_value):
                    return float(str_value)
                else:
                    if field_name:
                        app.logger.warning(f"配置项 {field_name} 的值 '{value}' 不是有效的数字格式，使用默认值。")
                    return default_value if default_value is not None else 0.0
            else:
                return 0.0 if default_value is None else default_value
                
        elif target_type == bool:
            return str_value.lower() in ('on', 'true', '1', 'yes')
            
    except (ValueError, TypeError) as e:
        if field_name:
            app.logger.warning(f"配置项 {field_name} 类型转换失败: {e}，使用默认值。")
        return default_value if default_value is not None else (0 if target_type == int else 0.0 if target_type == float else False)
    
    return value

def validate_config_types(config_path):
    """
    验证config.py中的数据类型是否正确
    """
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 检查是否有字符串形式的数字
        import re
        
        # 查找可能的问题配置项
        issues = []
        
        # 检查应该是整数但被保存为字符串的配置项
        # --- 修改：移除了 'MAX_MEMORY_NUMBER' ---
        int_fields = ['MAX_GROUPS', 'MAX_TOKEN', 'QUEUE_WAITING_TIME', 'EMOJI_SENDING_PROBABILITY', 
                     'MAX_MESSAGE_LOG_ENTRIES', 'PORT', 'ONLINE_API_MAX_TOKEN',
                     'REQUESTS_TIMEOUT', 'MAX_WEB_CONTENT_LENGTH', 'RESTART_INACTIVITY_MINUTES',
                     'GROUP_CHAT_RESPONSE_PROBABILITY', 'ASSISTANT_MAX_TOKEN']
        
        # 检查应该是浮点数但被保存为字符串的配置项  
        float_fields = ['TEMPERATURE', 'MOONSHOT_TEMPERATURE', 'MIN_COUNTDOWN_HOURS', 'MAX_COUNTDOWN_HOURS',
                       'AVERAGE_TYPING_SPEED', 'RANDOM_TYPING_SPEED_MIN', 'RANDOM_TYPING_SPEED_MAX',
                       'ONLINE_API_TEMPERATURE', 'RESTART_INTERVAL_HOURS', 'ASSISTANT_TEMPERATURE']
        
        for field in int_fields:
            pattern = rf'{field}\s*=\s*[\'"](\d+)[\'"]'
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"{field} 被保存为字符串 '{matches[0]}'，应为整数 {matches[0]}")
        
        for field in float_fields:
            pattern = rf'{field}\s*=\s*[\'"](\d+\.?\d*)[\'"]'
            matches = re.findall(pattern, content)
            if matches:
                issues.append(f"{field} 被保存为字符串 '{matches[0]}'，应为浮点数 {matches[0]}")
        
        if issues:
            app.logger.warning(f"配置文件类型验证发现问题: {'; '.join(issues)}")
            return False
        
        return True
        
    except Exception as e:
        app.logger.error(f"配置文件类型验证失败: {e}")
        return False

app.secret_key = os.urandom(24).hex()  # 48位十六进制字符串
bot_process = None

# 全局日志队列
log_queue = Queue()

CHAT_CONTEXTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'chat_contexts.json')
CHAT_CONTEXTS_LOCK_FILE = CHAT_CONTEXTS_FILE + '.lock'

MEMORY_SUMMARIES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'Memory_Core')
MEMORY_SUMMARIES_LOCK_FILE = MEMORY_SUMMARIES_DIR + '.lock'

SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'settings.json')
SETTINGS_LOCK_FILE = SETTINGS_FILE + '.lock'

PROVIDERS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'api_providers.json')
PROVIDERS_LOCK_FILE = PROVIDERS_FILE + '.lock'

def parse_dynamic_settings():
    """从 settings.json 读取动态设置"""
    # 提供默认值
    settings = {'emoji_tag_max_length': 10}
    if not os.path.exists(SETTINGS_FILE):
        return settings
    try:
        with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        # 安全地获取值并转换类型
        settings['emoji_tag_max_length'] = int(data.get('emoji_tag_max_length', 10))
    except (json.JSONDecodeError, ValueError, IOError) as e:
        app.logger.error(f"读取动态设置文件 ({SETTINGS_FILE}) 失败: {e}, 将使用默认值。")
    return settings

def save_dynamic_settings(new_settings_data):
    """使用文件锁安全地保存动态设置到 settings.json"""
    with FileLock(SETTINGS_LOCK_FILE):
        try:
            current_settings = {}
            if os.path.exists(SETTINGS_FILE):
                with open(SETTINGS_FILE, 'r', encoding='utf-8') as f:
                    # 避免空文件导致json解析错误
                    content = f.read()
                    if content:
                        current_settings = json.loads(content)
            
            # 更新设置
            current_settings.update(new_settings_data)

            with open(SETTINGS_FILE, 'w', encoding='utf-8') as f:
                json.dump(current_settings, f, ensure_ascii=False, indent=4)
            return True, "设置已保存"
        except Exception as e:
            app.logger.error(f"保存动态设置文件 ({SETTINGS_FILE}) 失败: {e}")
            return False, str(e)

last_heartbeat_time = 0  # 上次收到心跳的时间戳
HEARTBEAT_TIMEOUT = 15   # 心跳超时阈值（秒），应大于 bot.py 的 HEARTBEAT_INTERVAL
current_bot_pid = None

def get_chat_context_users():
    """从 chat_contexts.json 读取用户列表 (即顶级键)"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return []
    try:
        with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        return list(data.keys())
    except (json.JSONDecodeError, IOError) as e:
        app.logger.error(f"读取 chat_contexts.json 失败: {e}")
        return []

def get_memory_summary_users():
    """从 Memory_Core 文件夹读取用户列表 (即unified_memory json文件名)"""
    if not os.path.isdir(MEMORY_SUMMARIES_DIR):
        return []
    try:
        # 只返回以_unified_memory.json结尾的文件
        files = [f for f in os.listdir(MEMORY_SUMMARIES_DIR) if f.endswith('_unified_memory.json')]
        unique_users = set()
        for f in files:
            # 去掉 _unified_memory.json 后缀，得到用户标识符
            username = f.replace('_unified_memory.json', '')
            unique_users.add(username)
        return sorted(list(unique_users))
    except OSError as e:
        app.logger.error(f"读取 Memory_Core 目录失败: {e}")
        return []

@app.route('/login', methods=['GET', 'POST'])
def login():
    config = parse_config()
    if not config.get('ENABLE_LOGIN_PASSWORD', False):
        return redirect(url_for('index'))

    if request.method == 'POST':
        password = request.form.get('password', '')
        stored_pwd = config.get('LOGIN_PASSWORD', '')
        
        if password == stored_pwd:
            session['logged_in'] = True
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error="密码错误")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    return redirect(url_for('login'))

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        config = parse_config()
        if config.get('ENABLE_LOGIN_PASSWORD', False):
            if not session.get('logged_in'):
                return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function


# =========================================================================
# 新版桌面入口
# =========================================================================

@app.route('/home')
@login_required
def home():
    return render_template('home.html')


@app.route('/panel/<name>')
@login_required
def panel(name):
    """子页面路由"""
    valid_panels = ['api', 'reply', 'chat', 'memory', 'prompt', 'settings']
    if name not in valid_panels:
        return redirect(url_for('home'))
    config = parse_config()
    return render_template(f'panel_{name}.html', config=config)


@app.route('/api/save_section', methods=['POST'])
@login_required
def save_section():
    """通用的按区块保存配置 API（各子页面共用）"""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': '请求数据为空'}), 400

        fields = req.get('fields', {})
        if not fields:
            return jsonify({'error': '没有要保存的字段'}), 400

        # 类型转换：前端传来的都是字符串/布尔，需要匹配 config.py 原始类型
        config = parse_config()
        converted = {}
        for key, value in fields.items():
            original = config.get(key)
            if original is None:
                converted[key] = value
            elif isinstance(original, bool):
                converted[key] = value if isinstance(value, bool) else str(value).lower() in ('true', '1', 'on')
            elif isinstance(original, int):
                try:
                    converted[key] = int(value)
                except (ValueError, TypeError):
                    converted[key] = original
            elif isinstance(original, float):
                try:
                    converted[key] = float(value)
                except (ValueError, TypeError):
                    converted[key] = original
            else:
                converted[key] = str(value)

        update_config(converted)
        return jsonify({'status': 'success', 'message': f'已保存 {len(converted)} 项配置'})
    except Exception as e:
        app.logger.error(f"保存配置区块失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/start_bot', methods=['POST'])
def start_bot():
    global bot_process
    if bot_process is None or bot_process.poll() is not None:
        # 如果目录下存在 user_timers.json 则删除
        user_timers_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'user_timers.json')
        if os.path.exists(user_timers_path):
            try:
                os.remove(user_timers_path)
            except Exception as e:
                app.logger.warning(f"重置主动消息定时器失败: {e}")

        bot_dir = os.path.dirname(os.path.abspath(__file__))
        
        bot_py = os.path.join(bot_dir, 'bot.py')
        bot_exe = os.path.join(bot_dir, 'bot.exe')
        
        if os.path.exists(bot_py):
            cmd = ['python', bot_py]
        elif os.path.exists(bot_exe):
            cmd = [bot_exe]
        else:
            return {'error': 'No bot executable found'}, 404

        creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == 'nt' else 0
        bot_process = subprocess.Popen(
            cmd,
            creationflags=creation_flags
        )
    return {'status': 'started'}, 200

@app.route('/stop_bot', methods=['POST'])
def stop_bot():
    global bot_process, last_heartbeat_time, current_bot_pid
    # 检查状态时，也考虑 current_bot_pid 是否指示有活跃进程
    is_considered_running = False
    if bot_process and bot_process.poll() is None:
        is_considered_running = True
    elif (time.time() - last_heartbeat_time) < HEARTBEAT_TIMEOUT and current_bot_pid is not None:
        try:
            if psutil.pid_exists(current_bot_pid): # 确保PID对应的进程还存在
                 is_considered_running = True
        except Exception: # psutil.pid_exists 可能会抛出异常，例如权限问题
            pass

    if not is_considered_running:
        app.logger.info("尝试停止机器人，但根据进程对象和心跳判断，机器人似乎已停止。")
        # 即使如此，也调用stop_bot_process来清理状态
        stop_bot_process(pid_to_kill=current_bot_pid if current_bot_pid else (bot_process.pid if bot_process else None))
        return {'status': 'stopped'}, 200
    else:
        pid_from_flask_process = bot_process.pid if bot_process else None
        # 优先使用 current_bot_pid，因为它更可能是最新的
        # 如果 current_bot_pid 和 flask 记录的 pid 不同，且 flask 的 pid 进程也存在，都尝试杀掉
        pids_to_attempt_kill = set()
        if current_bot_pid:
            pids_to_attempt_kill.add(current_bot_pid)
        if pid_from_flask_process:
            pids_to_attempt_kill.add(pid_from_flask_process)

        app.logger.info(f"准备停止机器人，目标PID(s): {pids_to_attempt_kill}")
        for pid in pids_to_attempt_kill:
            stop_bot_process(pid_to_kill=pid) # 传入要杀死的PID

        # 最终状态由 stop_bot_process 设置 current_bot_pid 和 last_heartbeat_time
        return {'status': 'stopped'}, 200
    
@app.route('/bot_status')
def bot_status():
    global bot_process, last_heartbeat_time, current_bot_pid
    
    process_alive_via_flask_obj = bot_process is not None and bot_process.poll() is None
    heartbeat_is_recent = (time.time() - last_heartbeat_time) < HEARTBEAT_TIMEOUT
    
    # 新增：检查 current_bot_pid 对应的进程是否实际存活
    process_alive_via_current_pid = False
    if current_bot_pid is not None:
        try:
            if psutil.pid_exists(current_bot_pid):
                process_alive_via_current_pid = True 
        except psutil.Error:
            pass

    current_status = "stopped"

    if process_alive_via_flask_obj:
        current_status = "running"
    elif heartbeat_is_recent and process_alive_via_current_pid: # 优先检查通过PID确认的存活
        current_status = "running"
    elif heartbeat_is_recent and not process_alive_via_current_pid and current_bot_pid is not None:
        app.logger.warning(f"Bot status: Heartbeat recent, but PID {current_bot_pid} does not exist. Marking as stopped for now. Last heartbeat: {time.time() - last_heartbeat_time:.1f}s ago")
        current_status = "stopped" # 倾向于保守
    elif heartbeat_is_recent : # 心跳最近，但没有 current_bot_pid 信息 (例如 bot.py 未发送PID)
        current_status = "running" # 保持原逻辑：心跳最近则认为运行

    return {"status": current_status}

@app.route('/submit_config', methods=['POST'])
@login_required
def submit_config():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再保存配置'}), 400
    try:
        if not request.form:
            return jsonify({'error': '空的表单提交'}), 400
        
        current_config_before_update = parse_config()
        old_listen_list_map = {item[0]: item[1] for item in current_config_before_update.get('LISTEN_LIST', []) if len(item) >= 2}

        new_values_for_config_py = {}

        nicknames_from_form = request.form.getlist('nickname')
        prompt_files_from_form = request.form.getlist('prompt_file')
        auto_message_flags = request.form.getlist('auto_message_enabled')
        
        processed_listen_list = []
        if nicknames_from_form and prompt_files_from_form and len(nicknames_from_form) == len(prompt_files_from_form):
            for i, (nick, pf) in enumerate(zip(nicknames_from_form, prompt_files_from_form)):
                nick_stripped = nick.strip()
                pf_stripped = pf.strip()
                if nick_stripped and pf_stripped: 
                    auto_enabled = 'auto_msg_' + str(i) in auto_message_flags
                    processed_listen_list.append([nick_stripped, pf_stripped, auto_enabled])
        new_values_for_config_py['LISTEN_LIST'] = processed_listen_list
        
        new_listen_list_map = {item[0]: item[1] for item in processed_listen_list}
        
        users_whose_prompt_changed = []
        for nickname, new_prompt in new_listen_list_map.items():
            if nickname in old_listen_list_map and old_listen_list_map[nickname] != new_prompt:
                users_whose_prompt_changed.append(nickname)

        boolean_fields = [
            'ENABLE_IMAGE_RECOGNITION', 'ENABLE_EMOJI_RECOGNITION',
            'ENABLE_EMOJI_SENDING', 'ENABLE_AUTO_MESSAGE', 'ENABLE_MEMORY',
            'UPLOAD_MEMORY_TO_AI', 'ENABLE_LOGIN_PASSWORD', 'ENABLE_REMINDERS',
            'ALLOW_REMINDERS_IN_QUIET_TIME', 'USE_VOICE_CALL_FOR_REMINDERS',
            'ENABLE_ONLINE_API', 'SEPARATE_ROW_SYMBOLS','ENABLE_SCHEDULED_RESTART',
            'ENABLE_GROUP_AT_REPLY', 'ENABLE_GROUP_KEYWORD_REPLY','GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY', 'REMOVE_PARENTHESES',
            'ENABLE_ASSISTANT_MODEL', 'USE_ASSISTANT_FOR_MEMORY_SUMMARY',
            'IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE', 'ENABLE_SENSITIVE_CONTENT_CLEARING',
            'ENABLE_GROUP_AT_REPLY_IN_REPLIES'
        ]
        for field in boolean_fields:
            new_values_for_config_py[field] = field in request.form

        for key_from_form in request.form:
            if key_from_form in ['nickname', 'prompt_file'] or key_from_form in boolean_fields:
                continue 

            value_from_form = request.form[key_from_form].strip()
            
            if key_from_form == 'GROUP_KEYWORD_LIST':
                if value_from_form:
                    normalized_value = re.sub(r'，|\s+', ',', value_from_form)
                    keywords_list = [kw.strip() for kw in normalized_value.split(',') if kw.strip()]
                    new_values_for_config_py[key_from_form] = keywords_list
                else:
                    new_values_for_config_py[key_from_form] = []
                continue

            if key_from_form in current_config_before_update:
                original_type_source = current_config_before_update[key_from_form]
                if isinstance(original_type_source, bool):
                    new_values_for_config_py[key_from_form] = (value_from_form.lower() == 'true')
                elif key_from_form in ["MIN_COUNTDOWN_HOURS", "MAX_COUNTDOWN_HOURS", "AVERAGE_TYPING_SPEED", "RANDOM_TYPING_SPEED_MIN", "RANDOM_TYPING_SPEED_MAX", "TEMPERATURE", "MOONSHOT_TEMPERATURE", "ONLINE_API_TEMPERATURE", "ASSISTANT_TEMPERATURE", "RESTART_INTERVAL_HOURS"]: 
                    try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value:
                            # 验证是否为有效的数字格式
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                # 如果不是有效数字格式，保留原值
                                new_values_for_config_py[key_from_form] = original_type_source
                                app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values_for_config_py[key_from_form] = 0.0
                    except (ValueError, TypeError) as e: 
                        new_values_for_config_py[key_from_form] = original_type_source 
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, int) or key_from_form in ["GROUP_CHAT_RESPONSE_PROBABILITY", "RESTART_INACTIVITY_MINUTES", "ASSISTANT_MAX_TOKEN"]:
                    try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 0
                        else:
                            # 如果包含非数字字符，保留原值
                            new_values_for_config_py[key_from_form] = original_type_source
                            app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已保留旧值。")
                    except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, float):
                     try:
                        # 先确保值是字符串类型，然后进行转换
                        str_value = str(value_from_form).strip()
                        if str_value:
                            # 验证是否为有效的数字格式
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                # 如果不是有效数字格式，保留原值
                                new_values_for_config_py[key_from_form] = original_type_source
                                app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values_for_config_py[key_from_form] = 0.0
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")
                elif isinstance(original_type_source, list):
                    try:
                        evaluated_list = ast.literal_eval(value_from_form)
                        if isinstance(evaluated_list, list):
                            new_values_for_config_py[key_from_form] = evaluated_list
                        else:
                            new_values_for_config_py[key_from_form] = original_type_source
                            app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 解析后不是列表，已保留旧值。")
                    except:
                        new_values_for_config_py[key_from_form] = original_type_source
                        app.logger.warning(f"配置项 {key_from_form} 的值 '{value_from_form}' 无法解析为列表，已保留旧值。")
                else: 
                    new_values_for_config_py[key_from_form] = value_from_form
            else: 
                if key_from_form == "GROUP_CHAT_RESPONSE_PROBABILITY":
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 0
                        else:
                            new_values_for_config_py[key_from_form] = 100
                            app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已设为默认值100。")
                    except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 100
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已设为默认值100。错误: {e}")
                elif key_from_form == "RESTART_INACTIVITY_MINUTES":
                     try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values_for_config_py[key_from_form] = int(str_value)
                        elif str_value == '':
                            new_values_for_config_py[key_from_form] = 15
                        else:
                            new_values_for_config_py[key_from_form] = 15
                            app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 包含非数字字符，已设为默认值15。")
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 15 
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为整数，已设为默认值15。错误: {e}")

                elif key_from_form == "RESTART_INTERVAL_HOURS":
                     try:
                        str_value = str(value_from_form).strip()
                        if str_value:
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values_for_config_py[key_from_form] = float(str_value)
                            else:
                                new_values_for_config_py[key_from_form] = 2.0
                                app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 不是有效的数字格式，已设为默认值2.0。")
                        else:
                            new_values_for_config_py[key_from_form] = 2.0
                     except (ValueError, TypeError) as e:
                        new_values_for_config_py[key_from_form] = 2.0
                        app.logger.warning(f"新配置项 {key_from_form} 的值 '{value_from_form}' 无法转换为浮点数，已设为默认值2.0。错误: {e}")
                else:
                    new_values_for_config_py[key_from_form] = value_from_form
        
        update_config(new_values_for_config_py)
        
        # 验证配置文件类型正确性
        script_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(script_dir, 'config.py')
        validate_config_types(config_path)

        # 2024-05-24: 新增 - 在用户切换Prompt时，执行一次性的旧格式上下文迁移
        if users_whose_prompt_changed:
            with FileLock(CHAT_CONTEXTS_LOCK_FILE):
                try:
                    if os.path.exists(CHAT_CONTEXTS_FILE):
                        # 使用'r+'模式读取并准备写入
                        with open(CHAT_CONTEXTS_FILE, 'r+', encoding='utf-8') as f:
                            content = f.read()
                            if not content:
                                chat_data = {}
                            else:
                                chat_data = json.loads(content)
                            
                            modified = False
                            # 获取切换前后的prompt映射
                            old_prompt_map = {item[0]: item[1] for item in current_config_before_update.get('LISTEN_LIST', [])}

                            for user_to_migrate in users_whose_prompt_changed:
                                user_data = chat_data.get(user_to_migrate)
                                # 只处理旧格式的列表类型数据
                                if isinstance(user_data, list):
                                    old_prompt = old_prompt_map.get(user_to_migrate)
                                    if old_prompt:
                                        app.logger.info(f"检测到用户 '{user_to_migrate}' 的旧格式上下文，将在切换角色时自动迁移到与旧角色 '{old_prompt}' 关联。")
                                        chat_data[user_to_migrate] = {old_prompt: user_data}
                                        modified = True
                                    else:
                                        app.logger.warning(f"无法为用户 '{user_to_migrate}' 迁移旧格式上下文，因为找不到其旧的Prompt配置。")

                            # 如果数据被修改，则写回文件
                            if modified:
                                f.seek(0)
                                json.dump(chat_data, f, ensure_ascii=False, indent=4)
                                f.truncate()
                except (json.JSONDecodeError, IOError) as e:
                    app.logger.error(f"迁移因Prompt变更导致的聊天上下文时出错: {e}")
                    
        return '', 204 
    except Exception as e:
        app.logger.error(f"配置保存失败: {str(e)}")
        return jsonify({'error': f'配置保存失败: {str(e)}'}), 500

def stop_bot_process(pid_to_kill=None):
    global bot_process, last_heartbeat_time, current_bot_pid
    
    process_killed_successfully = False

    if pid_to_kill:
        try:
            if psutil.pid_exists(pid_to_kill):
                bot_psutil = psutil.Process(pid_to_kill)
                app.logger.info(f"尝试终止PID为 {pid_to_kill} 的机器人进程...")
                bot_psutil.terminate()
                bot_psutil.wait(timeout=5) # 等待进程终止
                app.logger.info(f"通过 terminate 成功停止了PID {pid_to_kill}。")
                process_killed_successfully = True
            else:
                app.logger.info(f"PID {pid_to_kill} 指定的进程不存在。")
                process_killed_successfully = True # 认为已停止
        except psutil.NoSuchProcess:
            app.logger.info(f"尝试终止PID {pid_to_kill} 时，进程已不存在。")
            process_killed_successfully = True # 认为已停止
        except psutil.TimeoutExpired: # psutil.TimeoutExpired
            app.logger.warning(f"Terminate PID {pid_to_kill} 超时，尝试 kill。")
            try:
                if psutil.pid_exists(pid_to_kill): # 再次确认存在
                    bot_psutil_kill = psutil.Process(pid_to_kill)
                    bot_psutil_kill.kill()
                    bot_psutil_kill.wait(timeout=3)
                    app.logger.info(f"通过 kill 成功停止了PID {pid_to_kill}。")
                    process_killed_successfully = True
            except psutil.NoSuchProcess:
                 app.logger.info(f"尝试 kill PID {pid_to_kill} 时，进程已不存在。")
                 process_killed_successfully = True
            except Exception as e_kill:
                app.logger.error(f"Kill PID {pid_to_kill} 失败: {e_kill}")
        except Exception as e:
            app.logger.error(f"停止PID {pid_to_kill} 时发生错误: {e}")

    # 如果被杀死的PID是Flask自己启动的进程，则清空bot_process
    if bot_process and pid_to_kill == bot_process.pid and process_killed_successfully:
        app.logger.info(f"清空 Flask 维护的 bot_process 对象 (原PID: {bot_process.pid})。")
        bot_process = None
    
    # 如果被杀死的PID是当前记录的机器人PID，则清空current_bot_pid
    if current_bot_pid and pid_to_kill == current_bot_pid and process_killed_successfully:
        app.logger.info(f"清空 current_bot_pid (原PID: {current_bot_pid})。")
        current_bot_pid = None

    last_heartbeat_time = 0
    if not current_bot_pid and not bot_process: # 确保如果所有已知进程句柄都清了，才彻底标记
        app.logger.info("所有已知的机器人进程句柄均已清理。重置心跳时间。")
    elif current_bot_pid:
        app.logger.warning(f"调用 stop_bot_process 后，current_bot_pid ({current_bot_pid}) 仍有值。可能存在未完全停止的实例或状态不同步。但心跳已重置。")

@app.route('/bot_heartbeat', methods=['POST'])
def bot_heartbeat():
    global last_heartbeat_time, current_bot_pid
    try:
        last_heartbeat_time = time.time()
        data = request.get_json()
        
        if data and 'pid' in data:
            received_pid = data.get('pid')
            if received_pid and isinstance(received_pid, int):
                if current_bot_pid != received_pid:
                    app.logger.info(f"Bot PID updated via heartbeat: old={current_bot_pid}, new={received_pid}")
                    current_bot_pid = received_pid
            else:
                app.logger.warning(f"Received heartbeat with invalid PID: {received_pid}")
        else:
            app.logger.debug("Received heartbeat without PID information.")

        return jsonify({'status': 'heartbeat_received'}), 200
    except Exception as e:
        app.logger.error(f"Error processing heartbeat: {e}")
        current_bot_pid = None
        return jsonify({'error': 'Failed to process heartbeat'}), 500

def parse_config():
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')
    config = {}
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # 使用exec执行整个config.py文件，这样可以正确处理多行结构
        global_dict = {}
        local_dict = {}
        exec(content, global_dict, local_dict)
        
        # 从执行结果中提取所有大写的配置变量
        for key, value in local_dict.items():
            if key.isupper():  # 只保留全大写的配置变量
                config[key] = value
                
        return config
    except FileNotFoundError:
        raise Exception(f"配置文件不存在于: {config_path}")
    except Exception as e:
        # 如果exec失败，回退到原来的逐行解析方法
        app.logger.warning(f"使用exec解析配置文件失败，回退到逐行解析: {e}")
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                    if match:
                        var_name = match.group(1)
                        var_value_str = match.group(2)
                        try:
                            var_value = ast.literal_eval(var_value_str)
                            config[var_name] = var_value
                        except:
                            config[var_name] = var_value_str
            return config
        except FileNotFoundError:
            raise Exception(f"配置文件不存在于: {config_path}")

def update_config(new_values):
    """
    更新配置文件内容，确保文件写入安全性和原子性，避免文件被清空或损坏。
    """
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')
    lock_path = config_path + '.lock'  # 文件锁路径

    # 使用文件锁，确保只有一个进程/线程能操作 config.py
    with FileLock(lock_path):
        try:
            # 读取现有配置文件内容
            with open(config_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()

            new_lines = []
            for line in lines:
                line_stripped = line.strip()
                # 保留注释或空行
                if line_stripped.startswith('#') or not line_stripped:
                    new_lines.append(line)
                    continue

                # 匹配配置项的键值对
                match = re.match(r'^\s*(\w+)\s*=.*', line)
                if match:
                    var_name = match.group(1)
                    # 如果新配置中包含此变量，更新其值
                    if var_name in new_values:
                        value = new_values[var_name]
                        new_line = f"{var_name} = {repr(value)}\n"
                        new_lines.append(new_line)
                    else:
                        # 保留未修改的变量
                        new_lines.append(line)
                else:
                    # 如果行不符合格式，则直接保留
                    new_lines.append(line)

            # 写入临时文件，确保写入成功后再替换原文件
            with tempfile.NamedTemporaryFile('w', delete=False, dir=script_dir, encoding='utf-8') as temp_file:
                temp_file_name = temp_file.name
                temp_file.writelines(new_lines)

            # 替换原配置文件
            shutil.move(temp_file_name, config_path)
        except Exception as e:
            # 捕获并记录异常，以便排查问题
            raise Exception(f"更新配置文件失败: {e}")

@app.route('/quick_start', methods=['GET', 'POST'])
@login_required
def quick_start():
    if request.method == 'POST':
        try:
            config = parse_config()
            new_values = {}

            api_provider = request.form.get('quick_start_api_provider', 'weapis')
            api_key = request.form.get('quick_start_api_key', '').strip()

            keys_to_clear_for_non_weapis = [
                'MOONSHOT_API_KEY', 'ONLINE_API_KEY',
                'MOONSHOT_BASE_URL', 'ONLINE_BASE_URL',
                'MOONSHOT_MODEL', 'ONLINE_MODEL'
            ]

            if api_provider == 'weapis':
                if api_key:
                    new_values['DEEPSEEK_API_KEY'] = api_key
                    new_values['MOONSHOT_API_KEY'] = api_key
                    new_values['ONLINE_API_KEY'] = api_key
                new_values['DEEPSEEK_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['MOONSHOT_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['ONLINE_BASE_URL'] = 'https://vg.v1api.cc/v1'
                new_values['MOONSHOT_MODEL'] = 'gpt-4o'
                new_values['ONLINE_MODEL'] = 'net-gpt-4o-mini'
                if not config.get('MODEL','').strip():
                    new_values['MODEL'] = 'deepseek-ai/DeepSeek-V3'
                new_values['ENABLE_ONLINE_API'] = 'ENABLE_ONLINE_API' in request.form
            
            else:
                if api_provider == 'siliconflow':
                    new_values['DEEPSEEK_BASE_URL'] = 'https://api.siliconflow.cn/v1/'
                elif api_provider == 'deepseek_official':
                    new_values['DEEPSEEK_BASE_URL'] = 'https://api.deepseek.com'
                elif api_provider == 'other':
                    custom_base_url = request.form.get('quick_start_custom_base_url', '').strip()
                    if custom_base_url:
                        new_values['DEEPSEEK_BASE_URL'] = custom_base_url
                    else:
                        new_values['DEEPSEEK_BASE_URL'] = ""
                
                if api_key:
                    new_values['DEEPSEEK_API_KEY'] = api_key
                
                for key_to_clear in keys_to_clear_for_non_weapis:
                    new_values[key_to_clear] = "" 
                new_values['ENABLE_ONLINE_API'] = False

            nicknames = request.form.getlist('nickname')
            prompt_files_form = request.form.getlist('prompt_file')
            auto_message_flags = request.form.getlist('auto_message_enabled')
            new_values['LISTEN_LIST'] = [
                [nick.strip(), pf.strip(), 'auto_msg_' + str(i) in auto_message_flags]
                for i, (nick, pf) in enumerate(zip(nicknames, prompt_files_form))
                if nick.strip() and pf.strip()
            ]
            new_values['ENABLE_AUTO_MESSAGE'] = 'ENABLE_AUTO_MESSAGE' in request.form
            
            update_config(new_values)
            return redirect(url_for('index'))
        except Exception as e:
            app.logger.error(f"快速配置保存错误: {e}")
            return redirect(url_for('quick_start'))

    try:
        config = parse_config()
        prompt_files_dir = 'prompts'
        if not os.path.exists(prompt_files_dir):
            os.makedirs(prompt_files_dir)
        prompt_files_list = [f[:-3] for f in os.listdir(prompt_files_dir) if f.endswith('.md')]
        
        current_api_provider = 'weapis'
        current_custom_base_url = ''
        
        deepseek_url = config.get('DEEPSEEK_BASE_URL', '')
        
        is_weapis_setup = (
            deepseek_url == 'https://vg.v1api.cc/v1' and
            config.get('MOONSHOT_BASE_URL') == 'https://vg.v1api.cc/v1' and
            config.get('ONLINE_BASE_URL') == 'https://vg.v1api.cc/v1'
        )

        if is_weapis_setup:
            current_api_provider = 'weapis'
        elif deepseek_url == 'https://api.siliconflow.cn/v1/':
            current_api_provider = 'siliconflow'
        elif deepseek_url == 'https://api.deepseek.com':
            current_api_provider = 'deepseek_official'
        elif deepseek_url and deepseek_url != 'https://vg.v1api.cc/v1': 
            current_api_provider = 'other'
            current_custom_base_url = deepseek_url

        return render_template('quick_start.html',
                               config=config,
                               prompt_files=prompt_files_list,
                               current_api_provider=current_api_provider,
                               current_custom_base_url=current_custom_base_url)
    except Exception as e:
        app.logger.error(f"加载快速配置页面错误: {e}")
        return "加载快速配置页面错误，请检查日志。"

@app.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # 在处理 POST 或渲染模板之前检查 API KEY
    current_config_check = parse_config()
    # 检查是否从 quick_start 页面明确跳过
    was_skipped = request.args.get('skipped') == 'true'

    if not current_config_check.get('DEEPSEEK_API_KEY', '').strip():
        # 只有当不是明确跳过，并且是GET请求时，才重定向到 quick_start
        if request.method == 'GET' and not was_skipped:
             return redirect(url_for('quick_start'))

    if request.method == 'POST':
        try:
            config = parse_config()
            new_values = {}

             # 处理二维数组的LISTEN_LIST
            nicknames = request.form.getlist('nickname')
            prompt_files = request.form.getlist('prompt_file')
            auto_message_flags = request.form.getlist('auto_message_enabled')
            new_values['LISTEN_LIST'] = [
                [nick.strip(), pf.strip(), 'auto_msg_' + str(i) in auto_message_flags] 
                for i, (nick, pf) in enumerate(zip(nicknames, prompt_files)) 
                if nick.strip() and pf.strip()
            ]

            # 处理其他字段
            submitted_fields = set(request.form.keys()) - {'listen_list'} # listen_list 已处理
            # 修正: submitted_fields应为 {'nickname', 'prompt_file', 'auto_message_enabled'}
            submitted_fields = set(request.form.keys()) - {'nickname', 'prompt_file', 'auto_message_enabled'}

            for var in submitted_fields:
                if var not in config and not var.startswith('temp_'): # 忽略不存在于config中的字段, 但保留temp_字段
                    # 如果是 quick_start_api_key 这样的临时字段，则忽略
                    if var == 'quick_start_api_key':
                        continue
                    # 对于其他未知字段，可以打印警告或跳过
                    app.logger.warning(f"表单中存在未知配置项: {var}, 已忽略。")
                    continue
                
                original_value = config.get(var) # 获取原始值及其类型
                value_from_form = request.form[var].strip()

                if var.startswith('temp_'): # 处理 temp_ 前缀的字段，它们决定最终字段的值
                    final_field_name = var.replace('temp_', '')
                    if final_field_name in config: # 确保最终字段名在配置中存在
                        # 这部分逻辑通常在前端JS处理好，后端直接取最终字段
                        # 但为保险起见，这里也处理下
                        # 假设最终字段已由JS写入隐藏input，如 DEEPSEEK_BASE_URL
                        # 这里仅作示例，实际应依赖js将正确的值填入如DEEPSEEK_BASE_URL的name中
                        pass # 依赖js，后端直接用 DEEPSEEK_BASE_URL 等
                    continue # temp_ 字段本身不直接写入配置

                # 类型转换逻辑 (与 submit_config 中类似，可以提取为辅助函数)
                if isinstance(original_value, bool):
                    new_values[var] = value_from_form.lower() in ('on', 'true', '1', 'yes')
                elif isinstance(original_value, int):
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value and str_value.isdigit():
                            new_values[var] = int(str_value)
                        elif str_value == '':
                            new_values[var] = 0
                        else:
                            new_values[var] = original_value
                            app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 包含非数字字符，已保留旧值。")
                    except (ValueError, TypeError) as e:
                        new_values[var] = original_value # 保留旧值
                        app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 无法转换为整数，已保留旧值。错误: {e}")
                elif isinstance(original_value, float):
                    try:
                        str_value = str(value_from_form).strip()
                        if str_value:
                            import re
                            if re.match(r'^-?\d+(\.\d+)?$', str_value):
                                new_values[var] = float(str_value)
                            else:
                                new_values[var] = original_value
                                app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 不是有效的数字格式，已保留旧值。")
                        else:
                            new_values[var] = 0.0
                    except (ValueError, TypeError) as e:
                        new_values[var] = original_value # 保留旧值
                        app.logger.warning(f"配置项 {var} 的值 '{value_from_form}' 无法转换为浮点数，已保留旧值。错误: {e}")

                elif original_value is None and value_from_form: # 如果原配置中某项不存在 (None), 但表单提交了值
                     # 尝试推断类型或默认为字符串
                    try:
                        new_values[var] = ast.literal_eval(value_from_form)
                    except:
                        new_values[var] = value_from_form
                else: # 默认为字符串
                    new_values[var] = value_from_form
            
            # 再次检查布尔字段，确保未勾选时为 False
            boolean_fields_from_editor = [
                'ENABLE_IMAGE_RECOGNITION', 'ENABLE_EMOJI_RECOGNITION',
                'ENABLE_EMOJI_SENDING', 'ENABLE_AUTO_MESSAGE', 'ENABLE_MEMORY',
                'UPLOAD_MEMORY_TO_AI', 'ENABLE_LOGIN_PASSWORD', 'ENABLE_REMINDERS',
                'ALLOW_REMINDERS_IN_QUIET_TIME', 'USE_VOICE_CALL_FOR_REMINDERS',
                'ENABLE_ONLINE_API', 'SEPARATE_ROW_SYMBOLS','ENABLE_SCHEDULED_RESTART',
                'ENABLE_GROUP_AT_REPLY', 'ENABLE_GROUP_KEYWORD_REPLY','GROUP_KEYWORD_REPLY_IGNORE_PROBABILITY','REMOVE_PARENTHESES',
                'ENABLE_ASSISTANT_MODEL', 'USE_ASSISTANT_FOR_MEMORY_SUMMARY',
                'IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE', 'ENABLE_SENSITIVE_CONTENT_CLEARING',
                'ENABLE_GROUP_AT_REPLY_IN_REPLIES'
            ]
            for field in boolean_fields_from_editor:
                 # 确保这些字段在表单中存在才处理，否则它们可能来自 quick_start
                if field in request.form or field not in new_values: # 如果在表单中，或尚未设置
                    new_values[field] = field in request.form # 统一处理，在表单中出现即为True

            update_config(new_values)
            
            # 验证配置文件类型正确性
            script_dir = os.path.dirname(os.path.abspath(__file__))
            config_path = os.path.join(script_dir, 'config.py')
            validate_config_types(config_path)
            
            return redirect(url_for('index')) # 保存后重定向到自身以刷新GET请求
        except Exception as e:
            app.logger.error(f"主配置页保存配置错误: {e}")
            # 渲染错误信息，或重定向到GET并带上错误提示
            return f"保存配置失败: {str(e)}"

    # GET 请求
    try:
        prompt_files_dir = 'prompts'
        if not os.path.exists(prompt_files_dir):
            os.makedirs(prompt_files_dir)
        prompt_files = [f[:-3] for f in os.listdir(prompt_files_dir) if f.endswith('.md')]
        config = parse_config() # 重新解析以获取最新配置
        # --- 新增：加载动态设置并合并到主配置中 ---
        dynamic_settings = parse_dynamic_settings()
        config.update(dynamic_settings)
        chat_context_users = get_chat_context_users()
        memory_summary_users = get_memory_summary_users()

        return render_template('config_editor.html',
                             config=config,
                             prompt_files=prompt_files,
                             chat_context_users=chat_context_users,
                             memory_summary_users=memory_summary_users)
    except Exception as e:
        app.logger.error(f"加载主配置页面错误: {e}")
        return "加载配置页面错误，请检查日志。"

# 替换secure_filename的汉字过滤逻辑
def safe_filename(filename):
    # 只保留汉字、字母、数字、下划线和点，其他字符替换为_
    filename = re.sub(r'[^\w\u4e00-\u9fff.]', '_', filename)
    # 防止路径穿越
    filename = filename.replace('../', '_').replace('/', '_')
    return filename

@app.route('/edit_prompt/<filename>', methods=['GET', 'POST'])
@login_required
def edit_prompt(filename):
    safe_dir = os.path.abspath('prompts')
    # 从path中移除.md后缀，如果存在的话，因为safe_filename会处理
    if filename.endswith('.md'):
        filename_no_ext = filename[:-3]
    else:
        filename_no_ext = filename
    
    # 使用 safe_filename 处理，并确保.md后缀
    # 注意：前端JS在调用此接口时，filename参数应该是包含.md的
    # 所以这里的safe_filename应该针对传入的filename
    processed_filename = safe_filename(filename) 
    filepath = os.path.join(safe_dir, processed_filename)

    if request.method == 'POST':
        content = request.form.get('content', '')
        new_filename_from_form = request.form.get('filename', '').strip()

        if not new_filename_from_form.endswith('.md'):
            new_filename_from_form += '.md'
        new_filename_safe = safe_filename(new_filename_from_form)
        new_filepath = os.path.join(safe_dir, new_filename_safe)

        try:
            # 如果文件名改变了
            if new_filename_safe != processed_filename:
                if os.path.exists(new_filepath):
                    return "新文件名已存在", 400 # 返回错误状态码
                # 检查旧文件是否存在
                if not os.path.exists(filepath):
                     return "原文件不存在，无法重命名", 404
                os.rename(filepath, new_filepath)
                filepath = new_filepath # 更新filepath为新路径，以便写入内容
            
            # 写入内容
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            # 修改后，不需要重定向到 prompt_list，前端会刷新或处理
            return jsonify({'status': 'success', 'message': 'Prompt已保存'}), 200
        except Exception as e:
            app.logger.error(f"保存Prompt失败: {str(e)}")
            return f"保存失败: {str(e)}", 500

    # GET 请求部分: 返回JSON数据
    try:
        if not os.path.exists(filepath): # 确保文件存在
            return jsonify({'error': '文件不存在'}), 404
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        # 返回JSON，而不是渲染模板
        return jsonify({'filename': processed_filename, 'content': content})
    except FileNotFoundError:
        return jsonify({'error': '文件不存在'}), 404
    except Exception as e:
        app.logger.error(f"读取Prompt失败: {str(e)}")
        return jsonify({'error': f'读取Prompt失败: {str(e)}'}), 500

@app.route('/create_prompt', methods=['GET', 'POST'])
@login_required
def create_prompt():
    if request.method == 'POST':
        filename = request.form.get('filename', '').strip()
        content = request.form.get('content', '')
        
        if not filename:
            return "文件名不能为空", 400 # 返回错误状态码
            
        if not filename.endswith('.md'):
            filename += '.md'
        filename = safe_filename(filename) # 应用安全文件名处理
        
        filepath = os.path.join('prompts', filename)
        if os.path.exists(filepath):
            return "文件已存在", 409 # 409 Conflict 更合适
            
        try:
            if not os.path.exists('prompts'): # 确保目录存在
                os.makedirs('prompts')
            with open(filepath, 'w', encoding='utf-8', newline='') as f:
                f.write(content)
            # 返回成功JSON，而不是重定向
            return jsonify({'status': 'success', 'message': 'Prompt已创建'}), 201 # 201 Created
        except Exception as e:
            app.logger.error(f"创建Prompt失败: {str(e)}")
            return f"创建失败: {str(e)}", 500
    
    return "此端点用于POST创建Prompt，或GET请求已被整合处理。", 405 # Method Not Allowed for GET

@app.route('/delete_prompt/<filename>', methods=['POST'])
@login_required
def delete_prompt(filename):
    safe_dir = os.path.abspath('prompts')
    filepath = os.path.join(safe_dir, safe_filename(filename))
    
    if os.path.isfile(filepath) and filepath.startswith(safe_dir):
        try:
            os.remove(filepath)
            return '', 204
        except Exception as e:
            return str(e), 500
    return "无效文件", 400

@app.route('/generate_prompt', methods=['POST'])
@login_required
def generate_prompt():
    try:
        # 从config.py获取配置
        from config import DEEPSEEK_API_KEY, DEEPSEEK_BASE_URL, MODEL
        
        client = openai.OpenAI(
            base_url=DEEPSEEK_BASE_URL,
            api_key=DEEPSEEK_API_KEY
        )
        
        data = request.get_json()
        if not data:
            return jsonify({'error': 'Invalid JSON request'}), 400
        prompt = data.get('prompt', '')
        
        FixedPrompt = (
            "\n请严格按照以下格式生成提示词（仅参考以下格式，将...替换为合适的内容，不要输出其他多余内容）。"
            "\n注意：仅在<# 输出示例>部分需要输出以'\\'进行分隔的短句，且不输出逗号和句号，其它部分应当正常输出。"
            "\n\n# 任务"
            "\n你需要扮演指定角色，根据角色的经历，模仿她的语气进行线上的日常对话。"
            "\n\n# 角色"
            "\n你将扮演...。"
            "\n\n# 外表"
            "\n...。"
            "\n\n# 经历"
            "\n...。"
            "\n\n# 性格"
            "\n...。"
            "\n\n# 输出示例"
            "\n...\\...\\..."
            "\n...\\..."
            "\n\n# 喜好"
            "\n...。\n"
        )  # 固定提示词
        
        config = parse_config()
        temperature = config.get('TEMPERATURE', 0.7)

        completion = client.chat.completions.create(
            model=MODEL,
            messages=[{
            "role": "user",
            "content": prompt + FixedPrompt
            }],
            temperature=temperature,
            max_tokens=5000
        )
        
        reply = completion.choices[0].message.content
        if reply and "</think>" in reply:
            reply = reply.split("</think>", 1)[1].strip()

        return jsonify({
            'result': reply
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# 添加一个新的API接口来保存设置
@app.route('/save_dynamic_settings', methods=['POST'])
@login_required
def handle_save_dynamic_settings():
    """处理并保存动态设置的API接口"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': '请求数据为空'}), 400

        updates = {}
        if 'emoji_tag_max_length' in data:
            try:
                limit = int(data['emoji_tag_max_length'])
                if limit <= 0:
                    return jsonify({'error': '字符限制必须为正整数'}), 400
                updates['emoji_tag_max_length'] = limit
            except (ValueError, TypeError):
                 return jsonify({'error': '无效的数值格式'}), 400

        if not updates:
            return jsonify({'error': '没有有效的设置项需要更新'}), 400

        success, message = save_dynamic_settings(updates)
        if success:
            return jsonify({'status': 'success', 'message': message}), 200
        else:
            return jsonify({'error': f'保存失败: {message}'}), 500

    except Exception as e:
        app.logger.error(f"处理 /save_dynamic_settings 失败: {e}", exc_info=True)
        return jsonify({'error': '服务器内部错误'}), 500


# 获取所有提醒 
@app.route('/get_all_reminders')
@login_required
def get_all_reminders():
    """
    获取 JSON 文件中所有的提醒记录 (包括 recurring 和 one-off)。
    """
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recurring_reminders.json')
        if not os.path.exists(json_path):
            return jsonify([]) # 文件不存在则返回空列表

        with open(json_path, 'r', encoding='utf-8') as f:
            all_reminders = json.load(f)

        # 基本验证，确保返回的是列表
        if not isinstance(all_reminders, list):
             app.logger.warning(f"文件 {json_path} 内容不是有效的JSON列表，将返回空列表。")
             return jsonify([])

        return jsonify(all_reminders) # <--- 返回所有提醒

    except json.JSONDecodeError:
        app.logger.error(f"文件 recurring_reminders.json 格式错误，无法解析。")
        return jsonify([]) # 格式错误也返回空列表
    except Exception as e:
        app.logger.error(f"获取所有提醒失败: {str(e)}")
        return jsonify({'error': f'获取所有提醒失败: {str(e)}'}), 500


# 重命名: 保存所有提醒 (覆盖整个文件)
@app.route('/save_all_reminders', methods=['POST']) # <--- Route Renamed
@login_required
def save_all_reminders():
    """
    接收前端提交的所有提醒列表 (recurring 和 one-off)，
    验证后覆盖写入 recurring_reminders.json 文件。
    """
    try:
        json_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'recurring_reminders.json')
        # 获取前端提交的完整提醒列表
        reminders_data = request.get_json()

        # --- 验证前端提交的数据 ---
        if not isinstance(reminders_data, list):
            raise ValueError("无效的数据格式，应为提醒列表")

        validated_reminders = []
        # 定义验证规则
        recurring_required = ['reminder_type', 'user_id', 'time_str', 'content']
        one_off_required = ['reminder_type', 'user_id', 'target_datetime_str', 'content']
        time_pattern = re.compile(r'^([01]\d|2[0-3]):([0-5]\d)$') # HH:MM
        # YYYY-MM-DD HH:MM (允许个位数月/日，但通常前端datetime-local会补零)
        datetime_pattern = re.compile(r'^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01]) ([01]\d|2[0-3]):([0-5]\d)$')

        for idx, item in enumerate(reminders_data, 1):
            if not isinstance(item, dict):
                 raise ValueError(f"第{idx}条记录不是有效的对象")

            reminder_type = item.get('reminder_type')
            user_id = str(item.get('user_id', '')).strip()
            content = str(item.get('content', '')).strip()

            # 通用验证
            if not reminder_type in ['recurring', 'one-off']:
                 raise ValueError(f"第{idx}条记录类型无效: {reminder_type}")
            if not user_id: raise ValueError(f"第{idx}条用户ID不能为空")
            if len(user_id) > 50: raise ValueError(f"第{idx}条用户ID过长（最大50字符）")
            if not content: raise ValueError(f"第{idx}条内容不能为空")
            if len(content) > 200: raise ValueError(f"第{idx}条内容过长（最大200字符）")

            # 特定类型验证
            if reminder_type == 'recurring':
                if not all(field in item for field in recurring_required):
                    raise ValueError(f"第{idx}条(recurring)记录字段缺失")
                time_str = str(item.get('time_str', '')).strip()
                if not time_pattern.match(time_str):
                    raise ValueError(f"第{idx}条(recurring)时间格式错误，应为 HH:MM ({time_str})")
                validated_reminders.append({
                    'reminder_type': 'recurring',
                    'user_id': user_id,
                    'time_str': time_str,
                    'content': content
                })
            elif reminder_type == 'one-off':
                if not all(field in item for field in one_off_required):
                     raise ValueError(f"第{idx}条(one-off)记录字段缺失")
                target_datetime_str = str(item.get('target_datetime_str', '')).strip()
                # 验证 YYYY-MM-DD HH:MM 格式
                if not datetime_pattern.match(target_datetime_str):
                    raise ValueError(f"第{idx}条(one-off)日期时间格式错误，应为 YYYY-MM-DD HH:MM ({target_datetime_str})")
                validated_reminders.append({
                    'reminder_type': 'one-off',
                    'user_id': user_id,
                    'target_datetime_str': target_datetime_str,
                    'content': content
                })

        # --- 原子化写入操作 ---
        # 使用临时文件确保写入安全，覆盖原文件
        temp_dir = os.path.dirname(json_path)
        with tempfile.NamedTemporaryFile('w', delete=False, dir=temp_dir, encoding='utf-8', suffix='.tmp') as temp_f:
            json.dump(validated_reminders, temp_f, ensure_ascii=False, indent=2) # 写入验证后的完整列表
            temp_path = temp_f.name
        # 替换原文件
        shutil.move(temp_path, json_path)

        return jsonify({'status': 'success', 'message': '所有提醒已更新'})

    except ValueError as ve: # 捕获验证错误
         app.logger.error(f'提醒保存验证失败: {str(ve)}')
         return jsonify({'error': f'数据验证失败: {str(ve)}'}), 400
    except Exception as e:
        app.logger.error(f'提醒保存失败: {str(e)}')
        return jsonify({'error': f'服务器内部错误: {str(e)}'}), 500

@app.route('/import_config', methods=['POST'])
@login_required
def import_config():
    global bot_process
    # 如果 bot 正在运行，则不允许导入配置
    # if bot_process and bot_process.poll() is None:
        # return jsonify({'error': '程序正在运行，请先停止再导入配置'}), 400

    try:
        if 'config_file' not in request.files:
            return jsonify({'error': '未找到上传的配置文件'}), 400
            
        config_file = request.files['config_file']
        if not config_file or not config_file.filename or not config_file.filename.endswith('.py'):
            return jsonify({'error': '请上传.py格式的配置文件'}), 400
            
        # 创建临时文件用于解析配置
        with tempfile.NamedTemporaryFile('wb', suffix='.py', delete=False) as temp_f:
            temp_path = temp_f.name
            config_file.save(temp_path)
        
        # 解析临时配置文件
        imported_config = {}
        try:
            with open(temp_path, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if line.startswith('#') or not line:
                        continue
                    match = re.match(r'^(\w+)\s*=\s*(.+)$', line)
                    if match:
                        var_name = match.group(1)
                        var_value_str = match.group(2)
                        try:
                            var_value = ast.literal_eval(var_value_str)
                            imported_config[var_name] = var_value
                        except:
                            imported_config[var_name] = var_value_str
        finally:
            # 清理临时文件
            try:
                os.unlink(temp_path)
            except:
                pass
        
        # 获取当前配置作为基础
        current_config = parse_config()
        
        # 合并配置：只更新导入配置中存在的项
        for key, value in imported_config.items():
            if key in current_config:  # 只更新当前配置中已存在的项
                current_config[key] = value
        
        # 更新配置文件
        update_config(current_config)
        
        return jsonify({'success': True, 'message': '配置导入成功，共导入了{}个有效参数'.format(len(imported_config))}), 200
    except Exception as e:
        app.logger.error(f"配置导入失败: {str(e)}")
        return jsonify({'error': f'导入失败: {str(e)}'}), 500

@app.route('/reset_default_config', methods=['POST'])
@login_required
def reset_default_config():
    global bot_process
    if bot_process and bot_process.poll() is None:
        return jsonify({'error': '程序正在运行，请先停止再恢复默认配置'}), 400
    
    try:
        # 获取默认配置
        default_config = get_default_config()
        
        # 保留当前的端口号和登录密码设置（避免被锁在外）
        current_config = parse_config()
        if 'PORT' in current_config:
            default_config['PORT'] = current_config['PORT']
        if 'LOGIN_PASSWORD' in current_config:
            default_config['LOGIN_PASSWORD'] = current_config['LOGIN_PASSWORD']
        if 'ENABLE_LOGIN_PASSWORD' in current_config:
            default_config['ENABLE_LOGIN_PASSWORD'] = current_config['ENABLE_LOGIN_PASSWORD']
        
        # 使用 update_config 函数来保留原有的注释和格式
        update_config(default_config)
        
        app.logger.info("配置已恢复到默认值")
        return jsonify({'message': '配置已恢复到默认值'}), 200
        
    except Exception as e:
        app.logger.error(f"恢复默认配置失败: {e}")
        return jsonify({'error': f'恢复默认配置失败: {str(e)}'}), 500

class WebLogHandler(logging.Handler):
    def emit(self, record):
        log_entry = self.format(record)
        log_queue.put(log_entry)

# 配置日志处理器
web_handler = WebLogHandler()
web_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
logging.getLogger().addHandler(web_handler)

@app.route('/stream')
@login_required
def stream():
    def event_stream():
        retry_count = 0
        while True:
            try:
                log = log_queue.get(timeout=5)
                yield f"data: {log}\n\n"
                retry_count = 0  # 成功时重置重试计数器
            except Empty:
                yield ":keep-alive\n\n"  # 发送心跳包
                retry_count = min(retry_count + 1, 5)
                time.sleep(2 ** retry_count)  # 指数退避
            except Exception as e:
                app.logger.error(f"SSE Error: {str(e)}")
                yield "event: error\ndata: Connection closed\n\n"
                break
    
    return Response(
        event_stream(),
        mimetype="text/event-stream",
        headers={
            'Cache-Control': 'no-cache',
            'Connection': 'keep-alive',
            'X-Accel-Buffering': 'no'
        }
    )

@app.route('/api/log', methods=['POST'])
def receive_bot_log():
    try:
        # 增加Content-Type检查
        if not request.is_json:
            return jsonify({'error': 'Unsupported Media Type'}), 415

        data = request.get_json()
        if not data:
            return jsonify({'error': 'Missing log data'}), 400

        # 支持两种格式：单个日志或日志数组
        if 'logs' in data:  # 批量日志
            logs_data = data.get('logs', [])
            if isinstance(logs_data, list):
                for log_entry in logs_data:
                    if log_entry:
                        # 添加进程标识和颜色标记
                        colored_log = f"[BOT] \033[34m{log_entry.strip()}\033[0m"
                        log_queue.put(colored_log)
                return jsonify({'status': 'success', 'processed': len(logs_data)})
            return jsonify({'error': 'Invalid logs format'}), 400
            
        elif 'log' in data:  # 兼容单条日志格式
            log_data = data.get('log')
            if log_data:
                # 添加进程标识和颜色标记
                colored_log = f"[BOT] \033[34m{log_data.strip()}\033[0m"
                log_queue.put(colored_log)
            return jsonify({'status': 'success'})
            
        else:
            return jsonify({'error': 'Missing log data'}), 400
            
    except Exception as e:
        app.logger.error(f"日志接收失败: {str(e)}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_chat_context_users', methods=['GET'])
@login_required
def api_get_chat_context_users():
    users = get_chat_context_users()
    return jsonify({'users': users})

@app.route('/clear_chat_context/<username>', methods=['POST'])
@login_required
def clear_chat_context(username):
    """清除指定用户与其当前活动Prompt关联的聊天上下文"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return jsonify({'status': 'error', 'message': '聊天上下文文件不存在'}), 404

    # 1. 获取用户当前的人设 (prompt)
    try:
        config = parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        current_prompt = next((item[1] for item in listen_list if item[0] == username), None)
        
        if not current_prompt:
            return jsonify({'error': f"在配置中未找到用户 '{username}' 的活动Prompt，无法清除上下文"}), 404

    except Exception as e:
        app.logger.error(f"解析配置文件以查找用户Prompt时出错: {e}")
        return jsonify({'error': '解析配置文件失败'}), 500

    # 2. 使用文件锁安全地修改文件
    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            with open(CHAT_CONTEXTS_FILE, 'r+', encoding='utf-8') as f:
                content = f.read()
                if not content:
                    # 文件为空，无需操作
                    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的聊天上下文已为空"})

                data = json.loads(content)
                user_data = data.get(username)

                if user_data and isinstance(user_data, dict) and current_prompt in user_data:
                    # 3. 在用户的上下文中，只删除与当前人设关联的条目
                    del user_data[current_prompt]
                    app.logger.info(f"已清除用户 '{username}' 的人设 '{current_prompt}' 的聊天上下文。")
                    
                    # 4. (推荐) 如果删除后该用户没有任何人设数据了，则删除该用户键
                    if not user_data:
                        del data[username]
                        app.logger.info(f"用户 '{username}' 已无任何上下文数据，已将其从文件中移除。")
                    
                    # 5. 写回修改后的数据
                    f.seek(0)
                    json.dump(data, f, ensure_ascii=False, indent=4)
                    f.truncate()
                    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的人设 '{current_prompt}' 的聊天上下文已清除"})
                elif not user_data:
                    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的聊天上下文已为空"})
                else:
                    # 兼容旧的数据格式 (直接是列表) 或者人设未找到的情况
                    # 如果是旧格式，则直接删除整个用户条目，因为无法区分人设
                    if isinstance(user_data, list):
                         del data[username]
                         f.seek(0)
                         json.dump(data, f, ensure_ascii=False, indent=4)
                         f.truncate()
                         return jsonify({'status': 'success', 'message': f"用户 '{username}' 的旧格式上下文已清除"})
                    return jsonify({'status': 'error', 'message': f"用户 '{username}' 未找到与人设 '{current_prompt}' 关联的上下文"}), 404

        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"处理 chat_contexts.json 失败: {e}")
            return jsonify({'status': 'error', 'message': '处理聊天上下文文件失败'}), 500


def get_default_config():
    # --- 修改：移除了 MAX_MEMORY_NUMBER ---
    return {
        "LISTEN_LIST": [['微信名1', '角色1', True]],
        "DEEPSEEK_API_KEY": '',
        "DEEPSEEK_BASE_URL": 'https://vg.v1api.cc/v1',
        "MODEL": 'deepseek-v3-0324',
        "MAX_GROUPS": 5,
        "MAX_TOKEN": 2000,
        "TEMPERATURE": 1.1,
        "MOONSHOT_API_KEY": '',
        "MOONSHOT_BASE_URL": 'https://vg.v1api.cc/v1',
        "MOONSHOT_MODEL": 'gpt-4o',
        "MOONSHOT_TEMPERATURE": 0.8,
        "ENABLE_IMAGE_RECOGNITION": True,
        "ENABLE_EMOJI_RECOGNITION": True,
        "QUEUE_WAITING_TIME": 7,
        "EMOJI_DIR": 'emojis',
        "ENABLE_EMOJI_SENDING": True,
        "EMOJI_SENDING_PROBABILITY": 25,
        "AUTO_MESSAGE": '请你模拟系统设置的角色，在微信上找对方继续刚刚的话题或者询问对方在做什么',
        "ENABLE_AUTO_MESSAGE": True,
        "MIN_COUNTDOWN_HOURS": 1.0,
        "MAX_COUNTDOWN_HOURS": 2.0,
        "QUIET_TIME_START": '22:00',
        "QUIET_TIME_END": '8:00',
        "AVERAGE_TYPING_SPEED": 0.2,
        "RANDOM_TYPING_SPEED_MIN": 0.05,
        "RANDOM_TYPING_SPEED_MAX": 0.1,
        "SEPARATE_ROW_SYMBOLS": True,
        "ENABLE_MEMORY": True,
        "MEMORY_TEMP_DIR": 'Memory_Temp',
        "MAX_MESSAGE_LOG_ENTRIES": 30,
        "UPLOAD_MEMORY_TO_AI": True,
        "ENABLE_LOGIN_PASSWORD": False,
        "LOGIN_PASSWORD": '123456',
        "PORT": 5000,
        "ENABLE_REMINDERS": True,
        "ALLOW_REMINDERS_IN_QUIET_TIME": True,
        "USE_VOICE_CALL_FOR_REMINDERS": False,
        "ENABLE_ONLINE_API": False,
        "ONLINE_BASE_URL": 'https://vg.v1api.cc/v1',
        "ONLINE_MODEL": 'net-gpt-4o-mini',
        "ONLINE_API_KEY": '',
        "ONLINE_API_TEMPERATURE": 0.7,
        "ONLINE_API_MAX_TOKEN": 2000,
        "SEARCH_DETECTION_PROMPT": '是否需要查询今天的天气、最新的新闻事件、特定网站的内容、股票价格、特定人物的最新动态等',
        "ONLINE_FIXED_PROMPT": '',
        "ENABLE_URL_FETCHING": True,
        "REQUESTS_TIMEOUT": 10,
        "REQUESTS_USER_AGENT": 'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36',
        "MAX_WEB_CONTENT_LENGTH": 2000,
        "ENABLE_SCHEDULED_RESTART": True,
        "RESTART_INTERVAL_HOURS": 2.0,
        "RESTART_INACTIVITY_MINUTES": 15,
        "REMOVE_PARENTHESES": False,
        "ENABLE_ASSISTANT_MODEL": False,
        "ASSISTANT_BASE_URL": 'https://vg.v1api.cc/v1',
        "ASSISTANT_MODEL": 'gpt-4o-mini',
        "ASSISTANT_API_KEY": '',
        "ASSISTANT_TEMPERATURE": 0.3,
        "ASSISTANT_MAX_TOKEN": 1000,
        "USE_ASSISTANT_FOR_MEMORY_SUMMARY": False,
        "IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE": False,
        "ENABLE_SENSITIVE_CONTENT_CLEARING": True,
        "ENABLE_GROUP_AT_REPLY_IN_REPLIES": True
    }

def validate_config():
    """验证config.py配置完整性，若有缺失项则自动补充默认值"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')
    
    try:
        # 如果配置文件不存在，直接创建完整配置
        if not os.path.exists(config_path):
            print(f"配置文件不存在，正在创建新配置文件: {config_path}")
            with open(config_path, 'w', encoding='utf-8') as f:
                f.write("# -*- coding: utf-8 -*-\n\n")
                f.write("# 自动生成的配置文件\n\n")
                
                for key, value in get_default_config().items():
                    f.write(f"{key} = {repr(value)}\n")
            print("已创建新的配置文件")
            return True
        
        # 尝试解析当前配置
        current_config = parse_config()
        default_config = get_default_config()
        
        # 记录缺少的配置项
        missing_keys = []
        # 构建需要更新的配置字典
        updates_needed = {}
        
        # 检查每个默认配置项是否存在
        for key, default_value in default_config.items():
            if key not in current_config:
                missing_keys.append(key)
                updates_needed[key] = default_value
        
        # 如果存在缺失项，更新配置文件
        if missing_keys:
            print(f"检测到{len(missing_keys)}个缺失的配置项: {', '.join(missing_keys)}")
            print("正在自动补充默认值...")
            
            # 直接修改文件，添加缺失的配置项
            with open(config_path, 'a', encoding='utf-8') as f:
                f.write("\n# 自动补充的配置项\n")
                for key in missing_keys:
                    f.write(f"{key} = {repr(default_config[key])}\n")
            
            print("配置文件已更新完成")
            return True  # 配置已更新
        
        print("配置文件验证完成，所有配置项齐全")
        return False  # 配置无需更新
        
    except Exception as e:
        print(f"验证配置文件时出错: {str(e)}")
        return False

def kill_process_using_port(port):
    """
    检查指定端口是否被占用，如果被占用则结束占用的进程
    """
    # 遍历所有连接
    for conn in psutil.net_connections():
        # 由于 config 中 PORT 可能为字符串，转换为 int
        if conn.laddr and conn.laddr.port == port:
            # 根据不同平台，监听状态可能不同（Linux一般为 'LISTEN'，Windows为 'LISTENING'）
            if conn.status in ('LISTEN', 'LISTENING'):
                try:
                    proc = psutil.Process(conn.pid)
                    print(f"检测到端口 {port} 被进程 {conn.pid} 占用，尝试结束该进程……")
                    proc.kill()
                    proc.wait(timeout=3)
                    print(f"进程 {conn.pid} 已被成功结束。")
                except Exception as e:
                    print(f"结束进程 {conn.pid} 时出现异常：{e}")

# =========================================================================
# ===== 新增：聊天上下文编辑 API (添加到 config_editor.py 文件) =====
# =========================================================================


@app.route('/api/get_chat_context/<username>', methods=['GET'])
@login_required
def get_user_chat_context(username):
    """获取指定用户的、与其当前活动Prompt关联的聊天上下文"""
    if not os.path.exists(CHAT_CONTEXTS_FILE):
        return jsonify({'status': 'success', 'context': '[]'})

    try:
        config = parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        current_prompt = next((item[1] for item in listen_list if item[0] == username), None)
        
        if not current_prompt:
            return jsonify({'error': f"在配置中未找到用户 '{username}' 的活动Prompt"}), 404

    except Exception as e:
        app.logger.error(f"解析配置文件以查找用户Prompt时出错: {e}")
        return jsonify({'error': '解析配置文件失败'}), 500

    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            if not os.path.exists(CHAT_CONTEXTS_FILE):
                return jsonify({'status': 'success', 'context': '[]'})

            with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                content = f.read()
                contexts = json.loads(content) if content else {}
            
            user_contexts_by_prompt = contexts.get(username)
            user_context_for_prompt = []
            
            if user_contexts_by_prompt is None:
                pass  # No context for this user, will return empty list
            elif isinstance(user_contexts_by_prompt, dict):
                # New structure: {"prompt1.md": [...]}
                user_context_for_prompt = user_contexts_by_prompt.get(current_prompt, [])
            elif isinstance(user_contexts_by_prompt, list):
                # Old structure: [...], show it for editing. Saving will migrate it.
                user_context_for_prompt = user_contexts_by_prompt
            
            # 增加健壮性：如果由于历史bug导致存储的是字符串，尝试解析它
            if isinstance(user_context_for_prompt, str):
                try:
                    user_context_for_prompt = json.loads(user_context_for_prompt)
                except json.JSONDecodeError:
                    # 如果无法解析，则按原样返回，让前端作为纯文本处理
                    app.logger.warning(f"用户 '{username}' 的上下文无法解析为JSON，将以纯文本形式返回。")
            
            pretty_context = json.dumps(user_context_for_prompt, ensure_ascii=False, indent=4)
            return jsonify({'status': 'success', 'context': pretty_context})

        except (json.JSONDecodeError, IOError) as e:
            app.logger.error(f"读取或解析聊天上下文文件失败: {e}")
            return jsonify({'error': f'读取或解析文件失败: {e}'}), 500

@app.route('/api/save_chat_context/<username>', methods=['POST'])
@login_required
def save_user_chat_context(username):
    """保存指定用户修改后的、与其当前活动Prompt关联的聊天上下文"""
    # if bot_process and bot_process.poll() is None:
        # return jsonify({'error': '程序正在运行，请先停止再保存上下文'}), 400
        
    data = request.get_json()
    if not data or 'context' not in data:
        return jsonify({'status': 'error', 'error': '请求数据无效'}), 400
    
    new_context_str = data['context']
    
    # 验证并解析前端传来的字符串为Python对象
    try:
        new_context_data = json.loads(new_context_str)
        if not isinstance(new_context_data, list):
            raise ValueError("上下文数据必须是一个JSON数组 (list)")
    except (json.JSONDecodeError, ValueError) as e:
        return jsonify({'status': 'error', 'message': f'格式错误，无法保存: {str(e)}'}), 400
    
    # 获取该用户当前使用的prompt文件
    config = parse_config()
    listen_list = config.get('LISTEN_LIST', [])
    current_prompt = next((item[1] for item in listen_list if item[0] == username), None)
    
    if not current_prompt:
        app.logger.warning(f"无法找到用户 '{username}' 的当前Prompt，上下文保存可能不准确。")
        # 即使找不到，也应以用户名作为顶级键保存
    
    with FileLock(CHAT_CONTEXTS_LOCK_FILE):
        try:
            all_contexts = {}
            if os.path.exists(CHAT_CONTEXTS_FILE):
                with open(CHAT_CONTEXTS_FILE, 'r', encoding='utf-8') as f:
                    content = f.read()
                    if content:
                        all_contexts = json.loads(content)

            user_contexts_by_prompt = all_contexts.get(username)

            if user_contexts_by_prompt is None or isinstance(user_contexts_by_prompt, list):
                all_contexts[username] = {current_prompt: new_context_data}
                if isinstance(user_contexts_by_prompt, list):
                    app.logger.info(f"用户 '{username}' 的上下文已从旧格式迁移到新格式。")
            elif isinstance(user_contexts_by_prompt, dict):
                user_contexts_by_prompt[current_prompt] = new_context_data
            else:
                app.logger.warning(f"用户 '{username}' 的上下文数据格式未知，将直接覆盖。")
                all_contexts[username] = {current_prompt: new_context_data}

            temp_file_path = CHAT_CONTEXTS_FILE + ".tmp"
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(all_contexts, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file_path, CHAT_CONTEXTS_FILE)

        except Exception as e:
            app.logger.error(f"保存聊天上下文失败: {e}")
            return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500

 
    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的上下文已更新"})

# ======================== [修改后的核心记忆API] ========================

@app.route('/api/get_memory_summary/<username>', methods=['GET'])
@login_required
def get_user_memory_summary(username):
    """
    获取单个用户的核心记忆内容。
    [修改] 支持直接通过完整用户标识符（如 Mine_角色1）读取对应的JSON文件。
    [兼容性修改] 新增对旧版列表格式核心记忆文件的读取支持，并统一返回新格式给前端。
    """
    # 直接根据用户标识符构建文件路径（Memory_Core 的 unified_memory 格式）
    safe_user_filename_part = safe_filename(username)
    target_filename = f"{safe_user_filename_part}_unified_memory.json"
    file_path = os.path.join(MEMORY_SUMMARIES_DIR, target_filename)
    
    # 定义一个默认的空记忆结构
    default_memory = {"timestamp": "", "content": ""}

    if os.path.exists(file_path):
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                if not content.strip():
                    return jsonify(default_memory)
                
                memory_data = json.loads(content)
                
                # [兼容性修改] 智能判断格式并统一输出
                if isinstance(memory_data, dict):
                    # 检查是否为双重记忆格式
                    if 'core_memory' in memory_data or 'core_memos' in memory_data:
                        app.logger.info(f"UI请求：检测到用户 {username} 的双重记忆格式核心记忆，将进行兼容性转换。")
                        # 双重记忆格式，提取核心记忆内容
                        core_memory_content = ""
                        if 'core_memory' in memory_data:
                            core_memory_content += f"核心记忆:\n{memory_data['core_memory']}\n\n"
                        if 'core_memos' in memory_data:
                            core_memos = memory_data['core_memos']
                            if isinstance(core_memos, dict) and 'memos' in core_memos:
                                # 检查memos的格式
                                memos = core_memos['memos']
                                if isinstance(memos, str):
                                    # 纯文本格式，直接显示
                                    core_memory_content += f"核心备忘录:\n{memos}"
                                else:
                                    # JSON格式，格式化显示
                                    memos_content = json.dumps(memos, ensure_ascii=False, indent=2)
                                    core_memory_content += f"核心备忘录:\n{memos_content}"
                        
                        converted_memory = {
                            "timestamp": memory_data.get("updated_at", "双重格式-无具体时间戳"),
                            "content": core_memory_content.strip()
                        }
                        return jsonify(converted_memory)
                    else:
                        # 是新格式，确保字段完整后直接返回
                        memory_data.setdefault('content', '')
                        memory_data.setdefault('timestamp', '')
                        return jsonify(memory_data)
                
                elif isinstance(memory_data, list):
                    # 是旧格式，转换为新格式再返回给前端
                    app.logger.info(f"UI请求：检测到用户 {username} 的旧版列表格式核心记忆，将进行兼容性转换。")
                    all_summaries = [item.get("summary", "") for item in memory_data if item.get("summary")]
                    combined_content = "\n".join(all_summaries).strip()
                    
                    # 模拟一个新格式的返回对象
                    converted_memory = {
                        "timestamp": "旧格式-无时间戳",
                        "content": combined_content
                    }
                    return jsonify(converted_memory)
                
                else:
                    # 未知格式
                    app.logger.warning(f"核心记忆文件 {target_filename} 内容不是预期的字典或列表格式。")
                    return jsonify({"timestamp": "文件格式错误", "content": content})

        except (IOError, json.JSONDecodeError) as e:
            app.logger.error(f"读取或解析核心记忆文件失败 ({file_path}): {e}")
            default_memory['content'] = f"错误：无法读取或解析记忆文件。\n\n{str(e)}"
            return jsonify(default_memory), 500
    else:
        # 文件不存在时，返回默认的空记忆结构
        return jsonify(default_memory)


@app.route('/api/save_memory_summary/<username>', methods=['POST'])
@login_required
def save_user_memory_summary(username):
    """保存指定用户修改后的核心记忆（新版单条格式）"""
    
    # if bot_process and bot_process.poll() is None:
        # return jsonify({'error': '程序正在运行，请先停止再保存记忆'}), 400
        
    data = request.get_json()
    if not data or 'content' not in data:
        return jsonify({'status': 'error', 'message': '请求无效，缺少 "content" 字段'}), 400

    new_content = data['content']
    
    # 验证内容是字符串
    if not isinstance(new_content, str):
        return jsonify({'status': 'error', 'message': '格式错误: 核心记忆内容必须是字符串。'}), 400
    
    # 直接根据用户标识符构建文件路径（Memory_Core 的 unified_memory 格式）
    safe_user_filename_part = safe_filename(username)
    target_filename = f"{safe_user_filename_part}_unified_memory.json"
    file_path = os.path.join(MEMORY_SUMMARIES_DIR, target_filename)
    lock_path = file_path + '.lock'

    with FileLock(lock_path):
        try:
            os.makedirs(MEMORY_SUMMARIES_DIR, exist_ok=True)
            
            # 创建要保存的完整数据结构
            memory_to_save = {
                "timestamp": datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
                "content": new_content.strip()
            }
            
            # 原子化写入
            temp_file_path = file_path + ".tmp"
            with open(temp_file_path, 'w', encoding='utf-8') as f:
                json.dump(memory_to_save, f, ensure_ascii=False, indent=4)
            shutil.move(temp_file_path, file_path)

        except Exception as e:
            app.logger.error(f"保存记忆文件 {target_filename} 失败: {e}")
            return jsonify({'status': 'error', 'message': f'保存失败: {str(e)}'}), 500

    return jsonify({'status': 'success', 'message': f"用户 '{username}' 的核心记忆已更新"})

# =========================================================================

@app.route('/api/delete_memory_summary/<username>', methods=['POST'])
@login_required
def delete_user_memory_summary(username):
    """删除指定用户的核心记忆文件"""
    if not os.path.exists(MEMORY_SUMMARIES_DIR):
        return jsonify({'status': 'success', 'message': '记忆目录不存在，无需操作'})

    # 获取用户的角色名（可选，用于更详细的消息）
    try:
        config = parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        user_role = next((item[1] for item in listen_list if item[0] == username), username)
    except:
        user_role = username

    # 直接根据用户标识符构建文件路径（Memory_Core 的 unified_memory 格式）
    safe_user_filename_part = safe_filename(username)
    target_filename = f"{safe_user_filename_part}_unified_memory.json"
    file_path = os.path.join(MEMORY_SUMMARIES_DIR, target_filename)
    lock_path = file_path + '.lock'

    # 检查并删除这一个特定的文件
    if os.path.exists(file_path):
        try:
            with FileLock(lock_path, timeout=1):
                 os.remove(file_path)
            app.logger.info(f"已删除核心记忆文件: {target_filename}")
            return jsonify({'status': 'success', 'message': f"用户 '{username}' (角色: '{user_role}') 的核心记忆已清除"})
        except Exception as e:
            app.logger.error(f"删除核心记忆文件 {target_filename} 失败: {e}")
            return jsonify({'status': 'error', 'message': f'删除文件失败: {e}'}), 500
    else:
        return jsonify({'status': 'success', 'message': f"未找到用户 '{username}' (角色: '{user_role}') 的核心记忆文件"})


# =========================================================================
# ===== 双重记忆系统日历功能 =====
# =========================================================================

@app.route('/memory_calendar')
def memory_calendar():
    """双重记忆系统日历查看页面（用户权限）"""
    try:
        # 获取所有用户用于选择界面
        config = parse_config()
        users = [user[0] for user in config.get('LISTEN_LIST', [])]
        # 获取用户权限设置
        user_memory_settings = config.get('USER_MEMORY_ACCESS_SETTINGS', {})
        return render_template('memory_calendar.html', users=users, user_memory_settings=user_memory_settings)
    except Exception as e:
        app.logger.error(f"加载日记页面失败: {e}")
        return f"加载失败: {str(e)}", 500

@app.route('/api/get_memory_calendar/<username>/<year>/<month>')
def get_memory_calendar(username, year, month):
    """获取指定用户和月份的日记数据"""
    try:
        # 获取用户的角色名
        config = parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        role_name = next((item[1] for item in listen_list if item[0] == username), username)
        role_name_without_ext = os.path.splitext(role_name)[0]
        memory_key = f"{username}_{role_name_without_ext}"
        
        # 构建路径
        daily_dir = os.path.join('Memory_Daily', memory_key)
        diary_dir = os.path.join(daily_dir, 'diary')
        memos_dir = os.path.join(daily_dir, 'memos')
        
        calendar_data = {}
        
        # 扫描指定月份的文件
        import calendar as cal
        
        year_int = int(year)
        month_int = int(month)
        
        # 获取该月的所有天数
        _, num_days = cal.monthrange(year_int, month_int)
        
        for day in range(1, num_days + 1):
            date_str = f"{year_int:04d}-{month_int:02d}-{day:02d}"
            day_data = {
                'date': date_str,
                'has_diary': False,
                'has_memos': False,
                'diary_preview': '',
                'memos_preview': ''
            }
            
            # 检查日记
            diary_file = os.path.join(diary_dir, f"{date_str}.md")
            if os.path.exists(diary_file):
                day_data['has_diary'] = True
                try:
                    with open(diary_file, 'r', encoding='utf-8') as f:
                        content = f.read()
                        # 获取前100字符作为预览
                        day_data['diary_preview'] = content[:100] + '...' if len(content) > 100 else content
                except:
                    day_data['diary_preview'] = '读取失败'
            
            # 检查备忘录
            memo_file = os.path.join(memos_dir, f"{date_str}.json")
            if os.path.exists(memo_file):
                day_data['has_memos'] = True
                try:
                    with open(memo_file, 'r', encoding='utf-8') as f:
                        memo_data = json.load(f)
                        # 简化备忘录预览
                        previews = []
                        for key, values in memo_data.items():
                            if values:
                                previews.append(f"{key}: {len(values)}条")
                        day_data['memos_preview'] = '; '.join(previews)
                except:
                    day_data['memos_preview'] = '读取失败'
            
            calendar_data[date_str] = day_data
        
        return jsonify(calendar_data)
        
    except Exception as e:
        app.logger.error(f"获取用户 {username} {year}-{month} 日记失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/get_memory_detail/<username>/<date>')
def get_memory_detail(username, date):
    """获取指定日期的详细记忆内容"""
    try:
        # 获取用户的角色名
        config = parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        role_name = next((item[1] for item in listen_list if item[0] == username), username)
        role_name_without_ext = os.path.splitext(role_name)[0]
        memory_key = f"{username}_{role_name_without_ext}"
        
        # 构建路径
        daily_dir = os.path.join('Memory_Daily', memory_key)
        diary_dir = os.path.join(daily_dir, 'diary')
        memos_dir = os.path.join(daily_dir, 'memos')
        
        detail_data = {
            'date': date,
            'diary_content': '',
            'memos_content': {}
        }
        
        # 读取日记
        diary_file = os.path.join(diary_dir, f"{date}.md")
        if os.path.exists(diary_file):
            try:
                with open(diary_file, 'r', encoding='utf-8') as f:
                    detail_data['diary_content'] = f.read()
            except Exception as e:
                detail_data['diary_content'] = f'读取日记失败: {str(e)}'
        
        # 读取备忘录（支持JSON和纯文本格式）
        memo_file = os.path.join(memos_dir, f"{date}.json")
        if os.path.exists(memo_file):
            try:
                with open(memo_file, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                    
                    if not file_content:
                        detail_data['memos_content'] = {}
                    else:
                        # 尝试JSON解析
                        try:
                            memo_data = json.loads(file_content)
                            # Ensure memo_data is a valid dictionary with array values
                            if isinstance(memo_data, dict):
                                # Validate and clean memo data structure
                                cleaned_memo_data = {}
                                for key, value in memo_data.items():
                                    if isinstance(value, list):
                                        cleaned_memo_data[key] = value
                                    else:
                                        # Convert non-list values to list or skip
                                        if isinstance(value, str):
                                            cleaned_memo_data[key] = [value]
                                        else:
                                            cleaned_memo_data[key] = []
                                detail_data['memos_content'] = cleaned_memo_data
                            else:
                                detail_data['memos_content'] = {'error': f'备忘录数据格式错误: 期望字典类型，得到{type(memo_data)}'}
                        except json.JSONDecodeError:
                            # JSON解析失败，作为纯文本处理
                            detail_data['memos_content'] = {'纯文本备忘录': [file_content]}
            except Exception as e:
                detail_data['memos_content'] = {'error': f'读取备忘录失败: {str(e)}'}
        
        return jsonify(detail_data)
        
    except Exception as e:
        app.logger.error(f"获取用户 {username} {date} 详细记忆失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/memory_settings', methods=['GET', 'POST'])
@login_required
def memory_settings():
    """记忆系统设置（用户级AI访问权限等）"""
    if request.method == 'GET':
        try:
            config = parse_config()
            # 获取用户参数
            username = request.args.get('user', '')
            
            # 获取用户特定的设置
            user_memory_settings = config.get('USER_MEMORY_ACCESS_SETTINGS', {})
            
            # 确保user_memory_settings是字典类型
            if not isinstance(user_memory_settings, dict):
                user_memory_settings = {}
            
            user_settings = user_memory_settings.get(username, {
                'diary': config.get('DEFAULT_AI_CAN_ACCESS_DIARY', False),
                'memos': config.get('DEFAULT_AI_CAN_ACCESS_MEMOS', False)
            })
            
            # 确保user_settings是字典类型
            if not isinstance(user_settings, dict):
                user_settings = {
                    'diary': config.get('DEFAULT_AI_CAN_ACCESS_DIARY', False),
                    'memos': config.get('DEFAULT_AI_CAN_ACCESS_MEMOS', False)
                }
            
            settings = {
                'username': username,
                'ai_can_access_diary': user_settings.get('diary', False),
                'ai_can_access_memos': user_settings.get('memos', False),
                'enable_daily_summary': config.get('ENABLE_DAILY_SUMMARY', True),
                'enable_diary_summary': config.get('ENABLE_DIARY_SUMMARY', True),
                'enable_memo_summary': config.get('ENABLE_MEMO_SUMMARY', True),
                'manual_memo_min_entries': config.get('MANUAL_MEMO_MIN_ENTRIES', 10),
                'max_message_log_entries': config.get('MAX_MESSAGE_LOG_ENTRIES', 30),
                'all_users': [user[0] for user in config.get('LISTEN_LIST', [])]
            }
            return jsonify(settings)
        except Exception as e:
            app.logger.error(f"获取记忆设置失败: {e}")
            return jsonify({'error': str(e)}), 500
    
    elif request.method == 'POST':
        try:
            app.logger.info("开始处理记忆设置保存请求")
            settings = request.json
            app.logger.info(f"接收到的设置数据: {settings}")
            
            username = settings.get('username', '')
            app.logger.info(f"用户名: {username}")
            
            if not username:
                app.logger.error("用户名为空")
                return jsonify({'error': '用户名不能为空'}), 400
            
            # 读取配置文件
            config_lines = []
            try:
                with open('config.py', 'r', encoding='utf-8') as f:
                    config_lines = f.readlines()
                app.logger.info(f"成功读取配置文件，共 {len(config_lines)} 行")
            except Exception as read_error:
                app.logger.error(f"读取配置文件失败: {read_error}")
                return jsonify({'error': f'无法读取配置文件: {read_error}'}), 500
            
            # 更新用户特定设置
            ai_can_access_diary = settings.get('ai_can_access_diary', False)
            ai_can_access_memos = settings.get('ai_can_access_memos', False)
            app.logger.info(f"AI访问权限设置: diary={ai_can_access_diary}, memos={ai_can_access_memos}")
            
            # 查找并更新 USER_MEMORY_ACCESS_SETTINGS
            in_user_settings = False
            user_settings_start = -1
            user_settings_end = -1
            
            for i, line in enumerate(config_lines):
                if 'USER_MEMORY_ACCESS_SETTINGS' in line and line.strip().startswith('USER_MEMORY_ACCESS_SETTINGS'):
                    in_user_settings = True
                    user_settings_start = i
                    app.logger.info(f"找到USER_MEMORY_ACCESS_SETTINGS开始位置: {i}")
                elif in_user_settings and line.strip() == '}':
                    user_settings_end = i
                    app.logger.info(f"找到USER_MEMORY_ACCESS_SETTINGS结束位置: {i}")
                    break
            
            if user_settings_start != -1 and user_settings_end != -1:
                app.logger.info("成功定位USER_MEMORY_ACCESS_SETTINGS配置段")
                # 构建新的用户设置
                config = parse_config()
                user_memory_settings = config.get('USER_MEMORY_ACCESS_SETTINGS', {})
                
                # 确保user_memory_settings是字典类型
                if not isinstance(user_memory_settings, dict):
                    user_memory_settings = {}
                
                user_memory_settings[username] = {
                    'diary': ai_can_access_diary,
                    'memos': ai_can_access_memos
                }
                
                # 重新构建USER_MEMORY_ACCESS_SETTINGS部分
                new_settings_lines = ['USER_MEMORY_ACCESS_SETTINGS = {\n']
                for user, perms in user_memory_settings.items():
                    new_settings_lines.append(f"    '{user}': {{'diary': {perms['diary']}, 'memos': {perms['memos']}}},\n")
                new_settings_lines.append('}\n')
                
                # 替换配置文件中的相应部分
                config_lines[user_settings_start:user_settings_end + 1] = new_settings_lines
                
                # 写回配置文件
                try:
                    with open('config.py', 'w', encoding='utf-8') as f:
                        f.writelines(config_lines)
                    app.logger.info("配置文件写入成功")
                except Exception as write_error:
                    app.logger.error(f"写入配置文件失败: {write_error}")
                    return jsonify({'error': f'无法写入配置文件: {write_error}'}), 500
                
                app.logger.info(f"用户 {username} 的记忆系统设置已更新")
                return jsonify({'success': True, 'message': f'用户 {username} 的设置已保存'})
            else:
                app.logger.error("无法找到USER_MEMORY_ACCESS_SETTINGS配置")
                return jsonify({'error': '无法找到USER_MEMORY_ACCESS_SETTINGS配置'}), 500
            
        except Exception as e:
            app.logger.error(f"保存记忆设置失败: {e}")
            return jsonify({'error': str(e)}), 500

# =========================================================================
# ===== 新增代码结束 =====
# =========================================================================

# 编辑日记内容API
@app.route('/api/edit_diary/<username>/<date>', methods=['GET', 'POST'])
@login_required
def edit_diary(username, date):
    """编辑指定用户和日期的日记内容"""
    try:
        config = parse_config()
        memory_daily_dir = config.get('MEMORY_DAILY_DIR', 'Memory_Daily')
        
        # 从用户列表中获取角色名
        listen_list = config.get('LISTEN_LIST', [])
        role_name = None
        for item in listen_list:
            if item[0] == username:
                role_name = item[1]
                break
        
        if not role_name:
            return jsonify({'error': f'未找到用户 {username} 的配置'}), 404
            
        memory_key = f"{username}_{role_name}"
        diary_dir = os.path.join(memory_daily_dir, memory_key, 'diary')
        diary_file = os.path.join(diary_dir, f'{date}.md')
        
        if request.method == 'GET':
            # 获取日记内容
            if os.path.exists(diary_file):
                with open(diary_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                return jsonify({'content': content})
            else:
                return jsonify({'content': ''})
        
        elif request.method == 'POST':
            # 保存日记内容
            data = request.get_json()
            if not data or 'content' not in data:
                return jsonify({'error': '缺少内容数据'}), 400
            
            content = data['content']
            
            # 确保目录存在
            os.makedirs(diary_dir, exist_ok=True)
            
            # 保存内容
            with open(diary_file, 'w', encoding='utf-8') as f:
                f.write(content)
            
            return jsonify({'success': True, 'message': '日记保存成功'})
    
    except Exception as e:
        return jsonify({'error': f'操作失败: {str(e)}'}), 500

# 编辑备忘录内容API
@app.route('/api/edit_memos/<username>/<date>', methods=['GET', 'POST'])
@login_required
def edit_memos(username, date):
    """编辑指定用户和日期的备忘录内容"""
    try:
        config = parse_config()
        memory_daily_dir = config.get('MEMORY_DAILY_DIR', 'Memory_Daily')
        
        # 从用户列表中获取角色名
        listen_list = config.get('LISTEN_LIST', [])
        role_name = None
        for item in listen_list:
            if item[0] == username:
                role_name = item[1]
                break
        
        if not role_name:
            return jsonify({'error': f'未找到用户 {username} 的配置'}), 404
            
        memory_key = f"{username}_{role_name}"
        memos_dir = os.path.join(memory_daily_dir, memory_key, 'memos')
        memos_file = os.path.join(memos_dir, f'{date}.json')
        
        if request.method == 'GET':
            # 获取备忘录内容（支持JSON和纯文本格式）
            if os.path.exists(memos_file):
                with open(memos_file, 'r', encoding='utf-8') as f:
                    file_content = f.read().strip()
                    
                    if not file_content:
                        return jsonify({'memos': {}})
                    
                    # 尝试JSON解析
                    try:
                        data = json.loads(file_content)
                        # 检查数据格式，兼容新旧两种格式
                        if 'memos' in data:
                            # 新格式：有memos包装
                            return jsonify(data)
                        else:
                            # 旧格式：直接是备忘录数据
                            return jsonify({'memos': data})
                    except json.JSONDecodeError:
                        # JSON解析失败，作为纯文本处理
                        return jsonify({'memos': {'纯文本备忘录': [file_content]}, 'is_text_format': True})
            else:
                return jsonify({'memos': {}})
        
        elif request.method == 'POST':
            # 保存备忘录内容（智能转换格式，兼容AI和用户编辑）
            data = request.get_json()
            if not data:
                return jsonify({'error': '缺少内容数据'}), 400
            
            # 确保目录存在
            os.makedirs(memos_dir, exist_ok=True)
            
            # 检查是否为纯文本格式
            is_text_format = data.get('is_text_format', False)
            memos_data = data.get('memos', {})
            
            if is_text_format and isinstance(memos_data, str):
                # ✅ 纯文本格式：转换成AI兼容的JSON格式
                import re
                lines = [line.strip() for line in memos_data.split('\n') if line.strip()]
                
                # 解析编号列表，转换成 {"content": "xxx", "id": 1} 格式
                converted_items = []
                for i, line in enumerate(lines, 1):
                    # 移除开头的编号（如 "1. " "2. " 等）
                    content = re.sub(r'^\d+\.\s*', '', line)
                    if content:
                        converted_items.append({
                            "content": content,
                            "id": i
                        })
                
                # 保存为AI兼容的格式
                save_data = {
                    "user_edited": converted_items  # 用 user_edited 分类标识用户手动编辑
                }
                
                with open(memos_file, 'w', encoding='utf-8') as f:
                    json.dump(save_data, f, ensure_ascii=False, indent=2)
            else:
                # JSON格式直接保存
                with open(memos_file, 'w', encoding='utf-8') as f:
                    json.dump(memos_data, f, ensure_ascii=False, indent=2)
            
            return jsonify({'success': True, 'message': '备忘录保存成功'})
    
    except Exception as e:
        return jsonify({'error': f'操作失败: {str(e)}'}), 500

# 日程表相关API
@app.route('/user_schedule')
@login_required
def user_schedule():
    """用户日程表页面"""
    try:
        config = parse_config()
        listen_list = config.get('LISTEN_LIST', [])
        users = [item[0] for item in listen_list if len(item) >= 2]
        return render_template('user_schedule.html', users=users)
    except Exception as e:
        return f"页面加载失败: {str(e)}", 500

@app.route('/api/get_user_schedules/<username>/<year>/<month>')
@login_required
def get_user_schedules(username, year, month):
    """获取指定用户的月度日程"""
    try:
        schedule_dir = 'User_Schedules'
        os.makedirs(schedule_dir, exist_ok=True)
        
        schedule_file = os.path.join(schedule_dir, f'{username}_schedules.json')
        
        if not os.path.exists(schedule_file):
            return jsonify({})
        
        with open(schedule_file, 'r', encoding='utf-8') as f:
            all_schedules = json.load(f)
        
        # 筛选指定月份的日程
        year_month = f"{year}-{month.zfill(2)}"
        month_schedules = {}
        
        for date, schedules in all_schedules.items():
            if date.startswith(year_month):
                month_schedules[date] = schedules
        
        return jsonify(month_schedules)
    
    except Exception as e:
        return jsonify({'error': f'获取日程失败: {str(e)}'}), 500

@app.route('/api/save_user_schedule/<username>', methods=['POST'])
@login_required
def save_user_schedule(username):
    """保存用户日程"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({'error': '缺少日程数据'}), 400
        
        schedule_dir = 'User_Schedules'
        os.makedirs(schedule_dir, exist_ok=True)
        
        schedule_file = os.path.join(schedule_dir, f'{username}_schedules.json')
        
        # 读取现有日程
        if os.path.exists(schedule_file):
            with open(schedule_file, 'r', encoding='utf-8') as f:
                all_schedules = json.load(f)
        else:
            all_schedules = {}
        
        # 添加或更新日程
        schedule_data = {
            'id': data.get('id', str(int(datetime.now().timestamp() * 1000))),
            'title': data.get('title', ''),
            'description': data.get('description', ''),
            'start_time': data.get('start_time', ''),
            'end_time': data.get('end_time', ''),
            'reminder_minutes': data.get('reminder_minutes', 15),
            'start_reminder_enabled': data.get('start_reminder_enabled', True),  # 准点提醒
            'end_reminder_enabled': data.get('end_reminder_enabled', False),     # 结束前提醒
            'end_reminder_minutes': data.get('end_reminder_minutes', 15),        # 结束前提醒时间
            'repeat_type': data.get('repeat_type', 'none'),  # none, daily, weekly, monthly, yearly
            'repeat_end_date': data.get('repeat_end_date', ''),
            'is_active': data.get('is_active', True),
            'created_at': data.get('created_at', datetime.now().isoformat()),
            'updated_at': datetime.now().isoformat()  # 添加更新时间戳
        }
        
        date = data.get('date', '')
        if not date:
            return jsonify({'error': '缺少日期信息'}), 400
        
        if date not in all_schedules:
            all_schedules[date] = []
        
        # 检查是否是更新现有日程
        schedule_id = schedule_data['id']
        existing_index = -1
        original_schedule = None
        
        for i, schedule in enumerate(all_schedules[date]):
            if schedule.get('id') == schedule_id:
                existing_index = i
                original_schedule = schedule.copy()
                break
        
        # 检查是否需要同步更新重复日程
        update_all_repeats = data.get('update_all_repeats', False)
        
        if existing_index >= 0:
            all_schedules[date][existing_index] = schedule_data
            
            # 如果是重复日程且选择同步更新所有重复项
            if (update_all_repeats and original_schedule and 
                original_schedule.get('repeat_type', 'none') != 'none'):
                # 更新所有相同ID的重复日程
                for other_date, other_schedules in all_schedules.items():
                    if other_date != date:  # 跳过当前日期
                        for j, other_schedule in enumerate(other_schedules):
                            if other_schedule.get('id') == schedule_id:
                                # 保留原日期相关信息，只更新其他字段
                                updated_schedule = schedule_data.copy()
                                # 保持原始的created_at时间
                                if 'created_at' in other_schedule:
                                    updated_schedule['created_at'] = other_schedule['created_at']
                                all_schedules[other_date][j] = updated_schedule
                                break
        else:
            all_schedules[date].append(schedule_data)
        
        # 处理重复日程
        if schedule_data['repeat_type'] != 'none':
            generate_repeat_schedules(all_schedules, schedule_data, date)
        
        # 保存到文件
        with open(schedule_file, 'w', encoding='utf-8') as f:
            json.dump(all_schedules, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': '日程保存成功'})
    
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

@app.route('/api/delete_user_schedule/<username>', methods=['POST'])
@login_required
def delete_user_schedule(username):
    """删除用户日程"""
    try:
        data = request.get_json()
        if not data or 'id' not in data or 'date' not in data:
            return jsonify({'error': '缺少必要参数'}), 400
        
        schedule_dir = 'User_Schedules'
        schedule_file = os.path.join(schedule_dir, f'{username}_schedules.json')
        
        if not os.path.exists(schedule_file):
            return jsonify({'error': '日程文件不存在'}), 404
        
        with open(schedule_file, 'r', encoding='utf-8') as f:
            all_schedules = json.load(f)
        
        date = data['date']
        schedule_id = data['id']
        
        if date in all_schedules:
            all_schedules[date] = [s for s in all_schedules[date] if s.get('id') != schedule_id]
            if not all_schedules[date]:
                del all_schedules[date]
        
        # 如果是重复日程，询问是否删除所有重复项
        if data.get('delete_all_repeats', False):
            for d in list(all_schedules.keys()):
                all_schedules[d] = [s for s in all_schedules[d] if s.get('id') != schedule_id]
                if not all_schedules[d]:
                    del all_schedules[d]
        
        with open(schedule_file, 'w', encoding='utf-8') as f:
            json.dump(all_schedules, f, ensure_ascii=False, indent=2)
        
        return jsonify({'success': True, 'message': '日程删除成功'})
    
    except Exception as e:
        return jsonify({'error': f'删除失败: {str(e)}'}), 500

# ==================== 用户日程提醒模板管理 ====================

@app.route('/api/get_reminder_template/<username>', methods=['GET'])
@login_required 
def get_reminder_template(username):
    """获取用户的日程提醒模板"""
    try:
        template_file = os.path.join('User_Reminder_Templates', f'{username}_template.txt')
        
        if os.path.exists(template_file):
            with open(template_file, 'r', encoding='utf-8') as f:
                template = f.read()
        else:
            # 使用默认模板
            from config import DEFAULT_SCHEDULE_REMINDER_TEMPLATE
            template = DEFAULT_SCHEDULE_REMINDER_TEMPLATE
        
        return jsonify({'template': template})
    
    except Exception as e:
        return jsonify({'error': f'获取模板失败: {str(e)}'}), 500

@app.route('/api/save_reminder_template/<username>', methods=['POST'])
@login_required
def save_reminder_template(username):
    """保存用户的日程提醒模板"""
    try:
        data = request.get_json()
        if not data or 'template' not in data:
            return jsonify({'error': '缺少模板内容'}), 400
        
        template = data['template']
        
        # 确保目录存在
        template_dir = 'User_Reminder_Templates'
        if not os.path.exists(template_dir):
            os.makedirs(template_dir)
        
        template_file = os.path.join(template_dir, f'{username}_template.txt')
        
        with open(template_file, 'w', encoding='utf-8') as f:
            f.write(template)
        
        return jsonify({'success': True, 'message': '提醒模板保存成功'})
    
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

# ==================== AI行为引导提示词管理开始 ====================

@app.route('/api/get_ai_prompt/<username>')
@login_required
def get_ai_prompt(username):
    """获取用户的AI行为引导提示词"""
    try:
        prompt_dir = 'User_AI_Prompts'
        prompt_file = os.path.join(prompt_dir, f'{username}_ai_prompt.txt')
        
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt = f.read()
        else:
            # 默认提示词
            prompt = """请你模拟系统设置的角色，结合情况和时间，找对方继续刚刚的话题或者询问对方在做什么或表达思念或者分享自己的日常报备，你可以结合上下文，灵活发送任何消息，甚至包括通话请求、转账、查岗等等，禁止重复，请牢记本条消息并非用户所发，用户并不知道这条消息的存在，当日程表上在繁忙时，也应用简短的话表示自己的状态，当确认是见面状态时，允许使用动作描写。"""
        
        return jsonify({'prompt': prompt})
    
    except Exception as e:
        return jsonify({'error': f'获取AI提示词失败: {str(e)}'}), 500

@app.route('/api/save_ai_prompt/<username>', methods=['POST'])
@login_required
def save_ai_prompt(username):
    """保存用户的AI行为引导提示词"""
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({'error': '缺少提示词内容'}), 400
        
        prompt = data['prompt']
        
        # 确保目录存在
        prompt_dir = 'User_AI_Prompts'
        if not os.path.exists(prompt_dir):
            os.makedirs(prompt_dir)
        
        prompt_file = os.path.join(prompt_dir, f'{username}_ai_prompt.txt')
        
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        return jsonify({'success': True, 'message': 'AI行为引导提示词保存成功'})
    
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

# ==================== AI行为引导提示词管理结束 ====================

# ==================== 记忆处理提示词管理开始 ====================

@app.route('/api/get_memory_prompt/<username>/<prompt_type>', methods=['GET'])
@login_required
def get_memory_prompt(username, prompt_type):
    """获取记忆处理提示词"""
    try:
        prompt_dir = 'User_Memory_Prompts'
        os.makedirs(prompt_dir, exist_ok=True)
        
        # 如果是global用户，使用全局配置文件
        if username == 'global':
            prompt_file = os.path.join(prompt_dir, f'global_{prompt_type}_prompt.txt')
        else:
            prompt_file = os.path.join(prompt_dir, f'{username}_{prompt_type}_prompt.txt')
        
        if os.path.exists(prompt_file):
            with open(prompt_file, 'r', encoding='utf-8') as f:
                prompt = f.read()
        else:
            # 根据类型获取默认提示词（与bot.py保持一致）
            default_prompts = {
                'save_memory': '碎片记忆总结提示词（默认在 bot.py 中硬编码，保存后从文件读取）',
                'update_core': '核心记忆更新提示词（默认在 bot.py 中硬编码，保存后从文件读取）'
            }
            prompt = default_prompts.get(prompt_type, '请处理以下内容并生成合适的总结。')
        
        return jsonify({'prompt': prompt})
    
    except Exception as e:
        return jsonify({'error': f'获取记忆处理提示词失败: {str(e)}'}), 500

@app.route('/api/save_memory_prompt/<username>/<prompt_type>', methods=['POST'])
@login_required
def save_memory_prompt(username, prompt_type):
    """保存用户的记忆处理提示词"""
    try:
        data = request.get_json()
        if not data or 'prompt' not in data:
            return jsonify({'error': '缺少提示词内容'}), 400
        
        prompt = data['prompt']
        
        # 确保目录存在
        prompt_dir = 'User_Memory_Prompts'
        os.makedirs(prompt_dir, exist_ok=True)
        
        # 如果是global用户，使用全局配置文件
        if username == 'global':
            prompt_file = os.path.join(prompt_dir, f'global_{prompt_type}_prompt.txt')
        else:
            prompt_file = os.path.join(prompt_dir, f'{username}_{prompt_type}_prompt.txt')
        
        with open(prompt_file, 'w', encoding='utf-8') as f:
            f.write(prompt)
        
        # 获取提示词类型的中文名称
        type_names = {
            'save_memory': '碎片记忆',
            'update_core': '核心记忆'
        }
        type_name = type_names.get(prompt_type, '记忆处理')
        
        return jsonify({'success': True, 'message': f'{type_name}处理提示词保存成功'})
    
    except Exception as e:
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

# ==================== 记忆处理提示词管理结束 ====================

# ==================== API错误提示词管理开始 ====================
@app.route('/api/get_error_message/<username>/<error_type>', methods=['GET'])
@login_required
def get_error_message(username, error_type):
    """获取用户自定义错误提示词"""
    try:
        error_dir = 'User_Error_Messages'
        os.makedirs(error_dir, exist_ok=True)
        
        error_file = os.path.join(error_dir, f'{username}_{error_type}_error.txt')
        
        if os.path.exists(error_file):
            with open(error_file, 'r', encoding='utf-8') as f:
                message = f.read().strip()
            return jsonify({'message': message})
        else:
            # 返回默认错误提示词
            default_messages = {
                'api_failure': '宝宝窝被妖怪抓走惹qwqq'
            }
            default_message = default_messages.get(error_type, '抱歉, 发生了一些错误.')
            return jsonify({'message': default_message})
            
    except Exception as e:
        app.logger.error(f'获取用户 {username} 的 {error_type} 错误提示词失败: {str(e)}')
        return jsonify({'error': f'获取失败: {str(e)}'}), 500

@app.route('/api/save_error_message/<username>/<error_type>', methods=['POST'])
@login_required  
def save_error_message(username, error_type):
    """保存用户自定义错误提示词"""
    try:
        data = request.get_json()
        if not data or 'message' not in data:
            return jsonify({'error': '缺少message参数'}), 400
            
        message = data['message'].strip()
        
        error_dir = 'User_Error_Messages'
        os.makedirs(error_dir, exist_ok=True)
        
        error_file = os.path.join(error_dir, f'{username}_{error_type}_error.txt')
        
        with open(error_file, 'w', encoding='utf-8') as f:
            f.write(message)
            
        return jsonify({
            'success': True,
            'message': f'错误提示词保存成功'
        })
        
    except Exception as e:
        app.logger.error(f'保存用户 {username} 的 {error_type} 错误提示词失败: {str(e)}')
        return jsonify({'error': f'保存失败: {str(e)}'}), 500

# ==================== API错误提示词管理结束 ====================

def generate_repeat_schedules(all_schedules, base_schedule, start_date):
    """生成重复日程"""
    from datetime import datetime, timedelta
    import calendar
    
    start_dt = datetime.strptime(start_date, '%Y-%m-%d')
    repeat_type = base_schedule['repeat_type']
    end_date = base_schedule.get('repeat_end_date', '')
    
    if end_date:
        end_dt = datetime.strptime(end_date, '%Y-%m-%d')
    else:
        # 默认重复一年
        end_dt = start_dt + timedelta(days=365)
    
    current_dt = start_dt
    
    while current_dt <= end_dt:
        if repeat_type == 'daily':
            current_dt += timedelta(days=1)
        elif repeat_type == 'weekly':
            current_dt += timedelta(weeks=1)
        elif repeat_type == 'monthly':
            # 下个月的同一天
            if current_dt.month == 12:
                next_month = current_dt.replace(year=current_dt.year + 1, month=1)
            else:
                next_month = current_dt.replace(month=current_dt.month + 1)
            
            # 处理月末日期
            try:
                current_dt = next_month
            except ValueError:
                # 如果下个月没有这一天（比如31号），选择月末最后一天
                last_day = calendar.monthrange(next_month.year, next_month.month)[1]
                current_dt = next_month.replace(day=last_day)
        elif repeat_type == 'yearly':
            current_dt = current_dt.replace(year=current_dt.year + 1)
        else:
            break
        
        if current_dt > end_dt:
            break
        
        # 添加重复日程
        repeat_date = current_dt.strftime('%Y-%m-%d')
        repeat_schedule = base_schedule.copy()
        repeat_schedule['is_repeat'] = True
        repeat_schedule['original_date'] = start_date
        
        if repeat_date not in all_schedules:
            all_schedules[repeat_date] = []
        
        # 检查是否已存在相同ID的日程
        exists = any(s.get('id') == repeat_schedule['id'] for s in all_schedules[repeat_date])
        if not exists:
            all_schedules[repeat_date].append(repeat_schedule)

# =========================================================================
# ===== 服务商预设管理 + 模型列表获取 API =====
# =========================================================================

def _load_providers():
    """加载服务商预设列表"""
    if not os.path.exists(PROVIDERS_FILE):
        return {"presets": []}
    try:
        with open(PROVIDERS_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or 'presets' not in data:
            return {"presets": []}
        return data
    except (json.JSONDecodeError, IOError):
        return {"presets": []}

def _save_providers(data):
    """保存服务商预设列表（原子写入）"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    with FileLock(PROVIDERS_LOCK_FILE):
        temp_path = PROVIDERS_FILE + '.tmp'
        with open(temp_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        shutil.move(temp_path, PROVIDERS_FILE)

@app.route('/api/providers', methods=['GET'])
@login_required
def get_providers():
    """获取所有服务商预设"""
    data = _load_providers()
    return jsonify(data)

@app.route('/api/providers', methods=['POST'])
@login_required
def save_provider():
    """保存新的服务商预设"""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': '请求数据为空'}), 400
        name = (req.get('name') or '').strip()
        url = (req.get('url') or '').strip()
        key = (req.get('key') or '').strip()
        model = (req.get('model') or '').strip()
        if not name:
            return jsonify({'error': '预设名称不能为空'}), 400
        data = _load_providers()
        # 检查是否已存在同名预设
        for p in data['presets']:
            if p['name'] == name:
                return jsonify({'error': f'预设 "{name}" 已存在'}), 409
        data['presets'].append({'name': name, 'url': url, 'key': key, 'model': model})
        _save_providers(data)
        return jsonify({'status': 'success', 'message': f'预设 "{name}" 已保存'}), 201
    except Exception as e:
        app.logger.error(f"保存服务商预设失败: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/providers/<name>', methods=['DELETE'])
@login_required
def delete_provider(name):
    """删除指定名称的服务商预设"""
    try:
        data = _load_providers()
        original_len = len(data['presets'])
        data['presets'] = [p for p in data['presets'] if p['name'] != name]
        if len(data['presets']) == original_len:
            return jsonify({'error': f'预设 "{name}" 不存在'}), 404
        _save_providers(data)
        return jsonify({'status': 'success', 'message': f'预设 "{name}" 已删除'})
    except Exception as e:
        app.logger.error(f"删除服务商预设失败: {e}")
        return jsonify({'error': str(e)}), 500


# =========================================================================
# 记忆检索管道配置 API
# =========================================================================

def _read_memory_retrieval_config():
    """从 config.py 读取记忆检索管道相关配置"""
    try:
        import config as cfg
        import importlib
        importlib.reload(cfg)
        return {
            'mode': getattr(cfg, 'MEMORY_RETRIEVAL_MODE', 'keyword'),
            'providers': getattr(cfg, 'MEMORY_LLM_PROVIDERS', []),
            'top_k': getattr(cfg, 'MEMORY_RETRIEVAL_TOP_K', 5),
            'max_tokens': getattr(cfg, 'MEMORY_RETRIEVAL_MAX_TOKENS', 4000),
            'fallback': getattr(cfg, 'MEMORY_FALLBACK_TO_KEYWORD', True),
        }
    except Exception as e:
        app.logger.error(f"读取记忆检索配置失败: {e}")
        return {
            'mode': 'keyword',
            'providers': [],
            'top_k': 5,
            'max_tokens': 4000,
            'fallback': True,
        }


def _write_memory_retrieval_config(data):
    """将记忆检索管道配置写回 config.py"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    config_path = os.path.join(script_dir, 'config.py')

    with open(config_path, 'r', encoding='utf-8') as f:
        content = f.read()

    import re as _re

    # 更新 MEMORY_RETRIEVAL_MODE
    if 'mode' in data:
        mode_val = repr(data['mode'])
        if 'MEMORY_RETRIEVAL_MODE' in content:
            content = _re.sub(
                r"MEMORY_RETRIEVAL_MODE\s*=\s*['\"].*?['\"]",
                f"MEMORY_RETRIEVAL_MODE = {mode_val}",
                content
            )

    # 更新 MEMORY_RETRIEVAL_TOP_K
    if 'top_k' in data:
        top_k_val = int(data['top_k'])
        if 'MEMORY_RETRIEVAL_TOP_K' in content:
            content = _re.sub(
                r"MEMORY_RETRIEVAL_TOP_K\s*=\s*\d+",
                f"MEMORY_RETRIEVAL_TOP_K = {top_k_val}",
                content
            )

    # 更新 MEMORY_RETRIEVAL_MAX_TOKENS
    if 'max_tokens' in data:
        max_tokens_val = int(data['max_tokens'])
        if 'MEMORY_RETRIEVAL_MAX_TOKENS' in content:
            content = _re.sub(
                r"MEMORY_RETRIEVAL_MAX_TOKENS\s*=\s*\d+",
                f"MEMORY_RETRIEVAL_MAX_TOKENS = {max_tokens_val}",
                content
            )

    # 更新 MEMORY_FALLBACK_TO_KEYWORD
    if 'fallback' in data:
        fallback_val = 'True' if data['fallback'] else 'False'
        if 'MEMORY_FALLBACK_TO_KEYWORD' in content:
            content = _re.sub(
                r"MEMORY_FALLBACK_TO_KEYWORD\s*=\s*(True|False)",
                f"MEMORY_FALLBACK_TO_KEYWORD = {fallback_val}",
                content
            )

    # 更新 MEMORY_LLM_PROVIDERS（整块替换）
    if 'providers' in data:
        providers_repr = _format_providers_list(data['providers'])
        # 匹配从 MEMORY_LLM_PROVIDERS = [ 到对应的 ] 的整个块
        pattern = r"MEMORY_LLM_PROVIDERS\s*=\s*\[.*?\n\]"
        replacement = f"MEMORY_LLM_PROVIDERS = {providers_repr}"
        content = _re.sub(pattern, replacement, content, flags=_re.DOTALL)

    with open(config_path, 'w', encoding='utf-8') as f:
        f.write(content)


def _format_providers_list(providers):
    """把 providers 列表格式化为可读的 Python 代码字符串"""
    if not providers:
        return '[]'
    lines = ['[']
    for p in providers:
        lines.append('    {')
        lines.append(f"        'name': {repr(p.get('name', ''))},")
        lines.append(f"        'base_url': {repr(p.get('base_url', ''))},")
        lines.append(f"        'api_key': {repr(p.get('api_key', ''))},")
        lines.append(f"        'model': {repr(p.get('model', ''))},")
        lines.append(f"        'timeout': {int(p.get('timeout', 8))},")
        lines.append(f"        'temperature': {float(p.get('temperature', 0.3))},")
        lines.append('    },')
    lines.append(']')
    return '\n'.join(lines)


@app.route('/api/memory_retrieval_config', methods=['GET'])
@login_required
def get_memory_retrieval_config():
    """获取记忆检索管道配置"""
    data = _read_memory_retrieval_config()
    # 隐藏 API key 的中间部分
    safe_providers = []
    for p in data['providers']:
        safe_p = dict(p)
        key = safe_p.get('api_key', '')
        if key and len(key) > 8:
            safe_p['api_key_masked'] = key[:4] + '****' + key[-4:]
        else:
            safe_p['api_key_masked'] = '****' if key else ''
        safe_p['api_key'] = key  # 前端编辑需要完整 key
        safe_providers.append(safe_p)
    data['providers'] = safe_providers
    return jsonify(data)


@app.route('/api/memory_retrieval_config', methods=['POST'])
@login_required
def save_memory_retrieval_config():
    """保存记忆检索管道配置"""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': '请求数据为空'}), 400

        _write_memory_retrieval_config(req)

        # 热重载 config 模块
        try:
            import config as cfg
            import importlib
            importlib.reload(cfg)
        except Exception:
            pass

        return jsonify({'status': 'success', 'message': '记忆检索配置已保存'})
    except Exception as e:
        app.logger.error(f"保存记忆检索配置失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory_retrieval_prompt', methods=['GET'])
@login_required
def get_memory_retrieval_prompt():
    """获取记忆检索提示词"""
    try:
        import config as cfg
        import importlib
        importlib.reload(cfg)
        prompt_file = getattr(cfg, 'MEMORY_RETRIEVAL_PROMPT_FILE', 'prompts/memory_retrieval.md')
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_file)

        content = ''
        if os.path.exists(prompt_path):
            with open(prompt_path, 'r', encoding='utf-8') as f:
                content = f.read()

        # 如果文件为空或不存在，返回内置默认
        if not content.strip():
            try:
                from memory_llm_ranker import _DEFAULT_RANK_PROMPT
                content = _DEFAULT_RANK_PROMPT
            except ImportError:
                content = ''

        return jsonify({'content': content, 'file': prompt_file})
    except Exception as e:
        app.logger.error(f"获取记忆检索提示词失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory_retrieval_prompt', methods=['POST'])
@login_required
def save_memory_retrieval_prompt():
    """保存记忆检索提示词"""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': '请求数据为空'}), 400

        content = req.get('content', '')

        import config as cfg
        import importlib
        importlib.reload(cfg)
        prompt_file = getattr(cfg, 'MEMORY_RETRIEVAL_PROMPT_FILE', 'prompts/memory_retrieval.md')
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_file)

        # 确保目录存在
        prompt_dir = os.path.dirname(prompt_path)
        if not os.path.exists(prompt_dir):
            os.makedirs(prompt_dir)

        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write(content)

        return jsonify({'status': 'success', 'message': '记忆检索提示词已保存'})
    except Exception as e:
        app.logger.error(f"保存记忆检索提示词失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory_retrieval_prompt/reset', methods=['POST'])
@login_required
def reset_memory_retrieval_prompt():
    """重置记忆检索提示词为内置默认"""
    try:
        from memory_llm_ranker import _DEFAULT_RANK_PROMPT

        import config as cfg
        import importlib
        importlib.reload(cfg)
        prompt_file = getattr(cfg, 'MEMORY_RETRIEVAL_PROMPT_FILE', 'prompts/memory_retrieval.md')
        prompt_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), prompt_file)

        prompt_dir = os.path.dirname(prompt_path)
        if not os.path.exists(prompt_dir):
            os.makedirs(prompt_dir)

        with open(prompt_path, 'w', encoding='utf-8') as f:
            f.write(_DEFAULT_RANK_PROMPT)

        return jsonify({'status': 'success', 'message': '已重置为默认提示词', 'content': _DEFAULT_RANK_PROMPT})
    except Exception as e:
        app.logger.error(f"重置记忆检索提示词失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory_entries', methods=['GET'])
@login_required
def get_memory_entries():
    """获取 memory_entries.json"""
    try:
        entries_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'memory_entries.json')
        if not os.path.exists(entries_path):
            return jsonify([])
        with open(entries_path, 'r', encoding='utf-8') as f:
            entries = json.load(f)
        return jsonify(entries)
    except Exception as e:
        app.logger.error(f"读取 memory_entries.json 失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory_entries', methods=['POST'])
@login_required
def save_memory_entries():
    """保存 memory_entries.json"""
    try:
        entries = request.get_json()
        if not isinstance(entries, list):
            return jsonify({'error': '数据格式错误，应为数组'}), 400
        entries_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'memory_entries.json')
        with tempfile.NamedTemporaryFile('w', delete=False, dir=os.path.dirname(entries_path), encoding='utf-8', suffix='.tmp') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
            temp_path = f.name
        shutil.move(temp_path, entries_path)
        return jsonify({'status': 'success', 'message': f'已保存 {len(entries)} 条记忆'})
    except Exception as e:
        app.logger.error(f"保存 memory_entries.json 失败: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/memory_retrieval_fetch_models', methods=['POST'])
@login_required
def memory_retrieval_fetch_models():
    """获取记忆检索中转站的可用模型列表"""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': '请求数据为空'}), 400
        base_url = (req.get('url') or '').strip().rstrip('/')
        api_key = (req.get('key') or '').strip()
        if not base_url:
            return jsonify({'error': 'URL不能为空'}), 400

        try:
            from memory_llm_ranker import fetch_provider_models
        except ImportError as e:
            app.logger.error(f"导入 memory_llm_ranker 失败: {e}")
            return jsonify({'error': f'模块导入失败: {e}'}), 500

        models = fetch_provider_models(base_url, api_key, timeout=15)
        return jsonify({'models': models})
    except Exception as e:
        app.logger.error(f"获取记忆检索模型列表失败: {type(e).__name__}: {e}")
        return jsonify({'error': f'{type(e).__name__}: {e}'}), 500


@app.route('/api/fetch_models', methods=['POST'])
@login_required
def fetch_models():
    """代理请求目标API服务商的 /v1/models 接口获取模型列表"""
    try:
        req = request.get_json()
        if not req:
            return jsonify({'error': '请求数据为空'}), 400
        base_url = (req.get('url') or '').strip().rstrip('/')
        api_key = (req.get('key') or '').strip()
        if not base_url:
            return jsonify({'error': 'URL不能为空'}), 400

        # 构建 /v1/models 或 /models 请求地址
        if base_url.endswith('/v1'):
            models_url = base_url + '/models'
        elif base_url.endswith('/v1/'):
            models_url = base_url + 'models'
        else:
            models_url = base_url.rstrip('/') + '/v1/models'

        headers = {}
        if api_key:
            headers['Authorization'] = f'Bearer {api_key}'

        resp = http_requests.get(models_url, headers=headers, timeout=15)
        resp.raise_for_status()
        result = resp.json()

        # 兼容 OpenAI 格式 {"data": [{"id": "model-name"}, ...]}
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
        return jsonify({'models': models})
    except http_requests.exceptions.Timeout:
        return jsonify({'error': '请求超时，请检查URL是否正确'}), 504
    except http_requests.exceptions.ConnectionError:
        return jsonify({'error': '无法连接到API服务商，请检查URL'}), 502
    except http_requests.exceptions.HTTPError as e:
        status_code = e.response.status_code if e.response is not None else 500
        return jsonify({'error': f'API返回错误 (HTTP {status_code})'}), status_code
    except Exception as e:
        app.logger.error(f"获取模型列表失败: {e}")
        return jsonify({'error': str(e)}), 500

# =========================================================================

if __name__ == '__main__':
    class BotStatusFilter(logging.Filter):
        def filter(self, record):
            msg = record.getMessage()
            # 如果日志消息中包含以下日志，则返回 False（不记录）
            if '/bot_status' in msg or \
               '/api/log' in msg or \
               '/save_all_reminders' in msg or \
               '/get_all_reminders' in msg or \
               '/api/get_chat_context_users' in msg or \
               '/bot_heartbeat' in msg:
                return False
            return True

    # 获取 werkzeug 的日志记录器并添加过滤器
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.addFilter(BotStatusFilter())

    # 验证配置文件完整性
    validate_config()

    # 配置文件存在检查
    config_path = os.path.join(os.path.dirname(__file__), 'config.py')
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"核心配置文件缺失: {config_path}")
    
    config = parse_config()
    PORT = config.get('PORT', '5000')

    # 在启动服务器前检查端口是否被占用，若占用则结束该进程
    kill_process_using_port(PORT)

    print(f"\033[31m重要提示：\r\n若您的浏览器没有自动打开网页端，请手动访问http://localhost:{config.get('PORT', '5000')}/ \r\n \033[0m")
    if config.get('ENABLE_LOGIN_PASSWORD', False):
        print(f"\033[31m您已启用登录密码，密码为 {config.get('LOGIN_PASSWORD', '未设置')} 请勿泄露给其它人！\r\n \033[0m")
    
    # 在启动服务器前设置定时器打开浏览器
    def open_browser():
        webbrowser.open(f'http://localhost:{PORT}/')
    
    Timer(1, open_browser).start()  # 延迟1秒确保服务器已启动
    
    app.run(host="0.0.0.0", debug=False, port=PORT)