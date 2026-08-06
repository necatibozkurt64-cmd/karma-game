#!/usr/bin/env python3
"""Karma card game server — Python asyncio + websockets."""
import asyncio
import json
import os
import random
import secrets
import string
from http.server import SimpleHTTPRequestHandler, HTTPServer
from pathlib import Path
import threading
import urllib.parse
import mimetypes

# ── Card Definitions ──────────────────────────────────────────────────────────
CARD_DEFS = [
    dict(nr=1,  name='Olli',                  value=1,  ability='none',       quote='Eier, we need Eier',                       count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=2,  name='Tupac',                  value=2,  ability='none',       quote='Chill, Alter, es kommen auch gute Zeiten.',  count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=3,  name='Arnold',  value=3,  ability='none',       quote='I choose four',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=4,  name='Cartman',           value=4,  ability='none',       quote='Respect My Authority!',                    count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=5,  name='Zinedine Zidane',        value=5,  ability='none',       quote='Ciao bella ciao!',                         count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=6,  name='Bruce Lee',              value=6,  ability='none',       quote='Bee water my friend',                      count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=7,  name='Ronaldo',                value=7,  ability='see_own',    quote='SUUUI ...your own card!!!',                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=8,  name='Leo',      value=8,  ability='see_own',    quote='check this out',                           count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=9,  name='Snowden',                value=9,  ability='see_others', quote='They see everything..',                    count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=10, name='Trump',                  value=10, ability='see_others', quote='Lets fuck up',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=11, name='Joker',                  value=11, ability='swap',       quote="Let's do some confusion.",                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=12, name='Hund',                   value=12, ability='see_swap',   quote='To the moon!',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=13, name='Mr Hankey',              value=13, ability='none',       quote='shit happens.',                            count=2,  colors=['#F44336','#F44336']),
    dict(nr=14, name='Titi',          value=0,  ability='none',       quote='Congratulations, you got me.',             count=1,  colors=['#9E9E9E']),
    dict(nr=15, name='Katze',                  value=-1, ability='none',       quote='You lucky bastard.',                       count=1,  colors=['#FFD700']),
]
IMAGE_FILES = {
    1:'01_Olli.png', 2:'02_tupac.jpg', 3:'03_arnold schwarzenegger.jpg',
    4:'04_Eric Cartman.png', 5:'05_zidane.jpg', 6:'06_bruce lee.jpg',
    7:'07_Ronaldo.jpeg', 8:'08_Leonardo DiCaprio.jpg', 9:'09_snowden.jpg',
    10:'10_trump.jpg', 11:'11_joker.jpg', 12:'12_Hund.jpg',
    13:'13_MrHankey.jpg', 14:'14_Thierry Henry.jpeg', 15:'15_Katze.jpg',
}
IMAGES_DIR = Path(__file__).parent / 'public' / 'Bilder'

# Karten werden immer nur temporär aufgedeckt – danach wieder verdeckt.
REVEAL_SECONDS = 6

import re
def _to_snake(name):
    return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()

def make_deck():
    deck = []
    for d in CARD_DEFS:
        for i in range(d['count']):
            card = dict(d)
            card['color'] = d['colors'][i % len(d['colors'])]
            card['image'] = IMAGE_FILES[d['nr']]
            card['uid'] = secrets.token_hex(4)
            del card['colors']
            del card['count']
            deck.append(card)
    random.shuffle(deck)
    return deck

def gen_session_id():
    chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'
    return ''.join(random.choices(chars, k=6))

# ── State ─────────────────────────────────────────────────────────────────────
sessions = {}   # id -> session dict
ws_map = {}     # ws -> {player_id, session_id}

def new_session(host_id, host_name, host_ws, game_mode):
    sid = gen_session_id()
    while sid in sessions:
        sid = gen_session_id()
    rounds = {'single':1,'best_of_3':3,'best_of_5':5,'best_of_10':10}.get(game_mode, 1)
    s = dict(
        id=sid, host_id=host_id, game_mode=game_mode, total_rounds=rounds,
        players=[], deck=[], discard_pile=[],
        phase='lobby', current_player_index=0,
        drawn_card=None, ability_state=None,
        racing_card=None, racing_task=None,
        end_called_by=None, final_round_left=0,
        round_number=1, match_scores={}, round_scores={},
        score_breakdown={},
        reveal_all=False, ability_reveal_task=None,
    )
    sessions[sid] = s
    _add_player(s, host_id, host_name, host_ws)
    return s

def _add_player(s, pid, name, ws):
    s['players'].append(dict(
        id=pid, name=name, ws=ws, hand=[], connected=True,
        revealed={}, reveal_until=0.0, reveal_task=None,
        peek_selection=[], peek_revealing=False, peek_done=False,
    ))
    s['match_scores'][pid] = 0
    s['round_scores'][pid] = 0

# ── Temporäre Karten-Enthüllung ───────────────────────────────────────────────
def _now():
    return asyncio.get_event_loop().time()

def _cancel_reveal(p):
    if p.get('reveal_task'):
        p['reveal_task'].cancel()
    p['reveal_task'] = None
    p['revealed'] = {}
    p['reveal_until'] = 0.0

async def reveal_to_player(s, p, indices, seconds=REVEAL_SECONDS, on_expire=None):
    """Deckt Karten NUR für diesen Spieler auf – danach automatisch wieder verdeckt."""
    if p.get('reveal_task'):
        p['reveal_task'].cancel()
    p['revealed'] = {str(i): True for i in indices}
    p['reveal_until'] = _now() + seconds
    p['reveal_task'] = asyncio.ensure_future(_expire_player_reveal(s, p, seconds, on_expire))

async def _expire_player_reveal(s, p, seconds, on_expire):
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    p['revealed'] = {}
    p['reveal_until'] = 0.0
    p['reveal_task'] = None
    if on_expire:
        on_expire(s, p)
    await send_state(s)

def _cancel_ability_reveal(s):
    if s.get('ability_reveal_task'):
        s['ability_reveal_task'].cancel()
    s['ability_reveal_task'] = None

def start_ability_reveal(s, a, seconds=REVEAL_SECONDS):
    _cancel_ability_reveal(s)
    a['reveal_until'] = _now() + seconds
    s['ability_reveal_task'] = asyncio.ensure_future(_expire_ability_reveal(s, a, seconds))

async def _expire_ability_reveal(s, a, seconds):
    try:
        await asyncio.sleep(seconds)
    except asyncio.CancelledError:
        return
    s['ability_reveal_task'] = None
    if s.get('ability_state') is not a:
        return
    a['reveal_until'] = 0.0
    if a['type'] in ('see_own', 'see_others'):
        # Reines Ansehen – Fähigkeit ist damit erledigt.
        s['ability_state'] = None
        s['phase'] = 'playing'
    else:
        # see_swap: Karten wieder verdecken, Entscheidung bleibt offen.
        a['revealed_cards'] = None
    await send_state(s)

# ── Messaging ─────────────────────────────────────────────────────────────────
async def send(ws, msg):
    try:
        await ws.send(json.dumps(msg))
    except Exception:
        pass

async def broadcast(s, msg):
    for p in s['players']:
        await send(p['ws'], msg)

def card_view(card, hidden):
    if not card:
        return None
    if hidden:
        return {'hidden': True, 'uid': card['uid']}
    return {k: card[k] for k in ('hidden','nr','name','value','ability','quote','image','color','uid') if k != 'hidden'} | {'hidden': False}

async def send_state(s):
    now = _now()
    for viewer in s['players']:
        vi = s['players'].index(viewer)
        players_view = []
        for p in s['players']:
            hand_view = []
            for i, card in enumerate(p['hand']):
                shown = s.get('reveal_all') or (p['id'] == viewer['id'] and viewer['revealed'].get(str(i)))
                hand_view.append(card_view(card, not shown))
            players_view.append(dict(
                id=p['id'], name=p['name'], connected=p['connected'],
                peekDone=p['peek_done'], isMe=(p['id'] == viewer['id']),
                hand=hand_view,
            ))

        ability_for_viewer = None
        if s['ability_state']:
            a = s['ability_state']
            ability_for_viewer = dict(type=a['type'], activatedBy=a['activated_by'], step=a.get('step'), waitingForSelection=a.get('waiting_for_selection'))
            if a['activated_by'] == viewer['id']:
                reveal_left = max(0.0, a.get('reveal_until', 0.0) - now)
                ability_for_viewer['revealSecondsLeft'] = round(reveal_left, 1)
                ability_for_viewer['revealedCard'] = card_view(a.get('revealed_card'), False) if (a.get('revealed_card') and reveal_left > 0) else None
                ability_for_viewer['revealedCards'] = [{'playerId': r['player_id'], 'cardIndex': r['card_index'], 'card': card_view(r['card'], False)} for r in a['revealed_cards']] if a.get('revealed_cards') else None
                ability_for_viewer['selectedCards'] = [{'playerId': x['player_id'], 'cardIndex': x['card_index']} for x in a.get('selected_cards', [])]

        cp = s['players'][s['current_player_index']] if s['players'] else None
        drawn_view = None
        if cp and cp['id'] == viewer['id'] and s['drawn_card']:
            drawn_view = card_view(s['drawn_card'], False)

        discard_top = card_view(s['discard_pile'][-1], False) if s['discard_pile'] else None

        await send(viewer['ws'], dict(
            type='state', phase=s['phase'],
            myId=viewer['id'], myIndex=vi,
            isHost=(viewer['id'] == s['host_id']),
            players=players_view,
            currentPlayerIndex=s['current_player_index'],
            currentPlayerId=cp['id'] if cp else None,
            deckSize=len(s['deck']),
            discardTop=discard_top,
            drawnCard=drawn_view,
            abilityState=ability_for_viewer,
            racingCard=card_view(s['racing_card'], False) if s['racing_card'] else None,
            endCalledBy=s['end_called_by'],
            finalRoundLeft=s['final_round_left'],
            gameMode=s['game_mode'],
            roundNumber=s['round_number'],
            totalRounds=s['total_rounds'],
            matchScores=s['match_scores'],
            roundScores=s['round_scores'],
            scoreBreakdown=s.get('score_breakdown', {}),
            sessionId=s['id'],
            revealSecondsLeft=round(max(0.0, viewer['reveal_until'] - now), 1),
            revealTotalSeconds=REVEAL_SECONDS,
            myPeekSelection=list(viewer['peek_selection']),
            peekRevealing=viewer['peek_revealing'],
        ))

# ── Game Logic ────────────────────────────────────────────────────────────────
def refill_deck(s):
    if s['deck'] or len(s['discard_pile']) <= 1:
        return
    top = s['discard_pile'].pop()
    s['deck'] = s['discard_pile'][:]
    random.shuffle(s['deck'])
    s['discard_pile'] = [top]

async def start_game(s):
    s['deck'] = make_deck()
    s['discard_pile'] = [s['deck'].pop()]
    s['phase'] = 'peek'
    s['current_player_index'] = random.randrange(len(s['players']))
    s['drawn_card'] = None
    s['ability_state'] = None
    s['end_called_by'] = None
    s['final_round_left'] = 0
    s['reveal_all'] = False
    s['round_scores'] = {}
    _cancel_ability_reveal(s)
    for p in s['players']:
        p['hand'] = [s['deck'].pop() for _ in range(4)]
        _cancel_reveal(p)
        p['peek_selection'] = []
        p['peek_revealing'] = False
        p['peek_done'] = False
        s['round_scores'][p['id']] = 0
    await send_state(s)

def _finish_peek(s, p):
    p['peek_revealing'] = False
    p['peek_done'] = True
    _check_all_peeked(s)

async def handle_peek(s, pid, card_index):
    """Karte für die Sichtung an-/abwählen. Bei 2 Karten startet der 6-Sekunden-Timer."""
    if s['phase'] != 'peek':
        return
    p = next((x for x in s['players'] if x['id'] == pid), None)
    if not p or p['peek_done'] or p['peek_revealing']:
        return
    if card_index < 0 or card_index >= len(p['hand']):
        return
    sel = p['peek_selection']
    if card_index in sel:
        sel.remove(card_index)
    elif len(sel) < 2:
        sel.append(card_index)
    if len(sel) == 2:
        p['peek_revealing'] = True
        await reveal_to_player(s, p, sel, REVEAL_SECONDS, on_expire=_finish_peek)
    await send_state(s)

async def handle_peek_done(s, pid):
    """'Fertig' – deckt eine evtl. angefangene Auswahl noch kurz auf, sonst direkt beenden."""
    if s['phase'] != 'peek':
        return
    p = next((x for x in s['players'] if x['id'] == pid), None)
    if not p or p['peek_done'] or p['peek_revealing']:
        return
    if p['peek_selection']:
        p['peek_revealing'] = True
        await reveal_to_player(s, p, p['peek_selection'], REVEAL_SECONDS, on_expire=_finish_peek)
    else:
        p['peek_done'] = True
        _check_all_peeked(s)
    await send_state(s)

def _check_all_peeked(s):
    if all(p['peek_done'] for p in s['players']):
        s['phase'] = 'playing'

async def handle_call_end(s, pid):
    if s['phase'] != 'playing' or s['drawn_card'] or s['end_called_by']:
        return
    cp = s['players'][s['current_player_index']]
    if cp['id'] != pid:
        return
    s['end_called_by'] = pid
    s['final_round_left'] = len(s['players']) - 1
    await broadcast(s, dict(type='toast', msg=f"{cp['name']} beendet das Spiel!", color='#ff9800'))
    await advance_turn(s, count_final=False)

async def handle_draw(s, pid):
    if s['phase'] != 'playing' or s['drawn_card']:
        return
    cp = s['players'][s['current_player_index']]
    if cp['id'] != pid:
        return
    refill_deck(s)
    if not s['deck']:
        return
    card = s['deck'].pop()
    s['drawn_card'] = card
    await send_state(s)

async def handle_keep(s, pid, hand_index):
    if s['phase'] != 'playing' or not s['drawn_card']:
        return
    cp = s['players'][s['current_player_index']]
    if cp['id'] != pid or hand_index < 0 or hand_index >= len(cp['hand']):
        return
    replaced = cp['hand'][hand_index]
    cp['hand'][hand_index] = s['drawn_card']
    # Die gezogene Karte hat der Spieler bereits gesehen – sie bleibt verdeckt.
    cp['revealed'].pop(str(hand_index), None)
    s['drawn_card'] = None
    s['discard_pile'].append(replaced)
    await start_racing(s)

async def handle_discard_drawn(s, pid):
    if s['phase'] != 'playing' or not s['drawn_card']:
        return
    if s['players'][s['current_player_index']]['id'] != pid:
        return
    card = s['drawn_card']
    if card['ability'] != 'none':
        s['phase'] = 'ability'
        s['ability_state'] = dict(
            type=card['ability'], activated_by=pid, drawn_card=card,
            step='select1', waiting_for_selection=True,
            selected_cards=[], revealed_card=None, revealed_cards=None,
        )
        await send_state(s)
    else:
        s['drawn_card'] = None
        s['discard_pile'].append(card)
        await start_racing(s)

async def start_racing(s):
    s['racing_card'] = s['discard_pile'][-1]
    s['phase'] = 'racing'
    if s['racing_task']:
        s['racing_task'].cancel()
    s['racing_task'] = asyncio.ensure_future(_racing_timer(s))
    await send_state(s)

async def _racing_timer(s):
    await asyncio.sleep(3)
    if s['phase'] == 'racing':
        s['racing_card'] = None
        s['phase'] = 'playing'
        s['racing_task'] = None
        await advance_turn(s)

async def handle_race(s, pid, card_index):
    if s['phase'] != 'racing' or not s['racing_card']:
        return
    p = next((x for x in s['players'] if x['id'] == pid), None)
    if not p or card_index < 0 or card_index >= len(p['hand']):
        return
    card = p['hand'][card_index]
    if card['value'] == s['racing_card']['value']:
        if s['racing_task']:
            s['racing_task'].cancel()
            s['racing_task'] = None
        removed = p['hand'].pop(card_index)
        # Indizes der temporär sichtbaren Karten nachziehen
        new_revealed = {}
        for k, v in p['revealed'].items():
            ki = int(k)
            if ki < card_index:
                new_revealed[str(ki)] = v
            elif ki > card_index:
                new_revealed[str(ki - 1)] = v
        p['revealed'] = new_revealed
        s['discard_pile'].append(removed)
        s['racing_card'] = None
        s['current_player_index'] = s['players'].index(p)
        s['phase'] = 'playing'
        await broadcast(s, dict(type='toast', msg=f"{p['name']} schnappt sich die Karte!", color='#4CAF50'))
        await send_state(s)
    else:
        refill_deck(s)
        if s['deck']:
            penalty = s['deck'].pop()
            p['hand'].append(penalty)
        await send(p['ws'], dict(type='toast', msg='Falsche Karte! Strafkarte erhalten.', color='#f44336'))
        await send_state(s)

# ── Ability Resolution ────────────────────────────────────────────────────────
async def handle_ability(s, pid, data):
    if s['phase'] != 'ability':
        return
    a = s['ability_state']
    if not a or a['activated_by'] != pid:
        return

    t = a['type']

    def norm_card_ref(ref):
        # Accept both camelCase (from frontend) and snake_case
        if not ref:
            return None
        return {'player_id': ref.get('playerId', ref.get('player_id')), 'card_index': ref.get('cardIndex', ref.get('card_index', -1))}

    if t == 'see_own':
        if a['waiting_for_selection']:
            p = next(x for x in s['players'] if x['id'] == pid)
            idx = data.get('cardIndex', data.get('card_index', -1))
            if idx < 0 or idx >= len(p['hand']):
                return
            a['revealed_card'] = p['hand'][idx]
            a['selected_cards'] = [{'player_id': pid, 'card_index': idx}]
            a['waiting_for_selection'] = False
            start_ability_reveal(s, a)
            await send_state(s)
        else:
            _cancel_ability_reveal(s)
            s['discard_pile'].append(a['drawn_card'])
            s['drawn_card'] = None
            s['ability_state'] = None
            await start_racing(s)

    elif t == 'see_others':
        if a['waiting_for_selection']:
            tpid = data.get('targetPlayerId', data.get('target_player_id'))
            tp = next((x for x in s['players'] if x['id'] == tpid), None)
            if not tp or tp['id'] == pid:
                return
            idx = data.get('cardIndex', data.get('card_index', -1))
            if idx < 0 or idx >= len(tp['hand']):
                return
            a['revealed_card'] = tp['hand'][idx]
            a['selected_cards'] = [{'player_id': tp['id'], 'card_index': idx}]
            a['waiting_for_selection'] = False
            start_ability_reveal(s, a)
            await send_state(s)
        else:
            _cancel_ability_reveal(s)
            s['discard_pile'].append(a['drawn_card'])
            s['drawn_card'] = None
            s['ability_state'] = None
            await start_racing(s)

    elif t == 'swap':
        if a['step'] == 'select1':
            c1 = norm_card_ref(data.get('card1'))
            if c1:
                a['selected_cards'] = [c1]
                a['step'] = 'select2'
                await send_state(s)
        elif a['step'] == 'select2':
            c2 = norm_card_ref(data.get('card2'))
            if c2:
                c1, = a['selected_cards']
                _do_swap(s, c1, c2)
                s['discard_pile'].append(a['drawn_card'])
                s['drawn_card'] = None
                _cancel_ability_reveal(s)
                s['ability_state'] = None
                await broadcast(s, dict(type='toast', msg='Karten getauscht!', color='#9C27B0'))
                await start_racing(s)

    elif t == 'see_swap':
        if a['step'] == 'select1':
            c1 = norm_card_ref(data.get('card1'))
            if c1:
                a['selected_cards'] = [c1]
                a['step'] = 'select2'
                await send_state(s)
        elif a['step'] == 'select2':
            c2 = norm_card_ref(data.get('card2'))
            if c2:
                c1, = a['selected_cards']
                p1 = next(x for x in s['players'] if x['id'] == c1['player_id'])
                p2 = next(x for x in s['players'] if x['id'] == c2['player_id'])
                a['revealed_cards'] = [
                    {'player_id': c1['player_id'], 'card_index': c1['card_index'], 'card': p1['hand'][c1['card_index']]},
                    {'player_id': c2['player_id'], 'card_index': c2['card_index'], 'card': p2['hand'][c2['card_index']]},
                ]
                a['selected_cards'] = [c1, c2]
                a['step'] = 'decide_swap'
                a['waiting_for_selection'] = False
                start_ability_reveal(s, a)
                await send_state(s)
        elif a['step'] == 'decide_swap':
            if data.get('doSwap', data.get('do_swap')):
                c1, c2 = a['selected_cards']
                _do_swap(s, c1, c2)
                await broadcast(s, dict(type='toast', msg='Karten gesehen & getauscht!', color='#9C27B0'))
            s['discard_pile'].append(a['drawn_card'])
            s['drawn_card'] = None
            _cancel_ability_reveal(s)
            s['ability_state'] = None
            await start_racing(s)

def _do_swap(s, c1, c2):
    p1 = next(x for x in s['players'] if x['id'] == c1['player_id'])
    p2 = next(x for x in s['players'] if x['id'] == c2['player_id'])
    i1, i2 = c1['card_index'], c2['card_index']
    p1['hand'][i1], p2['hand'][i2] = p2['hand'][i2], p1['hand'][i1]
    # Getauschte Positionen sind nicht mehr bekannt – niemals dauerhaft sichtbar lassen.
    p1['revealed'].pop(str(i1), None)
    p2['revealed'].pop(str(i2), None)

async def advance_turn(s, count_final=True):
    n = len(s['players'])
    s['current_player_index'] = (s['current_player_index'] + 1) % n
    if s['end_called_by'] and count_final:
        s['final_round_left'] -= 1
        if s['final_round_left'] <= 0:
            await end_round(s)
            return
    await send_state(s)

async def end_round(s):
    s['phase'] = 'scoring'
    if s['racing_task']:
        s['racing_task'].cancel()
        s['racing_task'] = None
    _cancel_ability_reveal(s)
    for p in s['players']:
        _cancel_reveal(p)
    s['racing_card'] = None
    s['drawn_card'] = None
    s['ability_state'] = None

    scores = {}
    score_breakdown = {}
    for p in s['players']:
        card_total = sum(c['value'] for c in p['hand'] if c)
        scores[p['id']] = card_total
        score_breakdown[p['id']] = {
            'cards': [c['value'] for c in p['hand'] if c],
            'card_total': card_total,
            'penalties': []
        }

    min_score = min(scores.values())
    caller = s['end_called_by']
    if caller and scores.get(caller, 0) != min_score:
        penalty = 30
        scores[caller] = scores.get(caller, 0) + penalty
        score_breakdown[caller]['penalties'].append({
            'amount': penalty,
            'reason': 'Spiel beendet aber nicht gewonnen: +30 Strafpunkte'
        })
    for p in s['players']:
        if p['id'] != caller and scores.get(p['id'], 0) > 7:
            penalty = 30
            scores[p['id']] = scores.get(p['id'], 0) + penalty
            score_breakdown[p['id']]['penalties'].append({
                'amount': penalty,
                'reason': 'Mehr als 7 Punkte in einer verlorenen Runde: +30 Strafpunkte'
            })

    s['round_scores'] = scores
    s['score_breakdown'] = score_breakdown
    for pid, sc in scores.items():
        s['match_scores'][pid] = s['match_scores'].get(pid, 0) + sc

    # Bei der Wertung werden alle Hände offengelegt.
    s['reveal_all'] = True

    await send_state(s)

async def start_next_round(s):
    if s['round_number'] >= s['total_rounds']:
        s['phase'] = 'done'
        await send_state(s)
        return
    s['round_number'] += 1
    await start_game(s)

# ── WebSocket Server ──────────────────────────────────────────────────────────
async def ws_handler(ws):
    ws_map[id(ws)] = {'ws': ws}
    try:
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                continue
            await dispatch(ws, msg)
    except Exception:
        pass
    finally:
        info = ws_map.pop(id(ws), None)
        if info and info.get('session_id'):
            s = sessions.get(info['session_id'])
            if s:
                p = next((x for x in s['players'] if x['id'] == info.get('player_id')), None)
                if p:
                    p['connected'] = False
                    await broadcast(s, dict(type='toast', msg=f"{p['name']} hat die Verbindung getrennt.", color='#ff9800'))
                    await send_state(s)

async def dispatch(ws, msg):
    t = msg.get('type')

    def g(key, alt=None):
        return msg.get(key, msg.get(alt or key))

    if t == 'create':
        pid  = g('playerId', 'player_id')
        name = g('playerName', 'player_name')
        mode = g('gameMode', 'game_mode') or 'single'
        s = new_session(pid, name, ws, mode)
        ws_map[id(ws)].update(player_id=pid, session_id=s['id'])
        await send(ws, dict(type='created', sessionId=s['id']))
        await send_state(s)
        return

    if t == 'join':
        pid  = g('playerId', 'player_id')
        name = g('playerName', 'player_name')
        sid  = (g('sessionId', 'session_id') or '').upper()
        s = sessions.get(sid)
        if not s:
            await send(ws, dict(type='error', msg='Session nicht gefunden.')); return
        if s['phase'] != 'lobby':
            await send(ws, dict(type='error', msg='Spiel bereits gestartet.')); return
        if len(s['players']) >= 4:
            await send(ws, dict(type='error', msg='Session ist voll (max. 4 Spieler).')); return
        if any(p['id'] == pid for p in s['players']):
            await send(ws, dict(type='error', msg='Bereits in der Session.')); return
        _add_player(s, pid, name, ws)
        ws_map[id(ws)].update(player_id=pid, session_id=sid)
        await send(ws, dict(type='joined', sessionId=sid))
        await broadcast(s, dict(type='toast', msg=f'{name} ist beigetreten!', color='#4CAF50'))
        await send_state(s)
        return

    info = ws_map.get(id(ws), {})
    pid = info.get('player_id')
    s = sessions.get(info.get('session_id'))
    if not s or not pid:
        return

    def gi(key):
        """Get integer value, accepting both camelCase and snake_case."""
        val = msg.get(key, msg.get(_to_snake(key), -1))
        return int(val) if val is not None else -1

    if t == 'start':
        if pid == s['host_id'] and s['phase'] == 'lobby' and len(s['players']) >= 2:
            await start_game(s)
    elif t == 'peek':
        await handle_peek(s, pid, gi('cardIndex'))
    elif t == 'peek_done':
        await handle_peek_done(s, pid)
    elif t == 'call_end':
        await handle_call_end(s, pid)
    elif t == 'draw':
        await handle_draw(s, pid)
    elif t == 'keep':
        await handle_keep(s, pid, gi('handIndex'))
    elif t == 'discard_drawn':
        await handle_discard_drawn(s, pid)
    elif t == 'race':
        await handle_race(s, pid, gi('cardIndex'))
    elif t == 'ability':
        await handle_ability(s, pid, msg)
    elif t == 'next_round':
        if s['phase'] in ('scoring', 'done'):
            await start_next_round(s)

# ── HTTP Server for static files ───────────────────────────────────────────────
PUBLIC_DIR = Path(__file__).parent / 'public'

# ── HTTP static file server ────────────────────────────────────────────────────
class KarmaHTTPHandler(SimpleHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urllib.parse.unquote(self.path.split('?')[0])
        if path.startswith('/images/'):
            fpath = IMAGES_DIR / path[len('/images/'):]
        else:
            fpath = PUBLIC_DIR / path.lstrip('/')
            if fpath.is_dir():
                fpath = fpath / 'index.html'
        if fpath.exists():
            data = fpath.read_bytes()
            mime, _ = mimetypes.guess_type(str(fpath))
            self.send_response(200)
            self.send_header('Content-Type', mime or 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
        else:
            self.send_response(404)
            self.end_headers()

    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()

def run_http(port):
    HTTPServer(('', port), KarmaHTTPHandler).serve_forever()

# ── Main ───────────────────────────────────────────────────────────────────────
async def main():
    import websockets
    http_port = int(os.environ.get('PORT', 3000))
    ws_port   = int(os.environ.get('WS_PORT', http_port + 1))

    threading.Thread(target=run_http, args=(http_port,), daemon=True).start()
    print(f'HTTP → http://localhost:{http_port}')
    print(f'WS   → ws://localhost:{ws_port}')

    async with websockets.serve(ws_handler, '', ws_port):
        print('Karma ready.')
        await asyncio.Future()

if __name__ == '__main__':
    asyncio.run(main())
