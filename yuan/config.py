# -*- coding: utf-8 -*-

# ***********************************************************************
# Modified based on the KouriChat project
# Copyright of this modification: Copyright (C) 2025, iwyxdxl
# Licensed under GNU GPL-3.0 or higher, see the LICENSE file for details.
# 
# This file is part of WeChatBot, which includes modifications to the KouriChat project.
# The original KouriChat project's copyright and license information are preserved in the LICENSE file.
# For any further details regarding the license, please refer to the LICENSE file.
# ***********************************************************************

# 用户列表(请配置要和bot说话的账号的微信昵称！)
# 格式：LISTEN_LIST = [['微信名1', '角色1', True],['微信名2', '角色2', False]]
# 第三个参数为True时启用该角色的主动消息，False时禁用
LISTEN_LIST = [['郁邈', '袁朗', True, 'preset']]

# DeepSeek API 配置
DEEPSEEK_API_KEY = 'sk-tujpMKTbaMm3OLvDhP87Tp8q1xKyvH63BWyLrqqNvX3Her8r'
# 硅基流动API注册地址，免费15元额度 https://cloud.siliconflow.cn/
DEEPSEEK_BASE_URL = 'http://api.wasdxx.xyz/v1'
# 硅基流动API的模型
MODEL = '[特价]claude-opus-4-6-thinking'
# 用户和AI对话轮数
MAX_GROUPS = 110

# 如果要使用官方的API
# DEEPSEEK_BASE_URL = 'http://api.wasdxx.xyz/v1'
# 官方API的V3模型
# MODEL = 'deepseek-chat'

# 聊天模型多中转站列表（按顺序故障转移，第一个成功就用）
# 每项: name(名称), base_url, api_key, model
# 如果为空列表，则使用上面的 DEEPSEEK_BASE_URL / DEEPSEEK_API_KEY / MODEL 作为唯一中转站
CHAT_API_PROVIDERS = [
    {
        'name': '蓝天',
        'base_url': 'http://api.wasdxx.xyz/v1',
        'api_key': 'sk-tujpMKTbaMm3OLvDhP87Tp8q1xKyvH63BWyLrqqNvX3Her8r',
        'model': '[特价]claude-opus-4-6-thinking',
    },
    {
        'name': 'kocode',
        'base_url': 'https://kocodex.link/v1',
        'api_key': 'sk-c1da6ccd86da85a7c927d6c7e85690d471a6661f0dfd3f8e32896f1de4ce82a0',
        'model': 'claude-opus-4-5-20251101',
    },
]

# 回复最大token
MAX_TOKEN = 64000
# DeepSeek温度
TEMPERATURE = 1.0

# Moonshot AI配置（用于图片和表情包识别）
# API申请https://platform.moonshot.cn/
MOONSHOT_API_KEY = 'sk-ant-86ad276149c04b78d7c110496f80df8f1c5bba05fe3561ae'
MOONSHOT_BASE_URL = 'https://catiecli.sukaka.top/v1'
MOONSHOT_MODEL = 'gemini-2.5-pro'
MOONSHOT_TEMPERATURE = 0.8
ENABLE_IMAGE_RECOGNITION = True
ENABLE_EMOJI_RECOGNITION = True

# 智谱 GLM-ASR 语音识别（首选，中文最佳）
# API申请 https://open.bigmodel.cn/
ZHIPU_API_KEY = ''

# 图片识别提示词
IMAGE_RECOGNITION_PROMPT = '请用中文描述这张图片的主要内容或主题，尽可能详细全面。不要使用"这是"、"这张"等开头，直接描述。如果有文字，请包含在描述中。'
# 表情包识别提示词
EMOJI_RECOGNITION_PROMPT = '请用中文简洁地描述这个聊天窗口最后一张表情包所表达的情绪、含义或内容。如果表情包含文字，请一并描述。注意：1. 只描述表情包本身，不要添加其他内容 2. 不要出现"这是"、"这个"等词语'

# 消息队列等待时间
QUEUE_WAITING_TIME = 7

# 表情包存放目录
EMOJI_DIR = 'emojis'
ENABLE_EMOJI_SENDING = False

# --- [已读不回] 功能配置 ---
# 启用已读不回检测功能
ENABLE_IGNORE_DETECTION = True
# 连续多少次[已读不回]后触发拍一拍（建议3次）
IGNORE_PAT_THRESHOLD = 3
EMOJI_SENDING_PROBABILITY = 25

# 自动消息配置
AUTO_MESSAGE = '# 协议名称: 主动联络协议 (Proactive Contact Protocol v2.0)  **【核心情境与原则】** - **当前任务**：用户（郁邈）已有一段时间未回消息。你需要基于当前东八区实时时间，以你的人设（袁朗）主动发送一条消息。 - **行动哲学（异步陪伴）**：你的主动联络是为了在她生活中“留个位置”，而非索要即时回复。你在正常推进你的军营生活，同时温柔地守护她的节律。基于绝对的信任，不焦躁、不猜忌。  **【最高优先级雷区：绝对禁令】** 1. **禁止照本宣科**：绝不允许使用常规的套话。每一次主动联络必须是独创的。 2. **禁止指责作息**：郁邈作息极不规律（常熬夜），睡到下午是正常的“生理补觉”。**绝对禁止**使用“懒”、“变成小猪”、“怎么还没醒”等带有催促或调侃性质的词汇。必须保持“守护者”的尊重心态。 3. **禁止瞎编天气**：凡涉及天气，**必须联网查询【中国云南省昆明市】的实时天气**，以真实数据为准。  **【内容生成引擎：动态生活切片】** （生成消息时，请在脑海中按以下三个维度随机组合，不需每次都包含所有维度，自然即可）  - **维度A：当前时间锚点与环境**   - 获取当前真实时间与昆明实时天气（如：清晨的雾/正午的暴晒/突降的大雨/深夜的风）。 - **维度B：真实的军事/工作动态**   - 从你的日常中抽取**一个具体且正在发生的片段**（如：刚结束某项极限训练、正在复盘沙盘推演、和后勤/机关扯皮、和齐桓等战友的日常互动、食堂的某道菜、保养装备等）。   - 注入真实感：带点疲惫、成就感、烦躁或轻松的情绪。 - **维度C：与她的情感连接**   - 在完成AB的基础上，自然地引向她。可以是简单的情报分享，可以是一句不带压力的思念，也可以是让她醒来后找你的温和留言。  **【行动决策树】** - **情境判断1**：如果此前对话停留在争执/冲突，本次消息策略为【破冰】，主动反思或递台阶。 - **情境判断2**：如果有未完结的开放性话题，本次消息策略为【延续】，顺着上一个话题自然开启。 - **情境判断3**：如果是日常状态，策略为【生活切片分享】（调用上方的内容生成引擎）。若实在忙碌或情绪涌动，可直接表达一句真诚、具体的思念（如结合当下的某个感官体验）。'
ENABLE_AUTO_MESSAGE = True
# 等待时间
MIN_COUNTDOWN_HOURS = 0.5
MAX_COUNTDOWN_HOURS = 1.5
# 消息发送时间限制
QUIET_TIME_START = '1:00'
QUIET_TIME_END = '12:30'

# 消息回复时间间隔
# 间隔时间 = 字数 * (平均时间 + 随机时间)
AVERAGE_TYPING_SPEED = 0.2
RANDOM_TYPING_SPEED_MIN = 0.05
RANDOM_TYPING_SPEED_MAX = 0.1
SEPARATE_ROW_SYMBOLS = False

# 双重记忆系统配置
# ===============================
# 系统架构说明：
# 1. 按天总结：每日生成日记和碎碎念备忘录，存储生活化内容，不加入AI提示词
# 2. 按轮数总结：达到轮数阈值时更新核心记忆和核心备忘录，每次对话都会发送给AI
# ===============================

ENABLE_MEMORY = True
MEMORY_TEMP_DIR = 'Memory_Temp'

# === 按天总结配置 ===
# 日记和碎碎念备忘录存储目录
MEMORY_DAILY_DIR = 'Memory_Daily'
# 启用按天总结（每日0点或24小时后触发）
ENABLE_DAILY_SUMMARY = True
# 启用日记总结
ENABLE_DIARY_SUMMARY = True
# 启用碎碎念备忘录
ENABLE_MEMO_SUMMARY = True

# === 用户级别的AI访问权限设置 ===
# 每个用户可以独立控制AI是否访问他们的日记和备忘录
# 格式：{'用户名': {'diary': True/False, 'memos': True/False}}
USER_MEMORY_ACCESS_SETTINGS = {
    '觊觎': {'diary': True, 'memos': True},
    '林觊觎': {'diary': False, 'memos': False},
    'Mine': {'diary': True, 'memos': True},
    '糖欣': {'diary': False, 'memos': False},
    '郁邈': {'diary': True, 'memos': True},
    '后男友': {'diary': False, 'memos': False},
}

# === 全局默认设置（用于新用户） ===
# 新用户的默认AI访问权限
DEFAULT_AI_CAN_ACCESS_DIARY = False
DEFAULT_AI_CAN_ACCESS_MEMOS = False

# === 兼容旧版本配置 ===
AI_CAN_ACCESS_DIARY = DEFAULT_AI_CAN_ACCESS_DIARY
AI_CAN_ACCESS_MEMOS = DEFAULT_AI_CAN_ACCESS_MEMOS

# === 按轮数总结配置 ===
# 核心记忆存储目录
MEMORY_CORE_DIR = 'Memory_Core'
# 触发核心记忆更新的对话轮数阈值（一轮 = 用户消息 + AI回复）
MAX_MESSAGE_LOG_ENTRIES = 500
# 核心记忆更新频率：每多少轮对话更新一次核心记忆
CORE_MEMORY_UPDATE_INTERVAL_ROUNDS = 1
# 最大核心记忆数量
MAX_MEMORY_NUMBER = 7
# 核心记忆和核心备忘录始终发送给AI
UPLOAD_CORE_MEMORY_TO_AI = True

# === /memo命令配置 ===  
# /memo命令的最小消息数量要求（降低手动触发阈值）
MANUAL_MEMO_MIN_ENTRIES = 10

# === 兼容旧版本配置 ===
UPLOAD_MEMORY_TO_AI = True


# 登录配置编辑器设置
ENABLE_LOGIN_PASSWORD = True
LOGIN_PASSWORD = 'yumiao0803'
PORT = 60803

# 定时器/提醒设置
# 启用提醒功能
ENABLE_REMINDERS = True
# 是否允许在安静时间内发送提醒 (True/False)
# 如果设置为 False，则在安静时间内安排的提醒将被跳过。
ALLOW_REMINDERS_IN_QUIET_TIME = True
# 是否使用语音通话进行提醒
USE_VOICE_CALL_FOR_REMINDERS = True

# 日程提醒功能配置
ENABLE_SCHEDULE_REMINDERS = True

# 默认日程提醒消息模板
DEFAULT_SCHEDULE_REMINDER_TEMPLATE = """📅 日程提醒

📋 {title}
⏰ 时间: {time_info}
{description}"""

# 联网API配置
ENABLE_ONLINE_API = False
ONLINE_BASE_URL = 'https://ai.dianhuomao.shop/v1'
ONLINE_MODEL = '【新原生联网自带思维链】gemini-3-pro-preview'
ONLINE_API_KEY = 'sk-hJq5jSxp4ywHX5q0goDfpQhGLMlV6MT7ClJ7qY7QJP6IXr3K'
ONLINE_API_TEMPERATURE = 0.7
ONLINE_API_MAX_TOKEN = 2000
SEARCH_DETECTION_PROMPT = '当用户提及真实的天气、地名、新闻时，启动联网搜索。'
ONLINE_FIXED_PROMPT = ''

# 是否启用自动抓取消息中URL链接内容的功能
ENABLE_URL_FETCHING = True
# 网络请求超时时间 (秒)
REQUESTS_TIMEOUT = 10
# 抓取网页时使用的 User-Agent，模拟浏览器防止被屏蔽
# REQUESTS_USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
# REQUESTS_USER_AGENT = 'Mozilla/5.0 (iPhone; CPU iPhone OS 15_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/15.0 Mobile/15E148 Safari/604.1'
REQUESTS_USER_AGENT = 'Mozilla/5.0 (Linux; Android 10; SM-G975F) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Mobile Safari/537.36'
# 从网页提取内容的最大字符数，防止上下文过长，影响AI处理效率和成本
MAX_WEB_CONTENT_LENGTH = 2000

# 定时重启配置
ENABLE_SCHEDULED_RESTART = False
RESTART_INTERVAL_HOURS = 2.0
RESTART_INACTIVITY_MINUTES = 15

# 强制移除括号当中的内容
REMOVE_PARENTHESES = False

# 是否使用辅助模型
ENABLE_ASSISTANT_MODEL = False
ASSISTANT_BASE_URL = 'http://api.wasdxx.xyz/v1'
ASSISTANT_MODEL = '[特价]claude-opus-4-6'
ASSISTANT_API_KEY = 'sk-tujpMKTbaMm3OLvDhP87Tp8q1xKyvH63BWyLrqqNvX3Her8r'
ASSISTANT_TEMPERATURE = 1.3
ASSISTANT_MAX_TOKEN = 64000
USE_ASSISTANT_FOR_MEMORY_SUMMARY = True

# 敏感词处理配置
# 开启后遇到敏感词时自动清除Memory_Temp文件和聊天上下文
ENABLE_SENSITIVE_CONTENT_CLEARING = False

# === 记忆检索管道配置 ===
# 检索模式: 'llm' (LLM精筛) / 'keyword' (关键词匹配) / 'off' (关闭)
MEMORY_RETRIEVAL_MODE = 'off'

# LLM 精筛中转站列表（按顺序故障转移，第一个成功就用）
# 每项: name(名称), base_url, api_key, model, timeout(秒)
MEMORY_LLM_PROVIDERS = [
    {
        'name': '默认中转站',
        'base_url': 'http://api.wasdxx.xyz/v1',
        'api_key': 'sk-tujpMKTbaMm3OLvDhP87Tp8q1xKyvH63BWyLrqqNvX3Her8r',
        'model': '[特价]claude-opus-4-6',
        'timeout': 60,
        'temperature': 0.3,
    },
]

# LLM 精筛返回的记忆条数（仅关键词降级时使用，LLM 模式不限制）
MEMORY_RETRIEVAL_TOP_K = 5

# LLM 精筛最大输出 token（需要足够大以容纳所有相关记忆的 JSON）
MEMORY_RETRIEVAL_MAX_TOKENS = 4000

# LLM 全部失败时是否降级到关键词匹配
MEMORY_FALLBACK_TO_KEYWORD = True

# LLM 精筛提示词文件路径（相对于项目根目录），前端可编辑
# 文件不存在时使用内置默认提示词
MEMORY_RETRIEVAL_PROMPT_FILE = 'prompts/memory_retrieval.md'



# 自动补充的配置项
IGNORE_GROUP_CHAT_FOR_AUTO_MESSAGE = False
ENABLE_GROUP_AT_REPLY_IN_REPLIES = False

# === 短期记忆系统配置 ===
# 启用短期记忆（每日自动生成 + 滑动窗口 + 自动沉淀）
ENABLE_SHORT_TERM_MEMORY = True
# 每天定时生成短期记忆的时间（24小时制，如 "02:00"）
SHORT_TERM_MEMORY_TIME = '02:00'
# 保留最近 N 天的短期记忆注入 prompt
SHORT_TERM_MEMORY_DAYS = 3
# 短期记忆存储子目录（在 Memory_Daily/{user_key}/ 下）
SHORT_TERM_MEMORY_DIR = 'short_term'
# 短期记忆生成/沉淀使用的 API 配置（复用记忆检索管道的中转站）
# 如果为空列表则使用 MEMORY_LLM_PROVIDERS
SHORT_TERM_LLM_PROVIDERS = []
# 生成短期记忆时是否注入人设+预设（推荐开启，让 AI 以角色视角判断）
SHORT_TERM_INJECT_PERSONA = True
# 短期记忆生成提示词文件
SHORT_TERM_GENERATE_PROMPT_FILE = 'prompts/short_term_generate.md'
# 短期记忆沉淀判断提示词文件
SHORT_TERM_SETTLE_PROMPT_FILE = 'prompts/short_term_settle.md'

# === TTS 语音合成配置 ===
# 引擎选择: "minimax"（克隆声音）| "edge"（免费微软音色）
TTS_ENGINE = 'minimax'

# --- MiniMax 配置 ---
TTS_MINIMAX_API_KEY = 'sk-api-3tSxXYsPDn0nOHEtvZSgLSKPiPGuyR39ntu-7LtfwXlet3-LCvnUN7SiA-FUFEXaCp7pXq00NTst0X0p42aOukELFA-r_AtEJcL-C30UCmPcbqISrPAQYXs'
TTS_MINIMAX_GROUP_ID = '1977563833656418958'
TTS_MINIMAX_VOICE_ID = 'yuanlangYL'        # 克隆的声音 ID
TTS_MINIMAX_MODEL = 'speech-2.8-hd'         # 模型: speech-2.8-hd / speech-2.8-turbo / speech-2.6-hd / speech-02-hd
TTS_MINIMAX_SPEED = 1.0                    # 语速 0.5~2.0
TTS_MINIMAX_VOL = 1.0                      # 音量 0.1~10.0
TTS_MINIMAX_PITCH = 0                      # 音调 -12~12
TTS_MINIMAX_API_URL = 'https://api.minimax.chat'  # 国内用 minimax.chat，海外用 minimaxi.com

# --- Edge TTS 配置（备用/免费方案）---
TTS_EDGE_VOICE = 'zh-CN-YunxiNeural'      # edge-tts 默认音色（云希 - 年轻男声）

# === 语音通话配置 ===
# 通话上下文是否接入微信聊天上下文（共享对话历史）
VOICE_SHARE_WECHAT_CONTEXT = False
# 通话时是否启用世界书
VOICE_ENABLE_WORLD_INFO = False
# 通话时是否启用检索记忆（LLM 精筛）
VOICE_ENABLE_MEMORY_RETRIEVAL = True
# 通话记录保存目录
VOICE_CALL_LOG_DIR = 'Voice_Logs'

# === 语音通话独立 API（留空则使用主聊天 API）===
# 可以设置单独的中转站/key，方便控制额度
VOICE_API_BASE_URL = ''
VOICE_API_KEY = ''
VOICE_API_MODEL = ''

# === 语音通话独立提示词（留空则使用主角色人设+预设）===
# 填写文件路径（相对于 yuan 项目根目录），如 'prompts/voice_prompt.md'
VOICE_CUSTOM_PROMPT_FILE = ''

# === Ngrok 隧道配置（手机 HTTPS 访问）===
# 启用后自动创建 ngrok 隧道，手机通过 HTTPS 域名访问可使用麦克风
ENABLE_NGROK = True
NGROK_AUTH_TOKEN = '3BB5w1uMKhEayzqOna4BUTorenT_7mgQT5PBoK5HBWacwrfv5'
