// ========== 扑克牌定义（2副牌108张） ==========
var SUITS = ['\u2666', '\u2663', '\u2665', '\u2660'];
var SUIT_NAMES = ['方块', '梅花', '红桃', '黑桃'];
var RANK_NAMES = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A'];

function getBaseId(id) { return id % 54; }

function getRawCardInfo(id) {
    var base = getBaseId(id);
    if (base === 52) return { rank: '小', suit: '王', rankIdx: -1, suitIdx: -1, isJoker: true, isBigJoker: false };
    if (base === 53) return { rank: '大', suit: '王', rankIdx: -1, suitIdx: -1, isJoker: true, isBigJoker: true };
    var suitIdx = Math.floor(base / 13);
    var rankIdx = base % 13;
    return { rank: RANK_NAMES[rankIdx], suit: SUITS[suitIdx], rankIdx: rankIdx, suitIdx: suitIdx, isJoker: false, isBigJoker: false };
}

// 权重：2最小(weight=2), 3=3, ..., A=14, 级牌=97, 逢人配=98, 小王=99, 大王=100
function getCardWeight(id, currentRank) {
    var info = getRawCardInfo(id);
    if (info.isBigJoker) return 100;
    if (info.isJoker) return 99;
    if (isWildCard(id, currentRank)) return 98;
    if (info.rankIdx === currentRank) return 97;
    return info.rankIdx + 2;
}

function isWildCard(id, currentRank) {
    var info = getRawCardInfo(id);
    return !info.isJoker && info.suitIdx === 2 && info.rankIdx === currentRank;
}

function isLevelCard(id, currentRank) {
    var info = getRawCardInfo(id);
    return !info.isJoker && info.rankIdx === currentRank;
}

function getCardColor(id) {
    var info = getRawCardInfo(id);
    if (info.isBigJoker) return 'joker-red';
    if (info.isJoker) return 'joker-black';
    return (info.suitIdx === 0 || info.suitIdx === 2) ? 'red' : 'black';
}

function getCardDisplayName(id, currentRank) {
    var info = getRawCardInfo(id);
    if (info.isJoker) return info.rank + info.suit;
    var name = info.suit + info.rank;
    if (isWildCard(id, currentRank)) name += '(配)';
    return name;
}

function createDoubleDeck() {
    var deck = [];
    for (var i = 0; i < 108; i++) deck.push(i);
    return deck;
}

function shuffle(deck) {
    for (var round = 0; round < 3; round++) {
        for (var i = deck.length - 1; i > 0; i--) {
            var j = Math.floor(Math.random() * (i + 1));
            var tmp = deck[i]; deck[i] = deck[j]; deck[j] = tmp;
        }
    }
    return deck;
}

function sortCards(cards, currentRank) {
    return cards.slice().sort(function(a, b) {
        var wa = getCardWeight(a, currentRank);
        var wb = getCardWeight(b, currentRank);
        if (wa !== wb) return wa - wb;
        var ia = getRawCardInfo(a);
        var ib = getRawCardInfo(b);
        if (ia.suitIdx !== ib.suitIdx) return ia.suitIdx - ib.suitIdx;
        return a - b;
    });
}

function dealCards() {
    var deck = shuffle(createDoubleDeck());
    return [deck.slice(0, 27), deck.slice(27, 54), deck.slice(54, 81), deck.slice(81, 108)];
}

function renderCard(id, currentRank, options) {
    options = options || {};
    var info = getRawCardInfo(id);
    var color = getCardColor(id);
    var wild = isWildCard(id, currentRank);
    var el = document.createElement('div');
    el.className = 'card ' + color + (wild ? ' wild' : '');
    el.dataset.id = id;
    el.innerHTML = '<span class="card-rank">' + info.rank + '</span><span class="card-suit">' + info.suit + '</span>';
    if (options.selectable) {
        el.addEventListener('click', function() { el.classList.toggle('selected'); });
    }
    return el;
}

function renderCardBack() {
    var el = document.createElement('div');
    el.className = 'card-back';
    return el;
}
