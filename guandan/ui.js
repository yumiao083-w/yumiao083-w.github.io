// ========== 掼蛋 UI 控制层 ==========

class GuandanUI {
    constructor() {
        this.game = new GuandanGame();
        this.animDelay = 5000;
        this.timerInterval = null;
        this.timerSeconds = 0;
    }

    startGame() {
        var startScreen = document.getElementById('start-screen');
        if (startScreen) startScreen.style.display = 'none';
        document.getElementById('result-screen').style.display = 'none';
        document.getElementById('tribute-overlay').style.display = 'none';
        this._tributeIdx = 0;
        this._returnIdx = 0;

        const result = this.game.startRound();
        this._updateLevelDisplay();
        this._renderAllHands();
        this._clearAllPlayed();
        this._clearAllActions();

        if (result.action === 'anti-tribute') {
            this._showInfo('抗贡！失败方有两张大王，拒绝进贡。');
            setTimeout(() => {
                this._showInfo(`${this.game.playerNames[result.headPlayer]} 先出牌`);
                this._startPlayPhase();
            }, 1500);
        } else if (result.action === 'tribute') {
            this._processTributeQueue();
        } else {
            this._showInfo(`${this.game.playerNames[this.game.currentPlayer]} 先出牌`);
            this._startPlayPhase();
        }
    }

    _processTributeQueue() {
        this._tributeIdx = this._tributeIdx || 0;
        const queue = this.game.tributeQueue;

        if (this._tributeIdx >= queue.length) {
            // 进贡全部完成，开始还贡
            this._tributeIdx = 0;
            this._processReturnQueue();
            return;
        }

        const idx = this._tributeIdx;
        const item = queue[idx];

        // 进贡：自动选最大牌（规则固定）
        const options = this.game.getTributeOptions(item.from);
        var selectedCard;

        if (item.from === 0 && options.length > 1) {
            // 用户有多张同权重牌可选花色，弹出选择
            this._showTributeUI('进贡', '你需要进贡最大的牌，请选择花色:', options, (cardId) => {
                this.game.executeTribute(idx, cardId);
                const info = getRawCardInfo(cardId);
                this._showInfo(this.game.playerNames[item.from] + ' 向 ' + this.game.playerNames[item.to] + ' 进贡 ' + info.rank + info.suit);
                this._renderAllHands();
                this._tributeIdx++;
                setTimeout(() => this._processTributeQueue(), 800);
            });
            return;
        }

        // AI 或只有一张可选：自动
        selectedCard = options.length > 0 ? options[0] : this.game.hands[item.from][this.game.hands[item.from].length - 1];
        this.game.executeTribute(idx, selectedCard);
        const info = getRawCardInfo(selectedCard);
        this._showInfo(this.game.playerNames[item.from] + ' 向 ' + this.game.playerNames[item.to] + ' 进贡 ' + info.rank + info.suit);
        this._renderAllHands();
        this._tributeIdx++;
        setTimeout(() => this._processTributeQueue(), 800);
    }

    _processReturnQueue() {
        const queue = this.game.returnQueue;

        if (this._returnIdx === undefined) this._returnIdx = 0;

        if (this._returnIdx >= queue.length) {
            // 还贡全部完成
            this._tributeIdx = 0;
            this._returnIdx = 0;
            this._showInfo('进贡/还贡完成');
            const order = this.game.prevResult.finishOrder;
            this.game.currentPlayer = order[order.length - 1]; // 末游先出
            this.game.phase = 'playing';
            this._renderAllHands();
            setTimeout(() => this._startPlayPhase(), 1000);
            return;
        }

        const idx = this._returnIdx;
        const item = queue[idx];
        const options = this.game.getReturnOptions(item.from);

        if (item.from === 0) {
            // 用户手动选还贡牌
            this._showTributeUI('还贡', '请选择一张牌还贡给 ' + this.game.playerNames[item.to] + '（不能还大牌、级牌、逢人配）:', options, (cardId) => {
                this.game.executeReturn(idx, cardId);
                const info = getRawCardInfo(cardId);
                this._showInfo(this.game.playerNames[item.from] + ' 还贡 ' + info.rank + info.suit + ' 给 ' + this.game.playerNames[item.to]);
                this._renderAllHands();
                this._returnIdx++;
                setTimeout(() => this._processReturnQueue(), 800);
            });
            return;
        }

        // AI 自动还贡
        const ai = new GuandanAI('return');
        const selectedCard = ai.chooseReturn(this.game.hands[item.from], this.game.currentRank);
        this.game.executeReturn(idx, selectedCard);
        const rInfo = getRawCardInfo(selectedCard);
        this._showInfo(this.game.playerNames[item.from] + ' 还贡 ' + rInfo.rank + rInfo.suit + ' 给 ' + this.game.playerNames[item.to]);
        this._renderAllHands();
        this._returnIdx++;
        setTimeout(() => this._processReturnQueue(), 800);
    }

    _showTributeUI(title, desc, cardOptions, callback) {
        this._tributeCallback = callback;
        this._tributeSelectedCard = null;
        document.getElementById('tribute-title').textContent = title;
        document.getElementById('tribute-desc').textContent = desc;
        document.getElementById('btn-tribute').disabled = true;

        const container = document.getElementById('tribute-cards');
        container.innerHTML = '';
        var self = this;
        cardOptions.forEach(function(id) {
            var cardEl = renderCard(id, self.game.currentRank);
            cardEl.style.cursor = 'pointer';
            cardEl.style.marginLeft = '0';
            cardEl.addEventListener('click', function() {
                container.querySelectorAll('.card').forEach(function(el) { el.classList.remove('selected'); });
                cardEl.classList.add('selected');
                self._tributeSelectedCard = id;
                document.getElementById('btn-tribute').disabled = false;
            });
            container.appendChild(cardEl);
        });

        document.getElementById('tribute-overlay').style.display = 'flex';
    }

    _startPlayPhase() {
        this.game.phase = 'playing';
        this._updateControls();
        this._showInfo(`轮到 ${this.game.playerNames[this.game.currentPlayer]} 出牌`);

        if (this.game.currentPlayer !== 0) {
            setTimeout(() => this._aiTurn(), this.animDelay);
        }
    }

    _aiTurn() {
        if (this.game.phase !== 'playing') return;
        const p = this.game.currentPlayer;
        if (p === 0) { this._updateControls(); return; }

        // 有 API 配置则走 API AI
        if (this.apiConfig && this.apiConfig.url && this.apiConfig.key && this.apiConfig.model) {
            this._showInfo(this.game.playerNames[p] + ' 思考中...');
            var apiAI = new GuandanAPIAI(this.apiConfig, this.game);
            var self = this;
            apiAI.getPlay(p, function(result) {
                if (result.fallback) {
                    // API 失败或出牌非法，降级规则引擎
                    if (result.speech) self._showSpeech(p, result.speech);
                    self._aiTurnLocal(p);
                } else if (result.action === 'play' && result.cards.length > 0) {
                    if (result.speech) self._showSpeech(p, result.speech);
                    self._executeAIPlay(p, result.cards);
                } else {
                    // AI 选择 pass — 但如果是首出（必须出牌），降级规则引擎
                    var mustPlay = (self.game.lastPlayedBy === -1 || self.game.lastPlayedBy === p);
                    if (mustPlay) {
                        console.warn('AI 选了 pass 但必须出牌，降级规则引擎');
                        if (result.speech) self._showSpeech(p, result.speech);
                        self._aiTurnLocal(p);
                    } else {
                        if (result.speech) self._showSpeech(p, result.speech);
                        self._executeAIPass(p);
                    }
                }
            });
            return;
        }

        // 没有 API 配置，走本地规则引擎
        this._aiTurnLocal(p);
    }

    _aiTurnLocal(p) {
        const cards = this.game.getAIPlay(p);
        if (cards && cards.length > 0) {
            this._executeAIPlay(p, cards);
        } else {
            this._executeAIPass(p);
        }
    }

    _executeAIPlay(p, cards) {
        const result = this.game.playCards(p, cards);
        if (result.ok) {
            this._showPlayed(p, cards);
            this._setAction(p, '');
            this._renderHand(p);

            if (result.roundEnd) {
                setTimeout(() => this._showRoundResult(result), 1000);
                return;
            }

            if (result.finished) {
                this._setAction(p, `[完] 第${this.game.finishOrder.indexOf(p)+1}个出完`);
            }

            const next = this.game.nextPlayer();
            this._showInfo(`轮到 ${this.game.playerNames[next]} 出牌`);
            this._updateControls();

            if (next !== 0) {
                setTimeout(() => this._aiTurn(), this.animDelay);
            }
        } else {
            // playCards 失败（不合法），降级强制出最小牌
            console.warn('AI play failed:', result.msg, cards);
            const forced = [this.game.hands[p][0]];
            const fResult = this.game.playCards(p, forced);
            if (fResult.ok) {
                this._showPlayed(p, forced);
                this._renderHand(p);
                if (fResult.roundEnd) {
                    setTimeout(() => this._showRoundResult(fResult), 1000);
                    return;
                }
                const next = this.game.nextPlayer();
                this._showInfo(`轮到 ${this.game.playerNames[next]} 出牌`);
                this._updateControls();
                if (next !== 0) setTimeout(() => this._aiTurn(), this.animDelay);
            }
        }
    }

    _executeAIPass(p) {
        const result = this.game.passPlay(p);
        if (result.ok) {
            this._setAction(p, '不出');
            this._showPlayed(p, null);
            const next = this.game.nextPlayer();
            this._showInfo(`轮到 ${this.game.playerNames[next]} 出牌`);
            this._updateControls();

            if (next !== 0) {
                setTimeout(() => {
                    this._setAction(p, '');
                    this._aiTurn();
                }, this.animDelay);
            } else {
                setTimeout(() => this._setAction(p, ''), this.animDelay);
            }
        } else {
            // 必须出牌但 AI 选了 pass，强制出最小的
            const forced = [this.game.hands[p][0]];
            const fResult = this.game.playCards(p, forced);
            if (fResult.ok) {
                this._showPlayed(p, forced);
                this._renderHand(p);
                if (fResult.roundEnd) {
                    setTimeout(() => this._showRoundResult(fResult), 1000);
                    return;
                }
                const next = this.game.nextPlayer();
                this._showInfo(`轮到 ${this.game.playerNames[next]} 出牌`);
                this._updateControls();
                if (next !== 0) setTimeout(() => this._aiTurn(), this.animDelay);
            }
        }
    }

    _showSpeech(p, text) {
        if (!text) return;
        var els = ['bottom-action', 'right-action', 'top-action', 'left-action'];
        var el = document.getElementById(els[p]);
        el.textContent = '"' + text.substring(0, 50) + (text.length > 50 ? '...' : '') + '"';
        el.classList.add('speech');
        setTimeout(function() { el.classList.remove('speech'); }, 4000);
    }

    // 用户出牌
    playCards() {
        if (this.game.currentPlayer !== 0) return;
        const selected = this._getSelectedCards();
        if (selected.length === 0) return;

        const result = this.game.playCards(0, selected);
        if (!result.ok) {
            this._showInfo('[X] ' + result.msg);
            return;
        }

        this._stopTimer();

        this._showPlayed(0, selected);
        this._renderHand(0);

        if (result.roundEnd) {
            setTimeout(() => this._showRoundResult(result), 1000);
            return;
        }

        if (result.finished) {
            this._setAction(0, `[完] 出完了！`);
        }

        const next = this.game.nextPlayer();
        this._showInfo(`轮到 ${this.game.playerNames[next]} 出牌`);
        this._updateControls();

        if (next !== 0) {
            setTimeout(() => this._aiTurn(), this.animDelay);
        }
    }

    pass() {
        if (this.game.currentPlayer !== 0) return;
        const result = this.game.passPlay(0);
        if (!result.ok) {
            this._showInfo('[X] ' + (result.msg || '必须出牌'));
            return;
        }

        this._stopTimer();

        this._setAction(0, '不出');
        this._showPlayed(0, null);

        const next = this.game.nextPlayer();
        this._showInfo(`轮到 ${this.game.playerNames[next]} 出牌`);
        this._updateControls();

        setTimeout(() => {
            this._setAction(0, '');
            if (next !== 0) this._aiTurn();
        }, this.animDelay);
    }

    hint() {
        if (this.game.currentPlayer !== 0) return;
        const ai = new GuandanAI('hint');
        let cards;
        if (this.game.lastPlayedBy === -1 || this.game.lastPlayedBy === 0) {
            cards = ai.choosePlay(this.game.hands[0], this.game.currentRank);
        } else {
            cards = ai.chooseFollow(this.game.hands[0], this.game.lastPlayedType, this.game.currentRank);
        }

        document.querySelectorAll('#bottom-cards .card.selected').forEach(el => el.classList.remove('selected'));

        if (cards) {
            cards.forEach(id => {
                const el = document.querySelector(`#bottom-cards .card[data-id="${id}"]`);
                if (el) el.classList.add('selected');
            });
        } else {
            this._showInfo('提示: 没有能出的牌');
        }
    }

    // ===== 倒计时 =====

    _startTimer() {
        this._stopTimer();
        this.timerSeconds = this.game.playerTimeout;
        var display = document.getElementById('timer-display');
        display.textContent = this.timerSeconds;
        display.classList.remove('warn');
        display.style.visibility = 'visible';
        var self = this;
        this.timerInterval = setInterval(function() {
            self.timerSeconds--;
            display.textContent = self.timerSeconds;
            if (self.timerSeconds <= 10) {
                display.classList.add('warn');
            }
            if (self.timerSeconds <= 0) {
                self._stopTimer();
                self._onTimeout();
            }
        }, 1000);
    }

    _stopTimer() {
        if (this.timerInterval) {
            clearInterval(this.timerInterval);
            this.timerInterval = null;
        }
        var display = document.getElementById('timer-display');
        display.textContent = '--';
        display.classList.remove('warn');
        display.style.visibility = 'hidden';
    }

    _onTimeout() {
        if (this.game.currentPlayer !== 0 || this.game.phase !== 'playing') return;
        // 能 pass 就 pass，否则出最小牌
        var canPass = this.game.lastPlayedBy !== -1 && this.game.lastPlayedBy !== 0;
        if (canPass) {
            this.pass();
        } else {
            // 必须出牌，出最小的单张
            var hand = this.game.hands[0];
            if (hand.length > 0) {
                var smallest = [hand[0]];
                var result = this.game.playCards(0, smallest);
                if (result.ok) {
                    this._showPlayed(0, smallest);
                    this._renderHand(0);
                    if (result.roundEnd) {
                        setTimeout(() => this._showRoundResult(result), 1000);
                        return;
                    }
                    var next = this.game.nextPlayer();
                    this._showInfo('超时自动出牌! 轮到 ' + this.game.playerNames[next] + ' 出牌');
                    this._updateControls();
                    if (next !== 0) {
                        setTimeout(() => this._aiTurn(), this.animDelay);
                    }
                }
            }
        }
    }

    // ===== 显示相关 =====

    _showRoundResult(result) {
        this._stopTimer();
        const orderNames = result.finishOrder.map((p, i) => {
            const titles = ['头游', '二游', '三游', '末游'];
            return `${titles[i]} ${this.game.playerNames[p]}`;
        });

        const teamName = result.winTeam === 0 ? 'A队(你的队伍)' : 'B队';
        const text = result.winTeam === 0 ? '你的队伍赢了！' : '对方队伍赢了';

        let detail = orderNames.join(' | ') + '\n';
        detail += `${teamName}升${result.upgrade}级`;
        if (result.switchTeam) detail += '（切换到对方等级）';
        detail += `\n下一局打: ${RANK_NAMES[this.game.currentRank]}`;

        document.getElementById('result-text').textContent = text;
        document.getElementById('result-text').style.color = result.winTeam === 0 ? '#ffd700' : '#ff6b6b';
        document.getElementById('result-detail').textContent = detail;
        document.getElementById('result-screen').style.display = 'flex';

        if (result.gameOver) {
            const winner = result.winner === 0 ? 'A队(你的队伍)' : 'B队';
            document.getElementById('result-text').textContent = `${winner} 赢得整场胜利！`;
        }
    }

    _updateLevelDisplay() {
        const aLevel = RANK_NAMES[this.game.teamLevels[0]];
        const bLevel = RANK_NAMES[this.game.teamLevels[1]];
        document.querySelector('.team-a-rank').textContent = aLevel;
        document.querySelector('.team-b-rank').textContent = bLevel;

        // 更新队名（可能被用户自定义了）
        document.querySelectorAll('.team-a-name').forEach(el => { el.textContent = this.game.teamNames[0]; });
        document.querySelectorAll('.team-b-name').forEach(el => { el.textContent = this.game.teamNames[1]; });

        document.getElementById('wild-card-display').textContent = this.game.getWildDisplay();

        // 高亮当前打的队
        const aEl = document.getElementById('team-a-level');
        const bEl = document.getElementById('team-b-level');
        if (this.game.currentTeam === 0) {
            aEl.style.color = '#ffd700'; bEl.style.color = '#ccc';
        } else {
            bEl.style.color = '#ffd700'; aEl.style.color = '#ccc';
        }
    }

    _renderAllHands() {
        this._renderHand(0);
        this._renderHand(1);
        this._renderHand(2);
        this._renderHand(3);
    }

    _renderHand(p) {
        const containers = ['bottom-cards', 'right-cards', 'top-cards', 'left-cards'];
        const el = document.getElementById(containers[p]);
        el.innerHTML = '';

        if (p === 0) {
            // 用户手牌：显示正面
            this.game.hands[0].forEach(id => {
                el.appendChild(renderCard(id, this.game.currentRank, { selectable: true }));
            });
        } else {
            // AI手牌：显示为单个牌图标+数字
            const count = this.game.hands[p].length;
            const icon = document.createElement('div');
            icon.className = 'card-count-icon';
            icon.innerHTML = '<span class="count-number">' + count + '</span><span class="count-label">张</span>';
            el.appendChild(icon);
            // 同步更新 info 栏的张数
            const area = ['player-bottom', 'player-right', 'player-top', 'player-left'][p];
            const countEl = document.querySelector(`#${area} .card-count`);
            if (countEl) countEl.textContent = `(${count}张)`;
        }
    }

    _showPlayed(p, cards) {
        const slots = ['played-bottom', 'played-right', 'played-top', 'played-left'];
        const el = document.getElementById(slots[p]);
        el.innerHTML = '';
        if (cards) {
            sortCards(cards, this.game.currentRank).forEach(id => {
                el.appendChild(renderCard(id, this.game.currentRank));
            });
        }
    }

    _clearAllPlayed() {
        ['played-bottom', 'played-right', 'played-top', 'played-left'].forEach(id => {
            document.getElementById(id).innerHTML = '';
        });
    }

    _setAction(p, text) {
        const els = ['bottom-action', 'right-action', 'top-action', 'left-action'];
        document.getElementById(els[p]).textContent = text;
    }

    _clearAllActions() {
        ['bottom-action', 'right-action', 'top-action', 'left-action'].forEach(id => {
            document.getElementById(id).textContent = '';
        });
    }

    _showInfo(text) {
        document.getElementById('game-info').textContent = text;
    }

    _getSelectedCards() {
        const selected = [];
        document.querySelectorAll('#bottom-cards .card.selected').forEach(el => {
            selected.push(parseInt(el.dataset.id));
        });
        return selected;
    }

    _updateControls() {
        const isMyTurn = this.game.currentPlayer === 0 && this.game.phase === 'playing';
        const canPass = isMyTurn && this.game.lastPlayedBy !== -1 && this.game.lastPlayedBy !== 0;

        document.getElementById('btn-play').disabled = !isMyTurn;
        document.getElementById('btn-pass').disabled = !canPass;
        document.getElementById('btn-hint').disabled = !isMyTurn;

        if (isMyTurn) {
            if (!this.timerInterval) this._startTimer();
        } else {
            this._stopTimer();
        }
    }

    submitTribute() {
        if (!this._tributeSelectedCard || !this._tributeCallback) return;
        document.getElementById('tribute-overlay').style.display = 'none';
        var callback = this._tributeCallback;
        var cardId = this._tributeSelectedCard;
        this._tributeCallback = null;
        this._tributeSelectedCard = null;
        callback(cardId);
    }

    applyConfig() {
        // 读取配置值
        var playerName = document.getElementById('cfg-player-name').value.trim() || '我';
        var partnerName = document.getElementById('cfg-partner-name').value.trim() || '对家';
        var teamA = document.getElementById('cfg-team-a').value.trim() || 'A队';
        var teamB = document.getElementById('cfg-team-b').value.trim() || 'B队';
        var aiDelay = parseInt(document.getElementById('cfg-ai-delay').value) || 5;
        var playerTimeout = parseInt(document.getElementById('cfg-player-timeout').value) || 30;

        // 限制范围
        if (aiDelay < 1) aiDelay = 1;
        if (aiDelay > 30) aiDelay = 30;
        if (playerTimeout < 10) playerTimeout = 10;
        if (playerTimeout > 120) playerTimeout = 120;

        // 应用到 game
        this.game.playerNames = [playerName, '电脑B', partnerName, '电脑A'];
        this.game.teamNames = [teamA, teamB];
        this.game.aiDelay = aiDelay * 1000;
        this.game.playerTimeout = playerTimeout;
        this.animDelay = aiDelay * 1000;

        // 更新界面上的名字
        document.getElementById('name-bottom').textContent = playerName;
        document.getElementById('name-top').textContent = partnerName;
        document.getElementById('name-right').textContent = '电脑B';
        document.getElementById('name-left').textContent = '电脑A';

        // 更新队名
        document.querySelectorAll('.team-a-name').forEach(function(el) { el.textContent = teamA; });
        document.querySelectorAll('.team-b-name').forEach(function(el) { el.textContent = teamB; });

        // 存储 API 配置
        var modelSelect = document.getElementById('cfg-model-select');
        var manualModel = document.getElementById('cfg-api-model').value.trim();
        var selectedModel = '';
        if (document.getElementById('model-list-area').style.display !== 'none' && modelSelect.value) {
            selectedModel = modelSelect.value;
        } else {
            selectedModel = manualModel;
        }

        this.apiConfig = {
            url: document.getElementById('cfg-api-url').value.trim(),
            key: document.getElementById('cfg-api-key').value.trim(),
            model: selectedModel,
            temperature: parseFloat(document.getElementById('cfg-temperature').value) || 0.7,
            rolePrompt: document.getElementById('cfg-role-prompt').value.trim(),
            systemPrompt: document.getElementById('cfg-system-prompt').value.trim()
        };

        // 隐藏配置界面，开始游戏
        document.getElementById('config-screen').style.display = 'none';

        // 移动端自动请求全屏
        if (/Mobi|Android|iPhone|iPad/i.test(navigator.userAgent)) {
            var el = document.documentElement;
            var rfs = el.requestFullscreen || el.webkitRequestFullscreen || el.msRequestFullscreen;
            if (rfs && !document.fullscreenElement && !document.webkitFullscreenElement) {
                rfs.call(el).then(function() {
                    if (screen.orientation && screen.orientation.lock) {
                        screen.orientation.lock('landscape').catch(function(){});
                    }
                }).catch(function(){});
            }
        }

        this.startGame();
    }

    fetchModels() {
        var url = document.getElementById('cfg-api-url').value.trim();
        var key = document.getElementById('cfg-api-key').value.trim();
        if (!url || !key) {
            alert('请先填写 API 地址和 Key');
            return;
        }
        // 确保 url 以 /v1 结尾格式
        var base = url.replace(/\/+$/, '');
        if (!base.endsWith('/v1')) {
            if (base.includes('/v1/')) base = base.substring(0, base.indexOf('/v1') + 3);
            else base = base + '/v1';
        }
        var btn = document.getElementById('btn-fetch-models');
        btn.textContent = '加载中...';
        btn.disabled = true;

        fetch(base + '/models', {
            headers: { 'Authorization': 'Bearer ' + key }
        })
        .then(function(resp) {
            if (!resp.ok) throw new Error('HTTP ' + resp.status);
            return resp.json();
        })
        .then(function(data) {
            var models = (data.data || data.models || []);
            var select = document.getElementById('cfg-model-select');
            select.innerHTML = '<option value="">-- 选择模型 --</option>';
            models.sort(function(a, b) { return (a.id || a.name || '').localeCompare(b.id || b.name || ''); });
            models.forEach(function(m) {
                var id = m.id || m.name || '';
                var opt = document.createElement('option');
                opt.value = id;
                opt.textContent = id;
                select.appendChild(opt);
            });
            // 切换到下拉模式
            document.getElementById('model-select-area').style.display = 'none';
            document.getElementById('model-list-area').style.display = 'flex';
            btn.textContent = '获取模型列表';
            btn.disabled = false;
        })
        .catch(function(err) {
            alert('获取模型失败: ' + err.message);
            btn.textContent = '获取模型列表';
            btn.disabled = false;
        });
    }

    switchToManualModel() {
        document.getElementById('model-select-area').style.display = 'block';
        document.getElementById('model-list-area').style.display = 'none';
    }

    resetPrompt() {
        document.getElementById('cfg-system-prompt').value = this._getDefaultPrompt();
    }

    _getDefaultPrompt() {
        return '你是一个掼蛋游戏AI玩家。\n\n' +
            '## 掼蛋规则\n' +
            '- 4人游戏，2v2，座位对面是队友\n' +
            '- 2副牌共108张，每人27张\n' +
            '- 牌型：单张、对子、三条、三带二、顺子(5-12张)、连对(3连起)、钢板(2连三条起)、炸弹(4-8同点)、同花顺(仅5张)、天王炸(4王)\n' +
            '- 炸弹大小：天王炸 > 八炸 > 七炸 > 六炸 > 同花顺 > 五炸 > 四炸\n' +
            '- 逢人配：当前级牌的红桃为万能牌，可替代任意牌\n' +
            '- 2最小，A最大，级牌权重高于A\n' +
            '- 同队两人都先出完则大胜(升3级)，头游+三游升2级，头游+末游升1级\n\n' +
            '## 输出格式（严格遵守）\n' +
            '先输出一句角色台词（简短，符合角色性格），然后换行输出分隔符和JSON：\n\n' +
            '你的台词...\n' +
            '===PLAY===\n' +
            '{"action":"play","cards":["红桃3","方块5"]}\n\n' +
            '或者不出：\n' +
            '你的台词...\n' +
            '===PLAY===\n' +
            '{"action":"pass"}\n\n' +
            '## 注意\n' +
            '- cards 中每张牌格式为 "花色+点数"，如 "红桃A" "方块10" "小王" "大王"\n' +
            '- 逢人配写原始牌名如 "红桃5"（当打5时），不要写"配"\n' +
            '- 必须从你的手牌中选择，不能出没有的牌\n' +
            '- 出牌必须合法（符合牌型要求，跟牌必须压过上家）\n' +
            '- 考虑策略：保护队友、合理拆牌、适时炸弹';
    }
}

const gameUI = new GuandanUI();

// 初始化默认提示词
document.addEventListener('DOMContentLoaded', function() {
    var promptEl = document.getElementById('cfg-system-prompt');
    if (promptEl && !promptEl.value) {
        promptEl.value = gameUI._getDefaultPrompt();
    }
});
