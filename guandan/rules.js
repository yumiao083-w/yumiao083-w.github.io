// ========== 掼蛋规则引擎 ==========
// 炸弹等级: 天王炸 > 八炸 > 七 > 六 > 同花顺(仅5张) > 五 > 四
// 炸弹为同序号4+张（可不同花色），同花顺仅5张连续同花色

var GDType = {
    INVALID: 0, SINGLE: 1, PAIR: 2, TRIPLE: 3, TRIPLE_TWO: 4,
    STRAIGHT: 5, DOUBLE_STRAIGHT: 6, PLATE: 7,
    BOMB4: 10, BOMB5: 11, STRAIGHT_FLUSH: 12, BOMB6: 13, BOMB7: 14, BOMB8: 15,
    ROCKET: 20
};

var TYPE_NAMES = {};
TYPE_NAMES[GDType.SINGLE] = '单张'; TYPE_NAMES[GDType.PAIR] = '对子';
TYPE_NAMES[GDType.TRIPLE] = '三条'; TYPE_NAMES[GDType.TRIPLE_TWO] = '三带二';
TYPE_NAMES[GDType.STRAIGHT] = '顺子'; TYPE_NAMES[GDType.DOUBLE_STRAIGHT] = '连对';
TYPE_NAMES[GDType.PLATE] = '钢板'; TYPE_NAMES[GDType.BOMB4] = '炸弹';
TYPE_NAMES[GDType.BOMB5] = '五炸'; TYPE_NAMES[GDType.BOMB6] = '六炸';
TYPE_NAMES[GDType.BOMB7] = '七炸'; TYPE_NAMES[GDType.BOMB8] = '八炸';
TYPE_NAMES[GDType.STRAIGHT_FLUSH] = '同花顺'; TYPE_NAMES[GDType.ROCKET] = '天王炸';

function getTypePriority(type) {
    switch (type) {
        case GDType.ROCKET: return 100;
        case GDType.BOMB8: return 90;
        case GDType.BOMB7: return 80;
        case GDType.BOMB6: return 70;
        case GDType.STRAIGHT_FLUSH: return 65;
        case GDType.BOMB5: return 60;
        case GDType.BOMB4: return 50;
        default: return 0;
    }
}

function getPointGroups(cardIds, currentRank) {
    var groups = {}, wilds = [];
    cardIds.forEach(function(id) {
        if (isWildCard(id, currentRank)) { wilds.push(id); }
        else { var w = getCardWeight(id, currentRank); if (!groups[w]) groups[w] = []; groups[w].push(id); }
    });
    return { groups: groups, wilds: wilds };
}

function analyzeCards(cardIds, currentRank) {
    var len = cardIds.length;
    if (len === 0) return { type: GDType.INVALID };
    var pg = getPointGroups(cardIds, currentRank);
    var groups = pg.groups, wilds = pg.wilds;
    var weights = Object.keys(groups).map(Number).sort(function(a,b){return a-b;});

    // 天王炸（4张王）
    if (len === 4) {
        var jokers = cardIds.filter(function(id) { return getRawCardInfo(id).isJoker; });
        if (jokers.length === 4) return { type: GDType.ROCKET, weight: 999 };
    }
    // 有逢人配且不是单独打
    if (wilds.length > 0 && len > wilds.length) return analyzeWithWilds(cardIds, currentRank);
    // 单牌
    if (len === 1) return { type: GDType.SINGLE, weight: getCardWeight(cardIds[0], currentRank) };
    // 对子
    if (len === 2 && weights.length === 1 && groups[weights[0]].length === 2) return { type: GDType.PAIR, weight: weights[0] };
    // 三同
    if (len === 3 && weights.length === 1 && groups[weights[0]].length === 3) return { type: GDType.TRIPLE, weight: weights[0] };
    // 炸弹 (4-8张同点数)
    if (len >= 4 && len <= 8 && weights.length === 1) {
        var bm = {4:GDType.BOMB4,5:GDType.BOMB5,6:GDType.BOMB6,7:GDType.BOMB7,8:GDType.BOMB8};
        if (bm[len]) return { type: bm[len], weight: weights[0] };
    }
    // 同花顺 (仅5张)
    if (len === 5) {
        var allNorm = cardIds.every(function(id) { return !getRawCardInfo(id).isJoker && !isWildCard(id, currentRank); });
        if (allNorm) {
            var ws5 = cardIds.map(function(id){return getCardWeight(id,currentRank);}).sort(function(a,b){return a-b;});
            var su5 = cardIds.map(function(id){return getRawCardInfo(id).suitIdx;});
            if (su5.every(function(s){return s===su5[0];}) && ws5[4]-ws5[0]===4 && new Set(ws5).size===5 && ws5.every(function(w){return w>=2&&w<=14;}))
                return { type: GDType.STRAIGHT_FLUSH, weight: ws5[0] };
        }
    }
    // 三带二
    if (len === 5) {
        var ct5 = {};
        Object.keys(groups).forEach(function(w){var c=groups[w].length;if(!ct5[c])ct5[c]=[];ct5[c].push(Number(w));});
        if (ct5[3] && ct5[3].length===1 && ct5[2] && ct5[2].length===1) return { type: GDType.TRIPLE_TWO, weight: ct5[3][0] };
    }
    // 顺子
    if (len >= 5 && len <= 12) {
        var allS = Object.values(groups).every(function(g){return g.length===1;});
        if (allS && weights.length===len && wilds.length===0 && weights[len-1]-weights[0]===len-1 && weights.every(function(w){return w>=2&&w<=14;}))
            return { type: GDType.STRAIGHT, weight: weights[0], length: len };
    }
    // 连对
    if (len >= 6 && len%2===0) {
        var pc = len/2;
        var allP = Object.values(groups).every(function(g){return g.length===2;});
        if (allP && weights.length===pc && wilds.length===0 && weights[pc-1]-weights[0]===pc-1 && weights.every(function(w){return w>=2&&w<=14;}))
            return { type: GDType.DOUBLE_STRAIGHT, weight: weights[0], length: pc };
    }
    // 钢板
    if (len >= 6 && len%3===0) {
        var tc = len/3;
        var allT = Object.values(groups).every(function(g){return g.length===3;});
        if (allT && weights.length===tc && wilds.length===0) {
            var sw = weights.slice().sort(function(a,b){return a-b;});
            if (sw[tc-1]-sw[0]===tc-1 && sw.every(function(w){return w>=2&&w<=14;}))
                return { type: GDType.PLATE, weight: sw[0], length: tc };
        }
    }
    return { type: GDType.INVALID };
}

// 逢人配智能分析：从大到小优先补大牌
function analyzeWithWilds(cardIds, currentRank) {
    var len = cardIds.length;
    var pg = getPointGroups(cardIds, currentRank);
    var groups = pg.groups, wilds = pg.wilds, wildCount = wilds.length;
    var weights = Object.keys(groups).map(Number).sort(function(a,b){return a-b;});
    var candidates = [];

    // 对子
    if (len===2 && wildCount>=1 && weights.length===1) candidates.push({type:GDType.PAIR,weight:weights[0]});
    // 三同
    if (len===3) { for (var i=weights.length-1;i>=0;i--) { var w=weights[i]; if(groups[w].length+wildCount>=3){candidates.push({type:GDType.TRIPLE,weight:w});break;} } }
    // 三带二
    if (len===5) {
        for (var i=weights.length-1;i>=0;i--) {
            var w=weights[i],have=groups[w].length,need3=Math.max(0,3-have);
            if (need3>wildCount||have>3) continue;
            var rem=wildCount-need3,other=0;
            for(var j=0;j<weights.length;j++) if(weights[j]!==w) other+=groups[weights[j]].length;
            if (other+rem===2) candidates.push({type:GDType.TRIPLE_TWO,weight:w});
        }
    }
    // 炸弹
    if (len>=4&&len<=8) {
        for (var i=weights.length-1;i>=0;i--) {
            var w=weights[i],have=groups[w].length;
            if (have+wildCount>=len&&have>=1) {
                var bm={4:GDType.BOMB4,5:GDType.BOMB5,6:GDType.BOMB6,7:GDType.BOMB7,8:GDType.BOMB8};
                if(bm[len]) candidates.push({type:bm[len],weight:w});
            }
        }
    }
    // 顺子
    if (len>=5&&len<=12) {
        for (var st=14-len+1;st>=2;st--) {
            var nd=0,ok=true;
            for(var i=0;i<len;i++){var w=st+i;if(w>14){ok=false;break;}if(!groups[w]||groups[w].length===0)nd++;else if(groups[w].length>1){ok=false;break;}}
            if (ok&&nd<=wildCount) {
                if (len===5) { var nw=cardIds.filter(function(id){return !isWildCard(id,currentRank);}); var ss=nw.map(function(id){return getRawCardInfo(id).suitIdx;}); if(ss.length>0&&ss.every(function(s){return s===ss[0];})) candidates.push({type:GDType.STRAIGHT_FLUSH,weight:st}); }
                candidates.push({type:GDType.STRAIGHT,weight:st,length:len}); break;
            }
        }
    }
    // 连对
    if (len>=6&&len%2===0) { var pc=len/2; for(var st=14-pc+1;st>=2;st--){var nd=0,ok=true;for(var i=0;i<pc;i++){var w=st+i;if(w>14){ok=false;break;}var h=groups[w]?groups[w].length:0;if(h>2){ok=false;break;}nd+=(2-h);}if(ok&&nd<=wildCount){candidates.push({type:GDType.DOUBLE_STRAIGHT,weight:st,length:pc});break;}} }
    // 钢板
    if (len>=6&&len%3===0) { var tc=len/3; for(var st=14-tc+1;st>=2;st--){var nd=0,ok=true;for(var i=0;i<tc;i++){var w=st+i;if(w>14){ok=false;break;}var h=groups[w]?groups[w].length:0;if(h>3){ok=false;break;}nd+=(3-h);}if(ok&&nd<=wildCount){candidates.push({type:GDType.PLATE,weight:st,length:tc});break;}} }

    if (candidates.length===0) return {type:GDType.INVALID};
    candidates.sort(function(a,b){var pa=getTypePriority(a.type),pb=getTypePriority(b.type);if(pa!==pb)return pb-pa;return b.weight-a.weight;});
    return candidates[0];
}

function canBeat(lastType, newCards, currentRank) {
    var newType = analyzeCards(newCards, currentRank);
    if (newType.type === GDType.INVALID) return false;
    var lp = getTypePriority(lastType.type), np = getTypePriority(newType.type);
    if (newType.type === GDType.ROCKET) return true;
    if (lastType.type === GDType.ROCKET) return false;
    if (np > 0 && lp > 0) { if (np !== lp) return np > lp; return newType.weight > lastType.weight; }
    if (np > 0 && lp === 0) return true;
    if (np === 0 && lp > 0) return false;
    if (newType.type !== lastType.type) return false;
    if (newType.length !== undefined && lastType.length !== undefined && newType.length !== lastType.length) return false;
    return newType.weight > lastType.weight;
}
