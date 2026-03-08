// ========== 掼蛋 AI ==========
function GuandanAI(name) { this.name = name; }

GuandanAI.prototype.choosePlay = function(hand, currentRank) {
    var sorted = sortCards(hand, currentRank);
    if (sorted.length === 0) return null;
    var pg = getPointGroups(sorted, currentRank);
    var groups = pg.groups;
    var weights = Object.keys(groups).map(Number).sort(function(a,b){return a-b;});
    // 顺子
    var str = this._findAnyStraight(groups, weights, 5);
    if (str) return str;
    // 连对
    var ds = this._findAnyDoubleStraight(groups, weights, 3);
    if (ds) return ds;
    // 三带二
    for (var i = 0; i < weights.length; i++) {
        var w = weights[i];
        if (groups[w].length >= 3) {
            var triple = groups[w].slice(0, 3);
            for (var j = 0; j < weights.length; j++) { if (weights[j] !== w && groups[weights[j]].length >= 2) return triple.concat(groups[weights[j]].slice(0, 2)); }
        }
    }
    // 对子
    for (var i = 0; i < weights.length; i++) if (groups[weights[i]].length === 2) return groups[weights[i]].slice(0, 2);
    // 三条
    for (var i = 0; i < weights.length; i++) if (groups[weights[i]].length === 3) return groups[weights[i]].slice(0, 3);
    // 单牌
    for (var i = 0; i < weights.length; i++) if (groups[weights[i]].length === 1) return [groups[weights[i]][0]];
    return [sorted[0]];
};

GuandanAI.prototype.chooseFollow = function(hand, lastType, currentRank) {
    var sorted = sortCards(hand, currentRank);
    var pg = getPointGroups(sorted, currentRank);
    var groups = pg.groups, wilds = pg.wilds;
    var weights = Object.keys(groups).map(Number).sort(function(a,b){return a-b;});
    var result = null;
    switch (lastType.type) {
        case GDType.SINGLE: result = this._followSingle(groups, weights, wilds, lastType); break;
        case GDType.PAIR: result = this._followPair(groups, weights, wilds, lastType); break;
        case GDType.TRIPLE: result = this._followTriple(groups, weights, lastType); break;
        case GDType.TRIPLE_TWO: result = this._followTripleTwo(groups, weights, lastType); break;
        case GDType.STRAIGHT: result = this._followStraight(groups, weights, lastType); break;
        case GDType.DOUBLE_STRAIGHT: result = this._followDoubleStraight(groups, weights, lastType); break;
        case GDType.PLATE: result = this._followPlate(groups, weights, lastType); break;
        case GDType.BOMB4: case GDType.BOMB5: case GDType.BOMB6: case GDType.BOMB7: case GDType.BOMB8:
            var bs = lastType.type - GDType.BOMB4 + 4;
            for (var i = 0; i < weights.length; i++) if (weights[i] > lastType.weight && groups[weights[i]].length >= bs) return groups[weights[i]].slice(0, bs);
            break;
        case GDType.STRAIGHT_FLUSH: result = this._followStraightFlush(sorted, lastType, currentRank); break;
    }
    if (result) return result;
    if (sorted.length <= 8) {
        var bomb = this._findAnyBomb(groups, weights, lastType);
        if (bomb) return bomb;
        var jokers = sorted.filter(function(id) { return getRawCardInfo(id).isJoker; });
        if (jokers.length === 4) return jokers;
    }
    return null;
};

GuandanAI.prototype._followSingle = function(g, w, wi, lt) {
    for (var i=0;i<w.length;i++) if(w[i]>lt.weight&&g[w[i]].length===1) return [g[w[i]][0]];
    for (var i=0;i<w.length;i++) if(w[i]>lt.weight&&g[w[i]].length>=2&&w[i]<=15) return [g[w[i]][0]];
    for (var i=0;i<w.length;i++) if(w[i]>lt.weight) return [g[w[i]][0]];
    if (wi.length>0&&98>lt.weight) return [wi[0]]; return null;
};
GuandanAI.prototype._followPair = function(g, w, wi, lt) {
    for (var i=0;i<w.length;i++) if(w[i]>lt.weight&&g[w[i]].length>=2) return g[w[i]].slice(0,2);
    if (wi.length>=1) for (var i=0;i<w.length;i++) if(w[i]>lt.weight&&g[w[i]].length>=1) return [g[w[i]][0],wi[0]];
    return null;
};
GuandanAI.prototype._followTriple = function(g, w, lt) {
    for (var i=0;i<w.length;i++) if(w[i]>lt.weight&&g[w[i]].length>=3) return g[w[i]].slice(0,3); return null;
};
GuandanAI.prototype._followTripleTwo = function(g, w, lt) {
    for (var i=0;i<w.length;i++) { var wt=w[i]; if(wt>lt.weight&&g[wt].length>=3) { var t=g[wt].slice(0,3); for(var j=0;j<w.length;j++) if(w[j]!==wt&&g[w[j]].length>=2) return t.concat(g[w[j]].slice(0,2)); } } return null;
};
GuandanAI.prototype._followStraight = function(g, w, lt) {
    var len=lt.length; for(var st=lt.weight+1;st<=14-len+1;st++){var ok=true,r=[];for(var i=0;i<len;i++){var wt=st+i;if(!g[wt]||g[wt].length===0){ok=false;break;}r.push(g[wt][0]);}if(ok)return r;} return null;
};
GuandanAI.prototype._followDoubleStraight = function(g, w, lt) {
    var pc=lt.length; for(var st=lt.weight+1;st<=14-pc+1;st++){var ok=true,r=[];for(var i=0;i<pc;i++){var wt=st+i;if(!g[wt]||g[wt].length<2){ok=false;break;}r=r.concat(g[wt].slice(0,2));}if(ok)return r;} return null;
};
GuandanAI.prototype._followPlate = function(g, w, lt) {
    var tc=lt.length; for(var st=lt.weight+1;st<=14-tc+1;st++){var ok=true,r=[];for(var i=0;i<tc;i++){var wt=st+i;if(!g[wt]||g[wt].length<3){ok=false;break;}r=r.concat(g[wt].slice(0,3));}if(ok)return r;} return null;
};
GuandanAI.prototype._followStraightFlush = function(sorted, lt, cr) {
    var bs={}; sorted.forEach(function(id){var info=getRawCardInfo(id);if(info.isJoker)return;var w=getCardWeight(id,cr);if(w<2||w>14)return;if(!bs[info.suitIdx])bs[info.suitIdx]={};if(!bs[info.suitIdx][w])bs[info.suitIdx][w]=id;});
    for(var s=0;s<4;s++){if(!bs[s])continue;for(var st=lt.weight+1;st<=10;st++){var ok=true,r=[];for(var i=0;i<5;i++){if(!bs[s][st+i]){ok=false;break;}r.push(bs[s][st+i]);}if(ok)return r;}} return null;
};
GuandanAI.prototype._findAnyStraight = function(g, w, ml) {
    var nw=w.filter(function(v){return v>=2&&v<=14;});
    for(var len=ml;len<=Math.min(12,nw.length);len++) for(var i=0;i<=nw.length-len;i++){var st=nw[i],ok=true,r=[];for(var j=0;j<len;j++){var wt=st+j;if(!g[wt]||g[wt].length===0){ok=false;break;}r.push(g[wt][0]);}if(ok&&r.length===len)return r;} return null;
};
GuandanAI.prototype._findAnyDoubleStraight = function(g, w, mp) {
    var nw=w.filter(function(v){return v>=2&&v<=14;});
    for(var pc=mp;pc<=nw.length;pc++) for(var i=0;i<=nw.length-pc;i++){var st=nw[i],ok=true,r=[];for(var j=0;j<pc;j++){var wt=st+j;if(!g[wt]||g[wt].length<2){ok=false;break;}r=r.concat(g[wt].slice(0,2));}if(ok&&r.length===pc*2)return r;} return null;
};
GuandanAI.prototype._findAnyBomb = function(g, w, lt) {
    var lp=getTypePriority(lt.type);
    for(var sz=4;sz<=8;sz++){var bt=[0,0,0,0,GDType.BOMB4,GDType.BOMB5,GDType.BOMB6,GDType.BOMB7,GDType.BOMB8];var bp=getTypePriority(bt[sz]);if(bp>lp){for(var i=0;i<w.length;i++)if(g[w[i]].length>=sz)return g[w[i]].slice(0,sz);}else if(bp===lp){for(var i=0;i<w.length;i++)if(g[w[i]].length>=sz&&w[i]>lt.weight)return g[w[i]].slice(0,sz);}} return null;
};

GuandanAI.prototype.chooseTribute = function(hand, currentRank) {
    var sorted = sortCards(hand, currentRank);
    for (var i = sorted.length - 1; i >= 0; i--) if (!isWildCard(sorted[i], currentRank)) return sorted[i];
    return sorted[sorted.length - 1];
};
GuandanAI.prototype.chooseReturn = function(hand, currentRank) {
    var sorted = sortCards(hand, currentRank);
    for (var i = 0; i < sorted.length; i++) {
        var info = getRawCardInfo(sorted[i]);
        if (info.isJoker) continue;
        if (isLevelCard(sorted[i], currentRank)) continue;
        if (isWildCard(sorted[i], currentRank)) continue;
        if (getCardWeight(sorted[i], currentRank) <= 10) return sorted[i];
    }
    return sorted[0];
};
