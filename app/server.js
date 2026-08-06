'use strict';
const express = require('express');
const http = require('http');
const WebSocket = require('ws');
const path = require('path');
const crypto = require('crypto');

const app = express();
const server = http.createServer(app);
const wss = new WebSocket.Server({ server });

app.use('/images', express.static('/Users/nb/Claude/Projects/Karma/Bilder'));
app.use(express.static(path.join(__dirname, 'public')));

// ─── Card Data ───────────────────────────────────────────────────────────────
const CARD_DEFS = [
  { nr:1,  name:'Olli',                  value:1,  ability:'none',       quote:'Eier, we need Eier',                       count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:2,  name:'Tupac',                 value:2,  ability:'none',       quote:'Chill, Alter, es kommen auch gute Zeiten.', count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:3,  name:'Arnold', value:3,  ability:'none',       quote:'I choose four',                            count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:4,  name:'Cartman',          value:4,  ability:'none',       quote:'Respect My Authority!',                   count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:5,  name:'Zinedine Zidane',       value:5,  ability:'none',       quote:'Ciao bella ciao!',                        count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:6,  name:'Bruce Lee',             value:6,  ability:'none',       quote:'Bee water my friend',                     count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:7,  name:'Ronaldo',               value:7,  ability:'see_own',    quote:'SUUUI ...your own card!!!',                count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:8,  name:'Leo',     value:8,  ability:'see_own',    quote:'check this out',                          count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:9,  name:'Snowden',               value:9,  ability:'see_others', quote:'They see everything..',                   count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:10, name:'Trump',                 value:10, ability:'see_others', quote:'Lets fuck up',                            count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:11, name:'Joker',                 value:11, ability:'swap',       quote:"Let's do some confusion.",                count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:12, name:'Hund',                  value:12, ability:'see_swap',   quote:'To the moon!',                            count:4, colors:['#4CAF50','#9C27B0','#2196F3','#FF9800'] },
  { nr:13, name:'Mr Hankey',             value:13, ability:'none',       quote:'shit happens.',                           count:2, colors:['#F44336','#F44336'] },
  { nr:14, name:'Titi',         value:0,  ability:'none',       quote:'Congratulations, you got me.',            count:1, colors:['#9E9E9E'] },
  { nr:15, name:'Katze',                 value:-1, ability:'none',       quote:'You lucky bastard.',                      count:1, colors:['#FFD700'] },
];

const IMAGE_FILES = {
  1:'01_Olli.png', 2:'02_tupac.jpg', 3:'03_arnold schwarzenegger.jpg',
  4:'04_Eric Cartman.png', 5:'05_zidane.jpg', 6:'06_bruce lee.jpg',
  7:'07_Ronaldo.jpeg', 8:'08_Leonardo DiCaprio.jpg', 9:'09_.jpg',
  10:'10_trump.jpg', 11:'11_joker.jpg', 12:'12_Hund.jpg',
  13:'13_MrHankey.jpg', 14:'14_Thierry Henry.jpeg', 15:'15_Katze.jpg',
};

function createDeck() {
  const deck = [];
  for (const def of CARD_DEFS) {
    for (let i = 0; i < def.count; i++) {
      const colorIndex = i % def.colors.length;
      deck.push({ ...def, color: def.colors[colorIndex], image: IMAGE_FILES[def.nr], uid: crypto.randomBytes(4).toString('hex') });
    }
  }
  return deck;
}

function shuffle(arr) {
  const a = [...arr];
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [a[i], a[j]] = [a[j], a[i]];
  }
  return a;
}

function genSessionId() {
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let id = '';
  for (let i = 0; i < 6; i++) id += chars[Math.floor(Math.random() * chars.length)];
  return id;
}

// ─── State ───────────────────────────────────────────────────────────────────
const sessions = {};
const wsMap = new Map(); // ws -> { playerId, sessionId }

function createSession(hostId, hostName, hostWs, gameMode) {
  let id;
  do { id = genSessionId(); } while (sessions[id]);
  const totalRounds = { single: 1, best_of_3: 3, best_of_5: 5, best_of_10: 10 }[gameMode] || 1;
  const session = {
    id, hostId, gameMode, totalRounds,
    players: [], deck: [], discardPile: [],
    phase: 'lobby', currentPlayerIndex: 0,
    drawnCard: null, abilityState: null,
    racingCard: null, racingTimer: null,
    endCalledBy: null, finalRoundLeft: 0,
    roundNumber: 1, matchScores: {}, roundScores: {},
  };
  sessions[id] = session;
  addPlayer(session, hostId, hostName, hostWs);
  return session;
}

function addPlayer(session, pid, name, ws) {
  session.players.push({ id: pid, name, ws, hand: [], knownCards: {}, peekCount: 0, peekDone: false, connected: true });
  session.matchScores[pid] = 0;
  session.roundScores[pid] = 0;
}

// ─── Messaging ───────────────────────────────────────────────────────────────
function send(ws, msg) {
  if (ws && ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(msg));
}

function broadcast(session, msg) {
  for (const p of session.players) send(p.ws, msg);
}

function cardView(card, hidden) {
  if (!card) return null;
  if (hidden) return { hidden: true, uid: card.uid };
  return { hidden: false, nr: card.nr, name: card.name, value: card.value, ability: card.ability, quote: card.quote, image: card.image, color: card.color, uid: card.uid };
}

function sendState(session) {
  for (const viewer of session.players) {
    const myIndex = session.players.indexOf(viewer);
    const players = session.players.map((p, pi) => ({
      id: p.id, name: p.name, connected: p.connected, peekDone: p.peekDone,
      isMe: p.id === viewer.id,
      hand: p.hand.map((card, ci) => {
        const known = p.id === viewer.id && viewer.knownCards[ci];
        return cardView(card, !known);
      }),
    }));

    // Build ability state for this viewer
    let abilityForViewer = null;
    if (session.abilityState) {
      const as = session.abilityState;
      abilityForViewer = { type: as.type, activatedBy: as.activatedBy, step: as.step, waitingForSelection: as.waitingForSelection };
      if (as.activatedBy === viewer.id) {
        abilityForViewer.revealedCard = as.revealedCard ? cardView(as.revealedCard, false) : null;
        abilityForViewer.revealedCards = as.revealedCards ? as.revealedCards.map(r => ({ ...r, card: cardView(r.card, false) })) : null;
        abilityForViewer.selectedCards = as.selectedCards || [];
      }
    }

    const currentPlayer = session.players[session.currentPlayerIndex];
    const drawnCardView = (currentPlayer && currentPlayer.id === viewer.id && session.drawnCard)
      ? cardView(session.drawnCard, false) : null;

    send(viewer.ws, {
      type: 'state', phase: session.phase,
      myId: viewer.id, myIndex,
      isHost: viewer.id === session.hostId,
      players, currentPlayerIndex: session.currentPlayerIndex,
      currentPlayerId: currentPlayer?.id,
      deckSize: session.deck.length,
      discardTop: session.discardPile.length > 0 ? cardView(session.discardPile[session.discardPile.length - 1], false) : null,
      drawnCard: drawnCardView,
      abilityState: abilityForViewer,
      racingCard: session.racingCard ? cardView(session.racingCard, false) : null,
      endCalledBy: session.endCalledBy,
      finalRoundLeft: session.finalRoundLeft,
      gameMode: session.gameMode, roundNumber: session.roundNumber, totalRounds: session.totalRounds,
      matchScores: session.matchScores, roundScores: session.roundScores,
      sessionId: session.id,
    });
  }
}

// ─── Game Logic ───────────────────────────────────────────────────────────────
function refillDeck(session) {
  if (session.deck.length > 0) return;
  const top = session.discardPile.pop();
  session.deck = shuffle(session.discardPile);
  session.discardPile = top ? [top] : [];
}

function startGame(session) {
  const deck = shuffle(createDeck());
  session.deck = deck;
  session.discardPile = [session.deck.pop()];
  session.phase = 'peek';
  session.currentPlayerIndex = Math.floor(Math.random() * session.players.length);
  session.drawnCard = null;
  session.abilityState = null;
  session.endCalledBy = null;
  session.finalRoundLeft = 0;
  session.roundScores = {};
  for (const p of session.players) {
    p.hand = [session.deck.pop(), session.deck.pop(), session.deck.pop(), session.deck.pop()];
    p.knownCards = {};
    p.peekCount = 0;
    p.peekDone = false;
    session.roundScores[p.id] = 0;
  }
  sendState(session);
}

function handlePeek(session, playerId, cardIndex) {
  if (session.phase !== 'peek') return;
  const p = session.players.find(x => x.id === playerId);
  if (!p || p.peekDone) return;
  if (p.knownCards[cardIndex] || p.peekCount >= 2) return;
  p.knownCards[cardIndex] = true;
  p.peekCount++;
  if (p.peekCount >= 2) p.peekDone = true;
  checkAllPeeked(session);
  sendState(session);
}

function handlePeekDone(session, playerId) {
  if (session.phase !== 'peek') return;
  const p = session.players.find(x => x.id === playerId);
  if (!p) return;
  p.peekDone = true;
  checkAllPeeked(session);
  sendState(session);
}

function checkAllPeeked(session) {
  if (session.players.every(p => p.peekDone)) session.phase = 'playing';
}

function handleCallEnd(session, playerId) {
  if (session.phase !== 'playing') return;
  const currentPlayer = session.players[session.currentPlayerIndex];
  if (!currentPlayer || currentPlayer.id !== playerId || session.drawnCard) return;
  if (session.endCalledBy) return;
  session.endCalledBy = playerId;
  session.finalRoundLeft = session.players.length - 1;
  broadcast(session, { type: 'toast', msg: `${currentPlayer.name} beendet das Spiel!`, color: '#ff9800' });
  advanceTurn(session);
}

function handleDraw(session, playerId) {
  if (session.phase !== 'playing') return;
  const cp = session.players[session.currentPlayerIndex];
  if (!cp || cp.id !== playerId || session.drawnCard) return;
  refillDeck(session);
  if (session.deck.length === 0) return;
  const card = session.deck.pop();
  session.drawnCard = card;
  if (card.ability !== 'none') {
    session.phase = 'ability';
    session.abilityState = { type: card.ability, activatedBy: playerId, drawnCard: card, step: 'select1', waitingForSelection: true, selectedCards: [], revealedCard: null, revealedCards: null };
  }
  sendState(session);
}

function handleKeep(session, playerId, handIndex) {
  if (session.phase !== 'playing' || !session.drawnCard) return;
  const cp = session.players[session.currentPlayerIndex];
  if (!cp || cp.id !== playerId) return;
  if (handIndex < 0 || handIndex >= cp.hand.length) return;
  const replaced = cp.hand[handIndex];
  cp.hand[handIndex] = session.drawnCard;
  cp.knownCards[handIndex] = true;
  session.drawnCard = null;
  placeOnDiscard(session, replaced);
  startRacing(session);
}

function handleDiscardDrawn(session, playerId) {
  if (session.phase !== 'playing' || !session.drawnCard) return;
  const cp = session.players[session.currentPlayerIndex];
  if (!cp || cp.id !== playerId) return;
  const card = session.drawnCard;
  session.drawnCard = null;
  placeOnDiscard(session, card);
  startRacing(session);
}

function placeOnDiscard(session, card) {
  session.discardPile.push(card);
}

function startRacing(session) {
  session.racingCard = session.discardPile[session.discardPile.length - 1];
  session.phase = 'racing';
  if (session.racingTimer) clearTimeout(session.racingTimer);
  session.racingTimer = setTimeout(() => {
    if (session.phase === 'racing') {
      session.racingCard = null;
      session.phase = 'playing';
      advanceTurn(session);
    }
  }, 3000);
  sendState(session);
}

function handleRaceDiscard(session, playerId, cardIndex) {
  if (session.phase !== 'racing' || !session.racingCard) return;
  const p = session.players.find(x => x.id === playerId);
  if (!p || cardIndex < 0 || cardIndex >= p.hand.length) return;
  const card = p.hand[cardIndex];
  if (!card) return;

  if (card.value === session.racingCard.value) {
    // Success
    if (session.racingTimer) clearTimeout(session.racingTimer);
    session.racingTimer = null;
    const removed = p.hand.splice(cardIndex, 1)[0];
    // Shift known cards
    const newKnown = {};
    for (const [k, v] of Object.entries(p.knownCards)) {
      const ki = parseInt(k);
      if (ki < cardIndex) newKnown[ki] = v;
      else if (ki > cardIndex) newKnown[ki - 1] = v;
    }
    p.knownCards = newKnown;
    placeOnDiscard(session, removed);
    session.racingCard = null;
    // This player goes next
    session.currentPlayerIndex = session.players.indexOf(p);
    session.phase = 'playing';
    broadcast(session, { type: 'toast', msg: `${p.name} schnappt sich die Karte!`, color: '#4CAF50' });
    sendState(session);
  } else {
    // Penalty card
    refillDeck(session);
    if (session.deck.length > 0) {
      const penalty = session.deck.pop();
      p.hand.push(penalty);
      // Don't add to knownCards - player doesn't see it
    }
    send(p.ws, { type: 'toast', msg: 'Falsche Karte! Strafkarte erhalten.', color: '#f44336' });
    sendState(session);
  }
}

// ─── Ability Resolution ───────────────────────────────────────────────────────
function handleAbilityAction(session, playerId, data) {
  if (session.phase !== 'ability') return;
  const as = session.abilityState;
  if (!as || as.activatedBy !== playerId) return;

  if (as.type === 'see_own') {
    if (as.waitingForSelection) {
      const p = session.players.find(x => x.id === playerId);
      const idx = data.cardIndex;
      if (idx < 0 || idx >= p.hand.length) return;
      as.revealedCard = p.hand[idx];
      as.selectedCards = [{ playerId, cardIndex: idx }];
      as.waitingForSelection = false;
      p.knownCards[idx] = true;
      sendState(session);
    } else {
      // Player clicked "OK", done
      finishAbility(session, playerId);
    }
  }

  if (as.type === 'see_others') {
    if (as.waitingForSelection) {
      const tp = session.players.find(x => x.id === data.targetPlayerId);
      if (!tp || tp.id === playerId) return;
      const idx = data.cardIndex;
      if (idx < 0 || idx >= tp.hand.length) return;
      as.revealedCard = tp.hand[idx];
      as.selectedCards = [{ playerId: data.targetPlayerId, cardIndex: idx }];
      as.waitingForSelection = false;
      sendState(session);
    } else {
      finishAbility(session, playerId);
    }
  }

  if (as.type === 'swap') {
    if (as.step === 'select1' && data.card1) {
      as.selectedCards = [data.card1];
      as.step = 'select2';
      sendState(session);
    } else if (as.step === 'select2' && data.card2) {
      const c1 = as.selectedCards[0];
      const c2 = data.card2;
      doSwap(session, c1, c2, false);
      as.waitingForSelection = false;
      session.abilityState = null;
      session.phase = 'playing';
      broadcast(session, { type: 'toast', msg: 'Karten getauscht!', color: '#9C27B0' });
      sendState(session);
    }
  }

  if (as.type === 'see_swap') {
    if (as.step === 'select1' && data.card1) {
      as.selectedCards = [data.card1];
      as.step = 'select2';
      sendState(session);
    } else if (as.step === 'select2' && data.card2) {
      const c1 = as.selectedCards[0];
      const c2 = data.card2;
      const p1 = session.players.find(x => x.id === c1.playerId);
      const p2 = session.players.find(x => x.id === c2.playerId);
      if (!p1 || !p2) return;
      as.revealedCards = [
        { playerId: c1.playerId, cardIndex: c1.cardIndex, card: p1.hand[c1.cardIndex] },
        { playerId: c2.playerId, cardIndex: c2.cardIndex, card: p2.hand[c2.cardIndex] },
      ];
      as.selectedCards = [c1, c2];
      as.step = 'decide_swap';
      as.waitingForSelection = false;
      sendState(session);
    } else if (as.step === 'decide_swap') {
      if (data.doSwap) {
        doSwap(session, as.selectedCards[0], as.selectedCards[1], true);
        broadcast(session, { type: 'toast', msg: 'Karten gesehen & getauscht!', color: '#9C27B0' });
      }
      session.abilityState = null;
      session.phase = 'playing';
      sendState(session);
    }
  }
}

function doSwap(session, c1, c2, seen) {
  const p1 = session.players.find(x => x.id === c1.playerId);
  const p2 = session.players.find(x => x.id === c2.playerId);
  if (!p1 || !p2) return;
  const temp = p1.hand[c1.cardIndex];
  p1.hand[c1.cardIndex] = p2.hand[c2.cardIndex];
  p2.hand[c2.cardIndex] = temp;
  // Clear known state for swapped positions (positions are uncertain now unless seen)
  if (p1 === p2) {
    const t = p1.knownCards[c1.cardIndex];
    p1.knownCards[c1.cardIndex] = p1.knownCards[c2.cardIndex];
    p1.knownCards[c2.cardIndex] = t;
  } else {
    delete p1.knownCards[c1.cardIndex];
    delete p2.knownCards[c2.cardIndex];
  }
}

function finishAbility(session, playerId) {
  session.abilityState = null;
  session.phase = 'playing';
  sendState(session);
}

// ─── Turn Advancement ─────────────────────────────────────────────────────────
function advanceTurn(session) {
  const n = session.players.length;
  session.currentPlayerIndex = (session.currentPlayerIndex + 1) % n;

  if (session.endCalledBy) {
    session.finalRoundLeft--;
    if (session.finalRoundLeft <= 0) {
      endRound(session);
      return;
    }
  }
  sendState(session);
}

function endRound(session) {
  session.phase = 'scoring';
  if (session.racingTimer) { clearTimeout(session.racingTimer); session.racingTimer = null; }
  session.racingCard = null;
  session.drawnCard = null;
  session.abilityState = null;

  // Calculate scores
  const scores = {};
  let minScore = Infinity;
  for (const p of session.players) {
    const sum = p.hand.reduce((acc, c) => acc + (c ? c.value : 0), 0);
    scores[p.id] = sum;
    if (sum < minScore) minScore = sum;
  }

  // Penalties
  const callerPenalty = session.endCalledBy;
  const callerScore = scores[callerPenalty];
  if (callerScore !== minScore) scores[callerPenalty] = (scores[callerPenalty] || 0) + 30;
  for (const p of session.players) {
    if (scores[p.id] > 7 && p.id !== callerPenalty) {
      scores[p.id] = (scores[p.id] || 0) + 30;
    }
  }

  session.roundScores = scores;
  for (const p of session.players) session.matchScores[p.id] = (session.matchScores[p.id] || 0) + (scores[p.id] || 0);

  // Reveal all hands
  for (const p of session.players) {
    for (let i = 0; i < p.hand.length; i++) p.knownCards[i] = true;
  }

  sendState(session);
}

function startNextRound(session) {
  if (session.roundNumber >= session.totalRounds) {
    session.phase = 'done';
    sendState(session);
    return;
  }
  session.roundNumber++;
  startGame(session);
}

// ─── WebSocket Handler ────────────────────────────────────────────────────────
wss.on('connection', ws => {
  ws.on('message', raw => {
    let msg;
    try { msg = JSON.parse(raw); } catch { return; }
    const { type } = msg;

    if (type === 'create') {
      const { playerId, playerName, gameMode } = msg;
      const session = createSession(playerId, playerName, ws, gameMode || 'single');
      wsMap.set(ws, { playerId, sessionId: session.id });
      send(ws, { type: 'created', sessionId: session.id });
      sendState(session);
      return;
    }

    if (type === 'join') {
      const { playerId, playerName, sessionId } = msg;
      const session = sessions[sessionId];
      if (!session) { send(ws, { type: 'error', msg: 'Session nicht gefunden.' }); return; }
      if (session.phase !== 'lobby') { send(ws, { type: 'error', msg: 'Spiel bereits gestartet.' }); return; }
      if (session.players.length >= 4) { send(ws, { type: 'error', msg: 'Session ist voll (max. 4 Spieler).' }); return; }
      if (session.players.find(p => p.id === playerId)) { send(ws, { type: 'error', msg: 'Du bist bereits in dieser Session.' }); return; }
      addPlayer(session, playerId, playerName, ws);
      wsMap.set(ws, { playerId, sessionId });
      send(ws, { type: 'joined', sessionId });
      broadcast(session, { type: 'toast', msg: `${playerName} ist beigetreten!`, color: '#4CAF50' });
      sendState(session);
      return;
    }

    const info = wsMap.get(ws);
    if (!info) return;
    const { playerId, sessionId } = info;
    const session = sessions[sessionId];
    if (!session) return;

    switch (type) {
      case 'start':
        if (playerId === session.hostId && session.phase === 'lobby' && session.players.length >= 2) startGame(session);
        break;
      case 'peek':
        handlePeek(session, playerId, msg.cardIndex);
        break;
      case 'peek_done':
        handlePeekDone(session, playerId);
        break;
      case 'call_end':
        handleCallEnd(session, playerId);
        break;
      case 'draw':
        handleDraw(session, playerId);
        break;
      case 'keep':
        handleKeep(session, playerId, msg.handIndex);
        break;
      case 'discard_drawn':
        handleDiscardDrawn(session, playerId);
        break;
      case 'race':
        handleRaceDiscard(session, playerId, msg.cardIndex);
        break;
      case 'ability':
        handleAbilityAction(session, playerId, msg);
        break;
      case 'next_round':
        if (session.phase === 'scoring' || session.phase === 'done') startNextRound(session);
        break;
    }
  });

  ws.on('close', () => {
    const info = wsMap.get(ws);
    wsMap.delete(ws);
    if (!info) return;
    const session = sessions[info.sessionId];
    if (!session) return;
    const p = session.players.find(x => x.id === info.playerId);
    if (p) {
      p.connected = false;
      broadcast(session, { type: 'toast', msg: `${p.name} hat die Verbindung getrennt.`, color: '#ff9800' });
      sendState(session);
    }
  });
});

const PORT = process.env.PORT || 3000;
server.listen(PORT, () => console.log(`Karma running on http://localhost:${PORT}`));
