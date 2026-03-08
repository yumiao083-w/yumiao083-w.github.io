// ========== 掼蛋 AI API 模块 ==========

function GuandanAPIAI(apiConfig, game) {
    this.config = apiConfig;
    this.game = game;
}

// 构建每次出牌的 user prompt
GuandanAPIAI.prototype.buildUserPrompt = function(playerIdx) {
    var game = this.game;
    var hand = game.hands[playerIdx];
    var currentRank = game.currentRank;

    // 手牌转可读名
    var handNames = hand.map(function(id) { return cardIdToName(id, currentRank); });

    // 手牌按牌型分组分析，帮助AI理解手牌结构
    var pg = getPointGroups(hand, currentRank);
    var groups = pg.groups;
    var weights = Object.keys(groups).map(Number).sort(function(a,b){return a-b;});
    var handAnalysis = [];
    weights.forEach(function(w) {
        var cards = groups[w].map(function(id) { return cardIdToName(id, currentRank); });
        var label = cards.length >= 4 ? '炸弹' : cards.length === 3 ? '三条' : cards.length === 2 ? '对子' : '单张';
        handAnalysis.push(label + ': ' + cards.join('+'));
    });
    if (pg.wilds.length > 0) {
        handAnalysis.push('逢人配: ' + pg.wilds.map(function(id) { return cardIdToName(id, currentRank); }).join('+'));
    }

    var lines = [];
    lines.push('当前打: ' + RANK_NAMES[currentRank] + ' | 逢人配: 红桃' + RANK_NAMES[currentRank]);
    lines.push('你是: ' + game.playerNames[playerIdx] + ' | 队友: ' + game.playerNames[(playerIdx + 2) % 4]);
    lines.push('');

    // 各家剩余牌数
    lines.push('各家牌数:');
    for (var i = 0; i < 4; i++) {
        var rel = '';
        if (i === playerIdx) rel = '(你)';
        else if (i === (playerIdx + 2) % 4) rel = '(队友)';
        else rel = '(对手)';
        var finished = game.finishOrder.indexOf(i) !== -1;
        lines.push('  ' + game.playerNames[i] + rel + ': ' + (finished ? '已出完' : game.hands[i].length + '张'));
    }
    lines.push('');

    // 手牌
    lines.push('你的手牌(' + hand.length + '张): ' + handNames.join(', '));
    lines.push('牌型分析: ' + handAnalysis.join(' | '));
    lines.push('');

    // 出牌要求
    var mustPlay = (game.lastPlayedBy === -1 || game.lastPlayedBy === playerIdx);
    if (mustPlay) {
        lines.push('【首出】你必须出牌，action必须是play，自由选择牌型。');
    } else {
        var lastTypeName = TYPE_NAMES[game.lastPlayedType.type] || '未知';
        var lastCardNames = game.lastPlayedCards.map(function(id) { return cardIdToName(id, currentRank); });
        var isTeammate = game.teams[game.lastPlayedBy] === game.teams[playerIdx];
        lines.push('上家: ' + game.playerNames[game.lastPlayedBy] + (isTeammate ? '(队友)' : '(对手)') +
                   ' 出了' + lastTypeName + ': ' + lastCardNames.join(', '));
        lines.push('你可以出更大的同类型牌/炸弹压过，或pass不出。');
        if (isTeammate) {
            lines.push('（上家是队友，建议不压，选pass）');
        }
    }

    return lines.join('\n');
};

// 将 card id 转为可读名称
function cardIdToName(id, currentRank) {
    var info = getRawCardInfo(id);
    if (info.isBigJoker) return '大王';
    if (info.isJoker) return '小王';
    return SUIT_NAMES[info.suitIdx] + info.rank;
}

// 将 AI 返回的牌名转为 card id
function cardNameToIds(name, hand, currentRank) {
    // 处理 "大王" "小王"
    if (name === '大王') return hand.filter(function(id) { return getRawCardInfo(id).isBigJoker; });
    if (name === '小王') return hand.filter(function(id) { var info = getRawCardInfo(id); return info.isJoker && !info.isBigJoker; });

    // 解析 "花色+点数"，如 "红桃A" "方块10"
    var suitMap = { '方块': 0, '梅花': 1, '红桃': 2, '黑桃': 3 };
    var suit = -1, rank = '';
    for (var s in suitMap) {
        if (name.indexOf(s) === 0) {
            suit = suitMap[s];
            rank = name.substring(s.length);
            break;
        }
    }
    if (suit === -1 || !rank) return [];

    var rankIdx = RANK_NAMES.indexOf(rank);
    if (rankIdx === -1) return [];

    // 找手牌中匹配的 card id
    return hand.filter(function(id) {
        var info = getRawCardInfo(id);
        return !info.isJoker && info.suitIdx === suit && info.rankIdx === rankIdx;
    });
}

// 从 AI 响应文本中解析出 speech + action + cards
GuandanAPIAI.prototype.parseResponse = function(text, hand, currentRank) {
    var result = { speech: '', action: 'pass', cards: [] };

    // 按分隔符拆分
    var parts = text.split('===PLAY===');
    if (parts.length >= 2) {
        result.speech = parts[0].trim();
        var jsonPart = parts[1].trim();
        var parsed = this._extractJSON(jsonPart);
        if (parsed) {
            result.action = parsed.action || 'pass';
            if (parsed.cards && Array.isArray(parsed.cards)) {
                result.cards = this._resolveCards(parsed.cards, hand, currentRank);
            }
        }
    } else {
        // 没有分隔符，尝试从整段文本中提取 JSON
        var jsonMatch = this._extractJSON(text);
        if (jsonMatch) {
            result.action = jsonMatch.action || 'pass';
            if (jsonMatch.cards && Array.isArray(jsonMatch.cards)) {
                result.cards = this._resolveCards(jsonMatch.cards, hand, currentRank);
            }
            // 把 JSON 之前的文字当作 speech
            var jsonStart = text.indexOf('{');
            if (jsonStart > 0) {
                result.speech = text.substring(0, jsonStart).trim();
            }
        } else {
            // 完全解析失败，把整段文字当 speech，降级 pass
            result.speech = text.trim();
        }
    }

    return result;
};

// 从文本中提取第一个 JSON 对象
GuandanAPIAI.prototype._extractJSON = function(text) {
    // 找第一个 { 和最后一个 } 之间的内容
    var start = text.indexOf('{');
    var end = text.lastIndexOf('}');
    if (start === -1 || end === -1 || end <= start) return null;

    var jsonStr = text.substring(start, end + 1);
    try {
        return JSON.parse(jsonStr);
    } catch (e) {
        // 尝试修复常见问题：单引号、末尾逗号
        try {
            jsonStr = jsonStr.replace(/'/g, '"').replace(/,\s*}/g, '}').replace(/,\s*]/g, ']');
            return JSON.parse(jsonStr);
        } catch (e2) {
            return null;
        }
    }
};

// 将牌名数组转为 card id 数组，每张牌只用一次
GuandanAPIAI.prototype._resolveCards = function(cardNames, hand, currentRank) {
    var used = [];
    var remaining = hand.slice();
    var resolved = [];

    for (var i = 0; i < cardNames.length; i++) {
        var name = cardNames[i].trim();
        var candidates = cardNameToIds(name, remaining, currentRank);
        if (candidates.length > 0) {
            var picked = candidates[0];
            resolved.push(picked);
            var idx = remaining.indexOf(picked);
            if (idx !== -1) remaining.splice(idx, 1);
        }
        // 找不到就跳过，后面会验证合法性
    }

    return resolved;
};

// 调用 API
GuandanAPIAI.prototype.getPlay = function(playerIdx, callback) {
    var self = this;
    var config = this.config;
    var game = this.game;

    // 构建消息
    var messages = [];

    // system prompt
    var sysPrompt = config.systemPrompt || '';
    if (config.rolePrompt) {
        sysPrompt += '\n\n## 你的角色\n' + config.rolePrompt;
        sysPrompt += '\n请以这个角色的语气说话和做决策。';
    }
    messages.push({ role: 'system', content: sysPrompt });

    // user prompt
    var userPrompt = this.buildUserPrompt(playerIdx);
    messages.push({ role: 'user', content: userPrompt });

    // API URL
    var url = config.url.replace(/\/+$/, '');
    if (!url.endsWith('/v1')) {
        if (url.includes('/v1/')) url = url.substring(0, url.indexOf('/v1') + 3);
    }
    url += '/chat/completions';

    var body = {
        model: config.model,
        messages: messages,
        temperature: config.temperature !== undefined ? config.temperature : 0.7,
        max_tokens: 500
    };

    fetch(url, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            'Authorization': 'Bearer ' + config.key
        },
        body: JSON.stringify(body)
    })
    .then(function(resp) {
        if (!resp.ok) throw new Error('API HTTP ' + resp.status);
        return resp.json();
    })
    .then(function(data) {
        var content = '';
        if (data.choices && data.choices[0]) {
            content = data.choices[0].message ? data.choices[0].message.content : '';
        }
        if (!content) throw new Error('API 返回为空');

        var parsed = self.parseResponse(content, game.hands[playerIdx], game.currentRank);

        // 验证出牌合法性
        if (parsed.action === 'play' && parsed.cards.length > 0) {
            var type = analyzeCards(parsed.cards, game.currentRank);
            if (type.type === GDType.INVALID) {
                console.warn('AI 出牌不合法，降级规则引擎', parsed.cards);
                callback({ fallback: true, speech: parsed.speech });
                return;
            }
            // 如果需要跟牌，检查能不能压过
            if (game.lastPlayedBy !== -1 && game.lastPlayedBy !== playerIdx) {
                if (!canBeat(game.lastPlayedType, parsed.cards, game.currentRank)) {
                    console.warn('AI 出牌压不过上家，降级规则引擎', parsed.cards);
                    callback({ fallback: true, speech: parsed.speech });
                    return;
                }
            }
            callback({ action: 'play', cards: parsed.cards, speech: parsed.speech });
        } else {
            callback({ action: 'pass', cards: [], speech: parsed.speech });
        }
    })
    .catch(function(err) {
        console.error('API AI 调用失败:', err);
        callback({ fallback: true, speech: '' });
    });
};
