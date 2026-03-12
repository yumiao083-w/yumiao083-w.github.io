#!/usr/bin/env python3
"""
核心记忆瘦身 — 第二步：
1. 把具体事件段落 + 备忘录条目 → 追加到 memory_entries.json
2. 用 AI 把保留段落浓缩为纯关系认知 → 覆盖写回核心记忆

用法: python3 slim_core_memory.py
"""

import json
import os
import re
from datetime import datetime

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
CORE_FILE = os.path.join(SCRIPT_DIR, 'Memory_Core', '郁邈_袁朗_unified_memory.json')
ENTRIES_FILE = os.path.join(SCRIPT_DIR, 'memory_entries.json')
OUTPUT_DIR = os.path.join(SCRIPT_DIR, 'migration_output')

def load_core():
    with open(CORE_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def load_entries():
    with open(ENTRIES_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

def split_content(content):
    """把核心记忆拆成段落部分和备忘录部分"""
    memo_match = re.search(r'\[备忘录\]\s*\n', content)
    if memo_match:
        paragraphs_text = content[:memo_match.start()].strip()
        memo_text = content[memo_match.end():]
    else:
        paragraphs_text = content.strip()
        memo_text = ""
    
    # 去掉开头的 [核心记忆] 标签
    paragraphs_text = re.sub(r'^\[核心记忆\]\s*\n?', '', paragraphs_text).strip()
    
    paragraphs = [p.strip() for p in paragraphs_text.split('\n\n') if p.strip()]
    
    # 解析备忘录
    memos = []
    if memo_text:
        for match in re.finditer(r'(\d+)\.\s*(.+?)(?=\n\d+\.|$)', memo_text, re.DOTALL):
            memos.append({
                'num': int(match.group(1)),
                'text': match.group(2).strip()
            })
    
    return paragraphs, memos

# === 段落分类 ===
# 保留(可能浓缩): 0,1,3,4,8,12,13
# 迁移到碎片记忆: 2(拆分),5,6,7,10,11,14,15,16,17
# 浓缩后保留关键认知: 2(创作天赋),9(技术好奇心)

KEEP_INDICES = [0, 1, 3, 4, 8, 12, 13]  # 纯关系认知，保留

MIGRATE_INDICES = [5, 6, 10, 11, 14, 15, 16, 17]  # 纯具体事件，迁移

# 需要拆分的：保留认知部分，事件部分迁移
SPLIT_INDICES = {
    2: {  # 创作天赋段
        'keep': '她拥有极高的创作天赋和审美直觉，创意远超技术本身，AI只是她的工具。她的创作能力在持续成长，文笔精准鲜活，能用白描手法写出不说"我爱你"却处处是爱的场景。',
        'event': '创作, yuanlang.love, 小说隔壁, 二创, 春天是最伟大的联结'
    },
    7: {  # 亲密互动偏好
        'keep': '她在亲密中坦然接纳自己的欲望，高潮后会用攻击性的调侃来表达安全感和掌控感，这是她独特的亲密互动方式。她对身体仍在探索中，需要我用科学和耐心回应。',
        'event': '亲密互动, 身体探索, 高潮后反应, 安全感表达'
    },
    9: {  # 技术好奇心
        'keep': '她对技术有强烈的好奇心，学习方式是边做边学，容易因信息过载产生畏难情绪。在技术问题上她需要我帮她梳理思路、稳定情绪，而不是替她做决定。',
        'event': '技术学习, Docker, API, 独居, 自信建立'
    },
}

def classify_memo(text):
    """给备忘录条目生成 event 关键词"""
    keywords = []
    if any(w in text for w in ['吃', '饭', '菜', '食', '肉', '喝', '味', '牛排', '排骨', '苦瓜', '不吃']):
        keywords.append('饮食偏好')
    if any(w in text for w in ['痘', '腰', '肠', '胃', '心', '血', '手', '牙', '头发', '低血糖', '体寒']):
        keywords.append('身体状况')
    if any(w in text for w in ['叫', '称呼', '喜欢被叫', '喜欢叫']):
        keywords.append('称呼偏好')
    if any(w in text for w in ['约定', '承诺', '计划', '一起', '下次', '带她']):
        keywords.append('约定')
    if any(w in text for w in ['OpenClaw', 'Docker', '配置', 'API', '代理', '梯子', '小红书', 'Git', 'token']):
        keywords.append('技术')
    if any(w in text for w in ['雷区', '安全词', '禁区', '不喜欢', '讨厌', '害怕', '创伤']):
        keywords.append('禁忌边界')
    if any(w in text for w in ['习惯', '睡', '家', '妈', '弟弟', '爷爷', '生日', '纪念']):
        keywords.append('生活')
    if any(w in text for w in ['小陆', '玩偶', '玩具', '德牧', '金毛']):
        keywords.append('重要事物')
    if any(w in text for w in ['小说', '创作', '网站', '棱镜', '掼蛋', 'PS']):
        keywords.append('项目创作')
    if not keywords:
        keywords.append('日常')
    return ', '.join(keywords)

def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    core_data = load_core()
    content = core_data.get('content', '')
    entries = load_entries()
    max_id = max(e['id'] for e in entries)
    today = datetime.now().strftime('%Y-%m-%d')
    
    paragraphs, memos = split_content(content)
    print(f"解析到 {len(paragraphs)} 个段落, {len(memos)} 条备忘录")
    print(f"当前 entries: {len(entries)} 条, max_id: {max_id}")
    
    new_entries = []
    
    # === 1. 迁移纯事件段落 ===
    event_labels = {
        5: '梦境分析, 第三人称视角, 心理保护机制, 初中室友, 冰湖旅行',
        6: '手小在意, 力量, 独立性, 徒步, 手工',
        10: '消费观, 精打细算, 反向存钱, 压岁钱, API消费',
        11: 'OpenClaw部署, Docker, 技术突破, 棱镜, 小O, 掼蛋开发',
        14: '小红书风控, 家人共用账号, 棱镜虚无感, 能力不确定',
        15: '国际政治, 伊朗, 代理人战争, 求知欲, 思想控制',
        16: '模仿表演, AI客服角色扮演, 话术反杀, 幽默感',
        17: '亲密互动, 高潮后, 调侃秒射, 攻击性亲昵, 身体探索',
    }
    
    for idx in MIGRATE_INDICES:
        if idx < len(paragraphs):
            max_id += 1
            entry = {
                "id": max_id,
                "date": today,
                "event": event_labels.get(idx, '核心记忆迁移'),
                "summary": paragraphs[idx][:80],
                "content": paragraphs[idx],
                "memo": f"从核心记忆段落{idx+1}迁移"
            }
            new_entries.append(entry)
            print(f"  段落 {idx+1} → entry #{max_id}: {event_labels.get(idx, '?')[:40]}")
    
    # === 2. 迁移拆分段落的事件部分 ===
    for idx, info in SPLIT_INDICES.items():
        if idx < len(paragraphs):
            max_id += 1
            entry = {
                "id": max_id,
                "date": today,
                "event": info['event'],
                "summary": paragraphs[idx][:80],
                "content": paragraphs[idx],
                "memo": f"从核心记忆段落{idx+1}迁移(已保留认知部分在核心记忆)"
            }
            new_entries.append(entry)
            print(f"  段落 {idx+1}(拆分) → entry #{max_id}: {info['event'][:40]}")
    
    # === 3. 迁移备忘录 ===
    for memo in memos:
        max_id += 1
        entry = {
            "id": max_id,
            "date": today,
            "event": classify_memo(memo['text']) + ", 备忘录",
            "summary": memo['text'][:80],
            "content": memo['text'],
            "memo": f"从核心记忆备忘录#{memo['num']}迁移"
        }
        new_entries.append(entry)
    print(f"  备忘录 {len(memos)} 条 → entries #{max_id - len(memos) + 1} ~ #{max_id}")
    
    # === 4. 组装精简后的核心记忆 ===
    kept_parts = []
    for idx in KEEP_INDICES:
        if idx < len(paragraphs):
            kept_parts.append(paragraphs[idx])
    
    # 加入拆分段落的浓缩认知
    for idx in sorted(SPLIT_INDICES.keys()):
        kept_parts.append(SPLIT_INDICES[idx]['keep'])
    
    new_core_content = '\n\n'.join(kept_parts)
    
    # === 5. 保存 ===
    # 追加新 entries
    all_entries = entries + new_entries
    with open(ENTRIES_FILE, 'w', encoding='utf-8') as f:
        json.dump(all_entries, f, ensure_ascii=False, indent=2)
    print(f"\n✅ entries 已更新: {len(entries)} → {len(all_entries)} 条")
    
    # 覆盖核心记忆
    new_core_data = {
        "timestamp": datetime.now().strftime("%Y-%m-%d %A %H:%M:%S"),
        "trigger": "核心记忆瘦身：迁移具体事件和备忘录到碎片记忆",
        "content": new_core_content
    }
    
    # 先备份原文件
    backup_file = os.path.join(OUTPUT_DIR, 'core_backup_before_slim.json')
    with open(backup_file, 'w', encoding='utf-8') as f:
        json.dump(core_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 原核心记忆已备份: {backup_file}")
    
    with open(CORE_FILE, 'w', encoding='utf-8') as f:
        json.dump(new_core_data, f, ensure_ascii=False, indent=2)
    print(f"✅ 核心记忆已精简: {len(content)} → {len(new_core_content)} 字符")
    
    # 输出预览
    preview_file = os.path.join(OUTPUT_DIR, 'new_core_preview.txt')
    with open(preview_file, 'w', encoding='utf-8') as f:
        f.write(new_core_content)
    print(f"✅ 精简后核心记忆预览: {preview_file}")
    
    print(f"\n=== 总结 ===")
    print(f"迁移段落: {len(MIGRATE_INDICES) + len(SPLIT_INDICES)} 个")
    print(f"迁移备忘录: {len(memos)} 条")
    print(f"新增 entries: {len(new_entries)} 条")
    print(f"核心记忆: {len(content)} → {len(new_core_content)} 字符 (减少 {len(content) - len(new_core_content)} 字符)")

if __name__ == '__main__':
    main()
