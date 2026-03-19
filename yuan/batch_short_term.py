"""
批量补生成短期记忆脚本

功能：
1. 读取 diary_log.txt，按日期分割
2. 对每一天的日志，如果超过 800 行则分段总结再合并
3. 调用 short_term_memory 的生成逻辑保存结果
"""

import os
import re
import sys
import json
import time
from datetime import datetime
from collections import defaultdict

# 添加项目目录到路径
root_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, root_dir)


def split_log_by_date(log_file):
    """按日期分割日志文件"""
    date_logs = defaultdict(list)
    
    with open(log_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            # 提取日期：2026-03-12 Thursday 02:21:34 | [郁邈] 老公
            match = re.match(r'^(\d{4}-\d{2}-\d{2})\s', line)
            if match:
                date_str = match.group(1)
                date_logs[date_str].append(line)
            else:
                # 没有日期前缀的行，归到最后一个日期
                if date_logs:
                    last_date = list(date_logs.keys())[-1]
                    date_logs[last_date].append(line)
    
    return dict(date_logs)


def _call_llm_long(system_prompt, user_prompt, timeout=120):
    """专用的 LLM 调用，超时时间更长"""
    from config import SHORT_TERM_LLM_PROVIDERS, MEMORY_LLM_PROVIDERS
    import openai
    
    providers = SHORT_TERM_LLM_PROVIDERS or MEMORY_LLM_PROVIDERS
    if not providers:
        print("    ❌ 没有配置 LLM 中转站")
        return None
    
    for p in providers:
        try:
            client = openai.OpenAI(
                base_url=p.get('base_url', ''),
                api_key=p.get('api_key', ''),
                timeout=timeout,
                default_headers={
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
                    "X-Stainless-Lang": "", "X-Stainless-Package-Version": "", "X-Stainless-OS": "", "X-Stainless-Arch": "", "X-Stainless-Runtime": "", "X-Stainless-Runtime-Version": "",
                }
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
            print(f"    ⚠ LLM 调用失败 ({p.get('name', '?')}): {e}")
            continue
    
    return None


def generate_for_date(user_id, date_str, log_lines):
    """为指定日期生成短期记忆"""
    from short_term_memory import (
        _get_role_and_key, _load_short_term, _save_short_term,
        _call_llm, _parse_generated_content, _load_prompt_file, _load_persona
    )
    from config import (ENABLE_SHORT_TERM_MEMORY, SHORT_TERM_INJECT_PERSONA,
                        SHORT_TERM_GENERATE_PROMPT_FILE)
    
    role_name, user_key = _get_role_and_key(user_id)
    
    # 检查是否已经生成过
    existing = _load_short_term(user_key, date_str)
    if existing and existing.get('status') in ('active', 'archived'):
        print(f"  ⏭ {date_str}: 已存在，跳过")
        return True
    
    if len(log_lines) < 3:
        print(f"  ⏭ {date_str}: 对话太少（{len(log_lines)}条），跳过")
        return True
    
    # 构建提示词
    prompt_template = _load_prompt_file(
        SHORT_TERM_GENERATE_PROMPT_FILE,
        "请总结今天的对话，生成短期记忆。先写300字总结，再列出事件。"
    )
    prompt_text = prompt_template.replace('{role_name}', role_name).replace('{user_id}', user_id)
    
    system_parts = []
    if SHORT_TERM_INJECT_PERSONA:
        persona, preset, _ = _load_persona(user_id)
        if persona:
            system_parts.append(persona)
        if preset:
            system_parts.append(preset)
    system_parts.append(prompt_text)
    system_prompt = '\n\n'.join(system_parts)
    
    # 日志太长时分段处理
    MAX_LINES_PER_CHUNK = 1000
    
    if len(log_lines) <= MAX_LINES_PER_CHUNK:
        # 直接总结
        full_logs = '\n'.join(log_lines)
        user_prompt = f"以下是{date_str}的对话记录：\n\n{full_logs}"
        print(f"  📝 {date_str}: {len(log_lines)} 行，直接总结...")
        result = _call_llm_long(system_prompt, user_prompt)
    else:
        # 分段总结再合并
        chunks = []
        for i in range(0, len(log_lines), MAX_LINES_PER_CHUNK):
            chunks.append(log_lines[i:i + MAX_LINES_PER_CHUNK])
        
        print(f"  📝 {date_str}: {len(log_lines)} 行，分 {len(chunks)} 段总结...")
        
        chunk_summaries = []
        for idx, chunk in enumerate(chunks):
            chunk_text = '\n'.join(chunk)
            chunk_prompt = (
                f"以下是{date_str}的对话记录（第{idx+1}/{len(chunks)}段）。"
                f"请总结这段对话的主要内容和事件，300字以内：\n\n{chunk_text}"
            )
            chunk_result = _call_llm_long(
                "你是一个对话总结助手。请简洁准确地总结对话内容。",
                chunk_prompt
            )
            if chunk_result:
                chunk_summaries.append(f"【第{idx+1}段】{chunk_result}")
                print(f"    ✅ 第{idx+1}段总结完成")
            else:
                print(f"    ❌ 第{idx+1}段总结失败")
            time.sleep(2)  # 避免 API 限速
        
        if not chunk_summaries:
            print(f"  ❌ {date_str}: 所有分段总结失败")
            return False
        
        # 合并总结
        merged = '\n\n'.join(chunk_summaries)
        merge_prompt = (
            f"以下是{date_str}对话的分段总结。请合并成一份完整的短期记忆，"
            f"包含：\n1. ## 今日总结（300字左右的整体概述）\n"
            f"2. ## 今日事件（列出所有重要事件）\n\n{merged}"
        )
        result = _call_llm_long(system_prompt, merge_prompt)
    
    if not result:
        print(f"  ❌ {date_str}: 生成失败")
        return False
    
    # 解析并保存
    summary, events = _parse_generated_content(result)
    
    data = {
        "date": date_str,
        "summary": summary,
        "events": events,
        "raw": result,
        "status": "active",
        "promoted": [],
        "generated_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    }
    
    success = _save_short_term(user_key, date_str, data)
    if success:
        print(f"  ✅ {date_str}: 总结{len(summary)}字, {len(events)}条事件")
    return success


def main():
    user_id = "郁邈"
    
    # 找日志文件
    from config import MEMORY_TEMP_DIR
    log_file = os.path.join(root_dir, MEMORY_TEMP_DIR, f'{user_id}_袁朗_diary_log.txt')
    
    if not os.path.exists(log_file):
        print(f"❌ 日志文件不存在: {log_file}")
        return
    
    # 按日期分割
    date_logs = split_log_by_date(log_file)
    dates = sorted(date_logs.keys())
    
    print(f"📊 日志文件: {log_file}")
    print(f"📅 共 {len(dates)} 天的记录:")
    for d in dates:
        print(f"   {d}: {len(date_logs[d])} 行")
    print()
    
    # 今天的日期不处理（还在聊天中）
    today = datetime.now().strftime('%Y-%m-%d')
    process_dates = [d for d in dates if d != today]
    
    if not process_dates:
        print("没有需要处理的日期")
        return
    
    print(f"🚀 开始处理 {len(process_dates)} 天的记录（跳过今天 {today}）\n")
    
    success_count = 0
    fail_count = 0
    
    for date_str in process_dates:
        lines = date_logs[date_str]
        try:
            ok = generate_for_date(user_id, date_str, lines)
            if ok:
                success_count += 1
            else:
                fail_count += 1
        except Exception as e:
            print(f"  ❌ {date_str}: 异常 - {e}")
            fail_count += 1
        
        time.sleep(3)  # 每天之间休息 3 秒
    
    print(f"\n🏁 完成！成功: {success_count}, 失败: {fail_count}")


if __name__ == '__main__':
    main()
