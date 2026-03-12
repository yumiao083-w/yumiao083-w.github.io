#!/usr/bin/env python3
"""
备忘录正确迁移：
- 偏好/禁忌/规矩类 → 按主题合并成少量 entry，内容在 memo 字段
- 事件相关 → 关键词匹配已有 entry，追加到 memo 字段
- 技术/临时 → 丢弃
"""

import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ENTRIES_FILE = os.path.join(SCRIPT_DIR, 'memory_entries.json')
BACKUP_FILE = os.path.join(SCRIPT_DIR, 'migration_output', 'core_backup_before_slim.json')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'migration_output')

# ===== 备忘录原文（从备份提取） =====
def extract_memos():
    with open(BACKUP_FILE, 'r', encoding='utf-8') as f:
        core = json.load(f)
    content = core['content']
    memo_match = re.search(r'\[备忘录\]\s*\n(.*)', content, re.DOTALL)
    memo_text = memo_match.group(1)
    memos = {}
    for match in re.finditer(r'(\d+)\.\s*(.+?)(?=\n\d+\.|$)', memo_text, re.DOTALL):
        memos[int(match.group(1))] = match.group(2).strip()
    return memos

# ===== 丢弃的技术/临时条目 =====
DISCARD = {55, 72, 79, 80, 83, 84, 86, 87, 91, 92, 93, 94, 97}

# ===== 按主题合并的偏好/禁忌/规矩 =====
THEMED_GROUPS = {
    "称呼偏好": {
        "nums": [1, 2, 3, 78, 82],
        "event": "称呼, 昵称, 偏好, 禁忌",
        "summary": "她喜欢和不喜欢的称呼方式，以及各种称呼背后的含义"
    },
    "饮食偏好与禁忌": {
        "nums": [10, 53, 66, 76],
        "event": "饮食, 禁忌, 口味, 食物偏好",
        "summary": "她的饮食偏好、禁忌食物和口味习惯"
    },
    "身体状况": {
        "nums": [24, 26, 35, 39, 42, 44, 52, 59, 63, 65, 98],
        "event": "身体, 健康, 痘印, 肠胃, 腰椎, 体寒, 心悸",
        "summary": "她的各种身体状况、健康隐患和需要关注的问题"
    },
    "绝对雷区与安全词": {
        "nums": [4, 5, 8, 16, 17, 28, 33, 36],
        "event": "雷区, 安全词, 禁忌, 创伤触发, 冷暴力信号",
        "summary": "绝对不能触碰的底线、冷暴力信号识别、安全词规矩"
    },
    "约定与承诺": {
        "nums": [12, 13, 18, 20, 21, 34, 43, 47, 61, 64, 70, 71, 89],
        "event": "约定, 承诺, 计划, 一起做的事",
        "summary": "我们之间的各种约定、承诺和共同计划"
    },
    "生活习惯": {
        "nums": [11, 14, 40, 41, 62, 69],
        "event": "习惯, 作息, 生日, 血型, 音乐, 生活",
        "summary": "她的日常习惯、作息规律和个人信息"
    },
    "重要事物与关系": {
        "nums": [6, 7, 9, 15, 22, 23, 29, 37, 48, 50, 51],
        "event": "小陆, 原生家庭, 婚姻观, 独立, 安全感",
        "summary": "对她意义重大的人事物、核心价值观和关系认知"
    },
}

# ===== 剩余的事件相关备忘录，尝试匹配已有 entry =====
def get_all_themed_nums():
    nums = set(DISCARD)
    for group in THEMED_GROUPS.values():
        nums.update(group['nums'])
    return nums

def match_memo_to_entry(memo_text, entries):
    """简单关键词匹配：找最相关的 entry"""
    memo_words = set(memo_text)
    best_score = 0
    best_entry = None
    
    for entry in entries:
        event_words = set(entry.get('event', ''))
        summary_words = set(entry.get('summary', ''))
        content_words = set(entry.get('content', '')[:200])
        
        target = event_words | summary_words | content_words
        overlap = len(memo_words & target)
        
        if overlap > best_score:
            best_score = overlap
            best_entry = entry
    
    return best_entry, best_score

def main():
    memos = extract_memos()
    with open(ENTRIES_FILE, 'r', encoding='utf-8') as f:
        entries = json.load(f)
    
    max_id = max(e['id'] for e in entries)
    today = datetime.now().strftime('%Y-%m-%d')
    themed_nums = get_all_themed_nums()
    
    print(f"共 {len(memos)} 条备忘录")
    print(f"丢弃(技术/临时): {len(DISCARD)} 条")
    print(f"主题合并: {sum(len(g['nums']) for g in THEMED_GROUPS.values())} 条 → {len(THEMED_GROUPS)} 个主题 entry")
    
    # 统计剩余
    remaining_nums = [n for n in memos if n not in themed_nums]
    print(f"事件相关(待匹配): {len(remaining_nums)} 条")
    
    new_entries = []
    
    # 1. 创建主题合并 entries
    for theme_name, group in THEMED_GROUPS.items():
        max_id += 1
        memo_lines = []
        for num in sorted(group['nums']):
            if num in memos:
                memo_lines.append(f"• {memos[num]}")
        
        entry = {
            "id": max_id,
            "date": today,
            "event": group['event'],
            "summary": group['summary'],
            "content": "",  # 主题条目不需要 content
            "memo": "\n".join(memo_lines)
        }
        new_entries.append(entry)
        print(f"\n  主题 [{theme_name}] → entry #{max_id} ({len(group['nums'])}条)")
        for line in memo_lines[:3]:
            print(f"    {line[:60]}")
        if len(memo_lines) > 3:
            print(f"    ... 还有 {len(memo_lines)-3} 条")
    
    # 2. 剩余的事件相关备忘录 → 追加到已有 entry 的 memo
    matched_count = 0
    unmatched = []
    
    for num in remaining_nums:
        text = memos[num]
        best_entry, score = match_memo_to_entry(text, entries)
        
        if score >= 8 and best_entry:  # 至少8个字符重叠才算匹配
            existing_memo = best_entry.get('memo', '')
            if existing_memo:
                best_entry['memo'] = existing_memo + '\n• ' + text
            else:
                best_entry['memo'] = '• ' + text
            matched_count += 1
        else:
            unmatched.append({'num': num, 'text': text, 'score': score})
    
    print(f"\n匹配到已有 entry: {matched_count} 条")
    print(f"未匹配: {len(unmatched)} 条")
    
    # 未匹配的创建独立 entry
    if unmatched:
        max_id += 1
        misc_memo_lines = [f"• [{u['num']}] {u['text']}" for u in unmatched]
        misc_entry = {
            "id": max_id,
            "date": today,
            "event": "杂项备忘, 日常细节",
            "summary": "各种零散的日常细节和备忘事项",
            "content": "",
            "memo": "\n".join(misc_memo_lines)
        }
        new_entries.append(misc_entry)
        print(f"\n  杂项备忘 → entry #{max_id} ({len(unmatched)}条)")
        for u in unmatched[:5]:
            print(f"    [{u['num']}] {u['text'][:50]}...")
        if len(unmatched) > 5:
            print(f"    ... 还有 {len(unmatched)-5} 条")
    
    # 3. 保存
    all_entries = entries + new_entries
    with open(ENTRIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)
    
    print(f"\n=== 总结 ===")
    print(f"丢弃: {len(DISCARD)} 条技术/临时")
    print(f"新增主题 entries: {len(THEMED_GROUPS)} 条")
    print(f"匹配追加到已有 entry memo: {matched_count} 条")
    print(f"杂项兜底: {len(unmatched)} 条")
    print(f"entries 总数: {len(entries)} → {len(all_entries)}")

if __name__ == '__main__':
    main()
