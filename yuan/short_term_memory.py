"""
短期记忆系统 - 每日自动生成 + 滑动窗口 + 自动沉淀

存储路径: Memory_Daily/{user_key}/short_term/YYYY-MM-DD.json
注入到 prompt 时渲染为 Markdown

流程:
1. 每天定时 → generate_short_term_memory() → 读对话日志生成当天短期记忆
2. 每次对话 → get_short_term_prompt() → 读最近 N 天记忆注入 prompt
3. 生成新一天时 → settle_expired_memory() → 对被挤出的第 N+1 天做沉淀判断
"""

import os
import json
import logging
import re
from datetime import datetime, timedelta

logger = logging.getLogger('bot')

# ======================================================================
# 存储层
# ======================================================================

def _get_short_term_dir(user_key):
    """获取用户的短期记忆目录"""
    from config import MEMORY_DAILY_DIR, SHORT_TERM_MEMORY_DIR
    root_dir = os.path.dirname(os.path.abspath(__file__))
    d = os.path.join(root_dir, MEMORY_DAILY_DIR, user_key, SHORT_TERM_MEMORY_DIR)
    os.makedirs(d, exist_ok=True)
    return d


def _load_short_term(user_key, date_str):
    """加载某天的短期记忆，返回 dict 或 None"""
    d = _get_short_term_dir(user_key)
    fp = os.path.join(d, f'{date_str}.json')
    if not os.path.exists(fp):
        return None
    try:
        with open(fp, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"加载短期记忆失败 {fp}: {e}")
        return None


def _save_short_term(user_key, date_str, data):
    """保存某天的短期记忆"""
    d = _get_short_term_dir(user_key)
    fp = os.path.join(d, f'{date_str}.json')
    try:
        with open(fp, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"短期记忆已保存: {fp}")
        return True
    except Exception as e:
        logger.error(f"保存短期记忆失败 {fp}: {e}")
        return False


def list_short_term_dates(user_key):
    """列出用户所有短期记忆日期（倒序）"""
    d = _get_short_term_dir(user_key)
    dates = []
    for f in os.listdir(d):
        if f.endswith('.json'):
            dates.append(f[:-5])
    dates.sort(reverse=True)
    return dates


# ======================================================================
# API 调用层（复用记忆检索管道的中转站配置）
# ======================================================================

def _call_llm(system_prompt, user_prompt):
    """调用 LLM，复用记忆检索管道的中转站"""
    from config import SHORT_TERM_LLM_PROVIDERS, MEMORY_LLM_PROVIDERS
    import openai
    
    providers = SHORT_TERM_LLM_PROVIDERS or MEMORY_LLM_PROVIDERS
    if not providers:
        logger.error("短期记忆: 没有配置 LLM 中转站")
        return None
    
    for p in providers:
        try:
            client = openai.OpenAI(
                base_url=p.get('base_url', ''),
                api_key=p.get('api_key', ''),
                timeout=p.get('timeout', 30)
            )
            response = client.chat.completions.create(
                model=p.get('model', 'gpt-4o-mini'),
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt}
                ],
                temperature=p.get('temperature', 0.5),
                max_tokens=4000
            )
            content = response.choices[0].message.content
            if content:
                return content.strip()
        except Exception as e:
            logger.warning(f"短期记忆 LLM 调用失败 ({p.get('name', '?')}): {e}")
            continue
    
    logger.error("短期记忆: 所有 LLM 中转站都失败了")
    return None


# ======================================================================
# 生成短期记忆
# ======================================================================

def _load_prompt_file(filepath, fallback=""):
    """加载提示词文件"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    fp = os.path.join(root_dir, filepath)
    if os.path.exists(fp):
        with open(fp, 'r', encoding='utf-8') as f:
            return f.read()
    return fallback


def _load_persona(user_id):
    """加载人设+预设内容"""
    from config import LISTEN_LIST
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 获取映射
    prompt_name = None
    preset_name = ''
    for entry in LISTEN_LIST:
        if entry[0] == user_id:
            prompt_name = entry[1]
            if len(entry) >= 4:
                preset_name = entry[3]
            break
    if not prompt_name:
        prompt_name = user_id
    
    # 加载人设
    persona = ""
    for p in [
        os.path.join(root_dir, 'prompts', 'characters', f'{prompt_name}.md'),
        os.path.join(root_dir, 'prompts', f'{prompt_name}.md'),
    ]:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                persona = f.read()
            break
    
    # 加载预设
    preset = ""
    search = []
    if preset_name:
        search.append(os.path.join(root_dir, 'prompts', 'presets', f'{preset_name}.md'))
        search.append(os.path.join(root_dir, 'prompts', f'{preset_name}.md'))
    search.append(os.path.join(root_dir, 'prompts', 'presets', 'preset.md'))
    search.append(os.path.join(root_dir, 'prompts', 'preset.md'))
    for p in search:
        if os.path.exists(p):
            with open(p, 'r', encoding='utf-8') as f:
                preset = f.read()
            break
    
    return persona, preset, prompt_name


def _get_role_and_key(user_id):
    """获取用户的角色名和 memory_key，不直接 import bot 避免循环依赖"""
    from config import LISTEN_LIST
    role_name = user_id
    for entry in LISTEN_LIST:
        if entry[0] == user_id:
            role_name = entry[1]
            break
    user_key = f"{user_id}_{role_name}"
    return role_name, user_key


def generate_short_term_memory(user_id, target_date=None):
    """
    生成指定日期的短期记忆
    
    Args:
        user_id: 用户 ID
        target_date: 目标日期字符串 YYYY-MM-DD，默认今天
    
    Returns:
        bool: 是否成功
    """
    from config import (ENABLE_SHORT_TERM_MEMORY, SHORT_TERM_INJECT_PERSONA,
                        SHORT_TERM_GENERATE_PROMPT_FILE, MEMORY_TEMP_DIR)
    
    if not ENABLE_SHORT_TERM_MEMORY:
        return False
    
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    if target_date is None:
        target_date = datetime.now().strftime('%Y-%m-%d')
    
    # 获取 user_key（不 import bot，避免循环依赖）
    role_name, user_key = _get_role_and_key(user_id)
    
    # 检查是否已经生成过
    existing = _load_short_term(user_key, target_date)
    if existing and existing.get('status') in ('active', 'archived'):
        logger.info(f"短期记忆 {target_date} 已存在 (status={existing.get('status')}), 跳过")
        return True
    
    # 读取对话日志
    diary_log = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_diary_log.txt')
    main_log = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_{role_name}_log.txt')
    log_file = diary_log if os.path.exists(diary_log) else main_log
    
    if not os.path.exists(log_file):
        logger.info(f"用户 {user_id} 没有对话日志，跳过短期记忆生成")
        return False
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        logs = [line.strip() for line in f if line.strip()]
    
    if len(logs) < 3:
        logger.info(f"用户 {user_id} 对话内容太少（{len(logs)}条），跳过")
        return False
    
    # 构建提示词
    prompt_template = _load_prompt_file(
        SHORT_TERM_GENERATE_PROMPT_FILE,
        "请总结今天的对话，生成短期记忆。先写300字总结，再列出事件。"
    )
    prompt_text = prompt_template.replace('{role_name}', role_name).replace('{user_id}', user_id)
    
    # 系统提示词（可选注入人设）
    system_parts = []
    if SHORT_TERM_INJECT_PERSONA:
        persona, preset, _ = _load_persona(user_id)
        if persona:
            system_parts.append(persona)
        if preset:
            system_parts.append(preset)
    system_parts.append(prompt_text)
    system_prompt = '\n\n'.join(system_parts)
    
    # 用户消息 = 对话日志
    full_logs = '\n'.join(logs)
    user_prompt = f"以下是今天（{target_date}）的对话记录：\n\n{full_logs}"
    
    # 调用 LLM
    logger.info(f"开始生成短期记忆: user={user_id}, date={target_date}, logs={len(logs)}条")
    result = _call_llm(system_prompt, user_prompt)
    
    if not result:
        logger.error(f"短期记忆生成失败: user={user_id}")
        return False
    
    # 解析结果
    summary, events = _parse_generated_content(result)
    
    # 保存
    data = {
        "date": target_date,
        "summary": summary,
        "events": events,
        "raw": result,
        "status": "active",
        "promoted": [],
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    success = _save_short_term(user_key, target_date, data)
    if success:
        logger.info(f"短期记忆生成成功: {target_date}, 总结{len(summary)}字, {len(events)}条事件")
    
    return success


def _parse_generated_content(text):
    """解析 LLM 生成的短期记忆内容"""
    summary = ""
    events = []
    
    # 分割总结和事件
    parts = re.split(r'##\s*今日事件', text, maxsplit=1)
    
    if len(parts) >= 2:
        # 提取总结
        summary_part = parts[0]
        summary_match = re.search(r'##\s*今日总结\s*\n(.*)', summary_part, re.DOTALL)
        if summary_match:
            summary = summary_match.group(1).strip()
        else:
            summary = summary_part.strip()
        
        # 提取事件列表
        events_text = parts[1].strip()
        for line in events_text.split('\n'):
            line = line.strip()
            # 匹配 "1. xxx" 或 "- xxx" 格式
            m = re.match(r'^\d+[\.\、]\s*(.+)$', line)
            if m:
                events.append(m.group(1).strip())
            elif line.startswith('- '):
                events.append(line[2:].strip())
    else:
        # 没有明确分段，整个当总结
        summary = text.strip()
    
    return summary, events


# ======================================================================
# 注入 prompt
# ======================================================================

def get_short_term_prompt(user_id):
    """
    获取最近 N 天的短期记忆，渲染为 Markdown 注入 prompt
    
    Returns:
        str: Markdown 格式的短期记忆文本，为空则返回 ""
    """
    from config import ENABLE_SHORT_TERM_MEMORY, SHORT_TERM_MEMORY_DAYS
    
    if not ENABLE_SHORT_TERM_MEMORY:
        return ""
    
    role_name, user_key = _get_role_and_key(user_id)
    
    days = SHORT_TERM_MEMORY_DAYS
    today = datetime.now()
    
    sections = []
    for i in range(days):
        date = (today - timedelta(days=i)).strftime('%Y-%m-%d')
        data = _load_short_term(user_key, date)
        if not data or data.get('status') not in ('active',):
            continue
        
        summary = data.get('summary', '')
        events = data.get('events', [])
        
        if not summary and not events:
            continue
        
        day_label = '今天' if i == 0 else f'{i}天前' if i <= 2 else date
        section = f"### {day_label}（{date}）\n"
        if summary:
            section += f"{summary}\n\n"
        if events:
            section += "事件：\n"
            for j, event in enumerate(events, 1):
                section += f"{j}. {event}\n"
        
        sections.append(section)
    
    if not sections:
        return ""
    
    return "## 最近的短期记忆\n\n以下是最近几天发生的事，你可以自然地引用。\n\n" + "\n".join(sections)


# ======================================================================
# 沉淀：滚出窗口的记忆自动判断升级/丢弃
# ======================================================================

def settle_expired_memory(user_id):
    """
    检查并沉淀过期的短期记忆（超出窗口天数的 active 记忆）
    
    Returns:
        bool: 是否有记忆被沉淀
    """
    from config import (ENABLE_SHORT_TERM_MEMORY, SHORT_TERM_MEMORY_DAYS,
                        SHORT_TERM_SETTLE_PROMPT_FILE, MEMORY_CORE_DIR)
    
    if not ENABLE_SHORT_TERM_MEMORY:
        return False
    
    role_name, user_key = _get_role_and_key(user_id)
    
    days = SHORT_TERM_MEMORY_DAYS
    today = datetime.now()
    cutoff = (today - timedelta(days=days)).strftime('%Y-%m-%d')
    
    # 找到所有过期但还是 active 的记忆
    all_dates = list_short_term_dates(user_key)
    expired = [d for d in all_dates if d < cutoff]
    expired_active = []
    for d in expired:
        data = _load_short_term(user_key, d)
        if data and data.get('status') == 'active':
            expired_active.append((d, data))
    
    if not expired_active:
        return False
    
    logger.info(f"发现 {len(expired_active)} 天过期短期记忆需要沉淀")
    
    root_dir = os.path.dirname(os.path.abspath(__file__))
    
    # 读取核心记忆
    core_memory = ""
    unified_file = os.path.join(root_dir, MEMORY_CORE_DIR, f'{user_key}_unified_memory.json')
    if os.path.exists(unified_file):
        try:
            with open(unified_file, 'r', encoding='utf-8') as f:
                core_data = json.load(f)
            core_memory = core_data.get('content', '')
        except Exception:
            pass
    
    settled_any = False
    
    for date_str, data in expired_active:
        try:
            success = _settle_one_day(user_id, user_key, role_name, date_str, data, core_memory)
            if success:
                settled_any = True
        except Exception as e:
            logger.error(f"沉淀 {date_str} 失败: {e}", exc_info=True)
            # 标记为 archived 避免反复重试
            data['status'] = 'archived'
            data['settle_error'] = str(e)
            _save_short_term(user_key, date_str, data)
    
    return settled_any


def _settle_one_day(user_id, user_key, role_name, date_str, data, core_memory):
    """沉淀单天的短期记忆"""
    from config import SHORT_TERM_SETTLE_PROMPT_FILE
    
    # 构建待判断内容
    content_parts = []
    if data.get('summary'):
        content_parts.append(f"## 总结\n{data['summary']}")
    if data.get('events'):
        content_parts.append("## 事件")
        for i, e in enumerate(data['events'], 1):
            content_parts.append(f"{i}. {e}")
    short_term_content = '\n'.join(content_parts)
    
    if not short_term_content.strip():
        data['status'] = 'discarded'
        data['settle_reason'] = '内容为空'
        _save_short_term(user_key, date_str, data)
        return True
    
    # 加载沉淀提示词
    prompt_template = _load_prompt_file(
        SHORT_TERM_SETTLE_PROMPT_FILE,
        "判断以下记忆是否值得保留。"
    )
    system_prompt = prompt_template.replace('{role_name}', role_name) \
        .replace('{user_id}', user_id) \
        .replace('{target_date}', date_str) \
        .replace('{core_memory}', core_memory or '（暂无核心记忆）') \
        .replace('{short_term_content}', short_term_content)
    
    user_prompt = "请根据以上内容做出判断。"
    
    logger.info(f"开始沉淀判断: {date_str}")
    result = _call_llm(system_prompt, user_prompt)
    
    if not result:
        logger.error(f"沉淀 LLM 调用失败: {date_str}")
        return False
    
    # 解析沉淀结果
    promoted_entries = _parse_settle_entries(result, date_str)
    core_update = _parse_settle_core_update(result)
    
    # 写入碎片记忆
    if promoted_entries:
        _promote_to_entries(promoted_entries)
        data['promoted'] = [e.get('id', 0) for e in promoted_entries]
        logger.info(f"沉淀 {date_str}: 升级 {len(promoted_entries)} 条碎片记忆")
    
    # 更新核心记忆
    if core_update:
        _update_core_memory(user_key, core_update)
        logger.info(f"沉淀 {date_str}: 核心记忆已更新")
    
    # 标记已处理
    data['status'] = 'archived'
    data['settle_result'] = result
    _save_short_term(user_key, date_str, data)
    
    return True


def _parse_settle_entries(text, date_str):
    """从沉淀结果中解析要升级的碎片记忆"""
    entries = []
    
    # 找到"升级为碎片记忆"部分
    section = re.search(r'##\s*升级为碎片记忆\s*\n(.*?)(?=##|$)', text, re.DOTALL)
    if not section:
        return entries
    
    content = section.group(1).strip()
    if content == '无' or not content:
        return entries
    
    # 解析每个事件块
    event_blocks = re.split(r'###\s*事件\s*\d+', content)
    for block in event_blocks:
        block = block.strip()
        if not block:
            continue
        
        event_match = re.search(r'-\s*event:\s*(.+)', block)
        summary_match = re.search(r'-\s*summary:\s*(.+)', block)
        content_match = re.search(r'-\s*content:\s*(.+)', block)
        
        if summary_match:
            entry = {
                'date': date_str,
                'event': event_match.group(1).strip() if event_match else '',
                'summary': summary_match.group(1).strip(),
                'content': content_match.group(1).strip() if content_match else '',
            }
            entries.append(entry)
    
    return entries


def _parse_settle_core_update(text):
    """从沉淀结果中解析核心记忆更新内容"""
    section = re.search(r'##\s*核心记忆更新\s*\n(.*?)(?=##|$)', text, re.DOTALL)
    if not section:
        return None
    content = section.group(1).strip()
    if content == '无' or not content:
        return None
    return content


def _promote_to_entries(new_entries):
    """将新条目写入 memory_entries.json"""
    root_dir = os.path.dirname(os.path.abspath(__file__))
    entries_path = os.path.join(root_dir, 'memory_entries.json')
    
    try:
        if os.path.exists(entries_path):
            with open(entries_path, 'r', encoding='utf-8') as f:
                entries = json.load(f)
        else:
            entries = []
        
        # 获取最大 id
        max_id = max((e.get('id', 0) for e in entries), default=0)
        
        for entry in new_entries:
            max_id += 1
            entry['id'] = max_id
            entries.append(entry)
        
        with open(entries_path, 'w', encoding='utf-8') as f:
            json.dump(entries, f, ensure_ascii=False, indent=2)
        
        logger.info(f"已写入 {len(new_entries)} 条新碎片记忆, max_id={max_id}")
    except Exception as e:
        logger.error(f"写入 memory_entries.json 失败: {e}")


def _update_core_memory(user_key, update_text):
    """追加核心记忆更新"""
    from config import MEMORY_CORE_DIR
    root_dir = os.path.dirname(os.path.abspath(__file__))
    unified_file = os.path.join(root_dir, MEMORY_CORE_DIR, f'{user_key}_unified_memory.json')
    
    try:
        if os.path.exists(unified_file):
            with open(unified_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
        else:
            data = {}
        
        old_content = data.get('content', '')
        data['content'] = old_content + '\n\n' + update_text if old_content else update_text
        data['timestamp'] = datetime.now().strftime('%Y-%m-%d %A %H:%M:%S')
        data['trigger'] = '短期记忆自动沉淀'
        
        with open(unified_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.info(f"核心记忆已更新: {unified_file}")
    except Exception as e:
        logger.error(f"更新核心记忆失败: {e}")


# ======================================================================
# 定时任务入口
# ======================================================================

def daily_short_term_task(user_id):
    """
    每日定时任务：生成今天的短期记忆 + 沉淀过期记忆
    """
    logger.info(f"=== 开始每日短期记忆任务: user={user_id} ===")
    
    # 1. 生成昨天的短期记忆（因为定时通常在凌晨，总结的是前一天的对话）
    yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
    gen_ok = generate_short_term_memory(user_id, target_date=yesterday)
    
    # 2. 沉淀过期记忆
    settle_ok = settle_expired_memory(user_id)
    
    logger.info(f"=== 每日短期记忆任务完成: gen={gen_ok}, settle={settle_ok} ===")
    return gen_ok or settle_ok
