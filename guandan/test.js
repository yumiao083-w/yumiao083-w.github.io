const fs = require('fs');
const vm = require('vm');
const ctx = vm.createContext({console, require, Math, Object, Array, Number, parseInt, Error});
vm.runInContext(fs.readFileSync('cards.js','utf8'), ctx);
vm.runInContext(fs.readFileSync('rules.js','utf8'), ctx);
vm.runInContext(fs.readFileSync('ai.js','utf8'), ctx);
vm.runInContext(fs.readFileSync('game.js','utf8'), ctx);

const testCode = `
const g = new GuandanGame();
g.startRound();
console.log("=== 掼蛋测试 ===");
console.log("当前打: " + RANK_NAMES[g.currentRank]);
console.log("逢人配: " + g.getWildDisplay());
console.log("先手: " + g.playerNames[g.currentPlayer]);
for (let i = 0; i < 4; i++) console.log(g.playerNames[i] + ": " + g.hands[i].length + "张");

let turns = 0;
while (g.phase === "playing" && turns < 120) {
    const p = g.currentPlayer;
    const ai = new GuandanAI("test");
    let cards;
    if (g.lastPlayedBy === -1 || g.lastPlayedBy === p) {
        cards = ai.choosePlay(g.hands[p], g.currentRank);
    } else {
        cards = ai.chooseFollow(g.hands[p], g.lastPlayedType, g.currentRank);
    }

    if (cards && cards.length > 0) {
        const result = g.playCards(p, cards);
        if (result.ok) {
            if (turns < 6) {
                const names = cards.map(function(id) {
                    const info = getRawCardInfo(id);
                    return info.rank + info.suit;
                }).join(" ");
                console.log(g.playerNames[p] + " 出: " + names);
            }
            if (result.roundEnd) {
                console.log("=== 本局结束 ===");
                console.log("出牌顺序: " + result.finishOrder.map(function(p){return g.playerNames[p]}).join(" > "));
                console.log("胜方: " + (result.winTeam === 0 ? "A队" : "B队") + " 升" + result.upgrade + "级");
                console.log("下一局打: " + RANK_NAMES[g.currentRank]);
                break;
            }
            g.nextPlayer();
        }
    } else {
        const pr = g.passPlay(p);
        if (pr.ok) {
            g.nextPlayer();
        } else {
            const forced = [g.hands[p][0]];
            const fr = g.playCards(p, forced);
            if (fr.ok) {
                if (fr.roundEnd) { console.log("局结束"); break; }
                g.nextPlayer();
            }
        }
    }
    turns++;
}
console.log("总回合: " + turns);
console.log("PASS");
`;

vm.runInContext(testCode, ctx);
