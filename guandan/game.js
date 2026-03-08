// ========== 掼蛋游戏逻辑 ==========

function GuandanGame() { this.reset(); }

GuandanGame.prototype.reset = function() {
    this.hands = [[], [], [], []];
    this.teams = [0, 1, 0, 1]; // 座位0=用户A, 1=右B, 2=对家A, 3=左B
    this.teamLevels = [0, 0]; // rankIdx: 0=打2, 1=打3, ..., 12=打A
    this.currentRank = 0;
    this.currentTeam = 0;
    this.currentPlayer = 0;
    this.lastPlayedCards = [];
    this.lastPlayedBy = -1;
    this.lastPlayedType = null;
    this.passCount = 0;
    this.finishOrder = [];
    this.phase = 'idle';
    this.roundNumber = 0;
    this.prevResult = null;
    this.playerNames = ['我', '电脑B', '对家', '电脑A'];
    this.teamNames = ['A队', 'B队'];
    this.tributeQueue = [];
    this.returnQueue = [];
    this.antiTribute = false;
    this.aiDelay = 5000;
    this.playerTimeout = 30;
};

GuandanGame.prototype.getRankName = function() { return RANK_NAMES[this.currentRank]; };
GuandanGame.prototype.getWildDisplay = function() { return '红桃' + RANK_NAMES[this.currentRank]; };

GuandanGame.prototype.startRound = function() {
    var dealt = dealCards();
    for (var i = 0; i < 4; i++) this.hands[i] = sortCards(dealt[i], this.currentRank);
    this.lastPlayedCards = []; this.lastPlayedBy = -1; this.lastPlayedType = null;
    this.passCount = 0; this.finishOrder = [];
    this.tributeQueue = []; this.returnQueue = []; this.antiTribute = false;
    this.roundNumber++;
    if (this.roundNumber === 1) { this.currentPlayer = Math.floor(Math.random() * 4); this.phase = 'playing'; return { action: 'play' }; }
    return this._checkTribute();
};

GuandanGame.prototype._checkTribute = function() {
    if (!this.prevResult) { this.currentPlayer = Math.floor(Math.random() * 4); this.phase = 'playing'; return { action: 'play' }; }
    var order = this.prevResult.finishOrder;
    var head = order[0], second = order[1], third = order[2], last = order[3];
    var headTeam = this.teams[head];
    this.tributeQueue = []; this.returnQueue = [];
    var isInternal = false;
    if (this.teams[second] === headTeam) { this.tributeQueue.push({from:third,to:head}); this.tributeQueue.push({from:last,to:second}); }
    else if (this.teams[third] === headTeam) { this.tributeQueue.push({from:last,to:head}); }
    else { this.tributeQueue.push({from:last,to:head}); isInternal = true; }

    // 抗贡
    if (!isInternal && this.tributeQueue.length > 0) {
        var losingTeam = 1 - headTeam, bigJokerCount = 0;
        for (var p = 0; p < 4; p++) if (this.teams[p] === losingTeam) for (var c = 0; c < this.hands[p].length; c++) if (getRawCardInfo(this.hands[p][c]).isBigJoker) bigJokerCount++;
        if (bigJokerCount >= 2) { this.antiTribute = true; this.tributeQueue = []; this.currentPlayer = head; this.phase = 'playing'; return { action: 'anti-tribute', headPlayer: head }; }
    }
    if (this.tributeQueue.length === 0) { this.currentPlayer = last; this.phase = 'playing'; return { action: 'play' }; }
    this.phase = 'tribute';
    return { action: 'tribute', queue: this.tributeQueue.slice() };
};

GuandanGame.prototype.executeTribute = function(tributeIdx, selectedCardId) {
    var item = this.tributeQueue[tributeIdx];
    this.hands[item.from] = this.hands[item.from].filter(function(id) { return id !== selectedCardId; });
    this.hands[item.to].push(selectedCardId);
    this.hands[item.to] = sortCards(this.hands[item.to], this.currentRank);
    this.returnQueue.push({ from: item.to, to: item.from });
    return selectedCardId;
};

GuandanGame.prototype.executeReturn = function(returnIdx, selectedCardId) {
    var item = this.returnQueue[returnIdx];
    this.hands[item.from] = this.hands[item.from].filter(function(id) { return id !== selectedCardId; });
    this.hands[item.to].push(selectedCardId);
    this.hands[item.to] = sortCards(this.hands[item.to], this.currentRank);
    return selectedCardId;
};

GuandanGame.prototype.isValidReturnCard = function(cardId) {
    var info = getRawCardInfo(cardId);
    if (info.isJoker) return false;
    if (isLevelCard(cardId, this.currentRank)) return false;
    if (isWildCard(cardId, this.currentRank)) return false;
    return getCardWeight(cardId, this.currentRank) <= 10;
};

// 进贡可选牌：最大权重的非逢人配牌（含级牌），同权重可选花色
GuandanGame.prototype.getTributeOptions = function(playerIdx) {
    var hand = this.hands[playerIdx], self = this;
    var maxW = -1;
    hand.forEach(function(id) { if (!isWildCard(id, self.currentRank)) { var w = getCardWeight(id, self.currentRank); if (w > maxW) maxW = w; } });
    return hand.filter(function(id) { return !isWildCard(id, self.currentRank) && getCardWeight(id, self.currentRank) === maxW; });
};

GuandanGame.prototype.getReturnOptions = function(playerIdx) {
    var self = this;
    return this.hands[playerIdx].filter(function(id) { return self.isValidReturnCard(id); });
};

GuandanGame.prototype.getAIPlay = function(playerIdx) {
    var ai = new GuandanAI('ai' + playerIdx);
    if (this.lastPlayedBy === -1 || this.lastPlayedBy === playerIdx) {
        return ai.choosePlay(this.hands[playerIdx], this.currentRank);
    } else {
        return ai.chooseFollow(this.hands[playerIdx], this.lastPlayedType, this.currentRank);
    }
};

GuandanGame.prototype.playCards = function(playerIdx, cardIds) {
    if (this.phase !== 'playing') return { ok: false, msg: '不在出牌阶段' };
    if (playerIdx !== this.currentPlayer) return { ok: false, msg: '不是你的回合' };
    var type = analyzeCards(cardIds, this.currentRank);
    if (type.type === GDType.INVALID) return { ok: false, msg: '不合法的牌型' };
    if (this.lastPlayedBy !== -1 && this.lastPlayedBy !== playerIdx) {
        if (!canBeat(this.lastPlayedType, cardIds, this.currentRank)) return { ok: false, msg: '压不过上家' };
    }
    var self = this;
    cardIds.forEach(function(id) { var idx = self.hands[playerIdx].indexOf(id); if (idx !== -1) self.hands[playerIdx].splice(idx, 1); });
    this.lastPlayedCards = cardIds; this.lastPlayedBy = playerIdx; this.lastPlayedType = type; this.passCount = 0;
    if (this.hands[playerIdx].length === 0) {
        this.finishOrder.push(playerIdx);
        if (this.finishOrder.length >= 3 || this._teamFinished()) return this._endRound(playerIdx);
    }
    return { ok: true, type: type, finished: this.hands[playerIdx].length === 0 };
};

GuandanGame.prototype.passPlay = function(playerIdx) {
    if (playerIdx !== this.currentPlayer) return { ok: false };
    if (this.lastPlayedBy === -1 || this.lastPlayedBy === playerIdx) return { ok: false, msg: '必须出牌' };
    this.passCount++;
    return { ok: true };
};

GuandanGame.prototype.nextPlayer = function() {
    var next = (this.currentPlayer + 1) % 4, attempts = 0;
    while (this.finishOrder.indexOf(next) !== -1 && attempts < 4) { next = (next + 1) % 4; attempts++; }
    // 接风
    if (this.passCount >= this._activePlayers() - 1) {
        if (this.finishOrder.indexOf(this.lastPlayedBy) !== -1) {
            var tm = this._getTeammate(this.lastPlayedBy);
            this.currentPlayer = this.finishOrder.indexOf(tm) === -1 ? tm : next;
        } else { this.currentPlayer = this.lastPlayedBy; }
        this.lastPlayedBy = -1; this.lastPlayedType = null; this.lastPlayedCards = []; this.passCount = 0;
        return this.currentPlayer;
    }
    this.currentPlayer = next;
    return next;
};

GuandanGame.prototype._activePlayers = function() { return 4 - this.finishOrder.length; };
GuandanGame.prototype._getTeammate = function(p) { return (p + 2) % 4; };
GuandanGame.prototype._teamFinished = function() { return this.finishOrder.length >= 2 && this.teams[this.finishOrder[0]] === this.teams[this.finishOrder[1]]; };

GuandanGame.prototype._endRound = function(lastFinisher) {
    while (this.finishOrder.length < 4) for (var i = 0; i < 4; i++) if (this.finishOrder.indexOf(i) === -1) this.finishOrder.push(i);
    var order = this.finishOrder, head = order[0], second = order[1];
    var headTeam = this.teams[head], winTeam, upgrade;
    if (this.teams[second] === headTeam) { winTeam = headTeam; upgrade = 3; }
    else if (this.teams[order[2]] === headTeam) { winTeam = headTeam; upgrade = 2; }
    else { winTeam = headTeam; upgrade = 1; }

    var switchTeam = (winTeam !== this.currentTeam);
    if (!switchTeam) {
        this.teamLevels[winTeam] = Math.min(this.teamLevels[winTeam] + upgrade, 12);
        this.currentRank = this.teamLevels[winTeam];
    } else {
        this.currentTeam = winTeam;
        this.currentRank = this.teamLevels[winTeam]; // 切换时打对方上次的等级
    }

    this.prevResult = { finishOrder: order.slice(), headPlayer: head };
    this.phase = 'result';
    var gameOver = this.teamLevels[winTeam] > 12;
    if (gameOver) this.teamLevels[winTeam] = 12;
    return { ok: true, roundEnd: true, finishOrder: order, winTeam: winTeam, upgrade: upgrade, switchTeam: switchTeam, gameOver: gameOver, winner: gameOver ? winTeam : -1, newRank: this.currentRank };
};
