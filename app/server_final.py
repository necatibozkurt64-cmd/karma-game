#!/usr/bin/env python3
"""Karma card game server — aiohttp (HTTP + WebSocket on same port)."""
import asyncio
import json
import os
import random
import secrets
import string
from pathlib import Path
import mimetypes
import re
from aiohttp import web

# ── Card Definitions ──────────────────────────────────────────────────────────
CARD_DEFS = [
    dict(nr=1,  name='Olli',                  value=1,  ability='none',       quote='Eier, we need Eier',                       count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=2,  name='Tupac',                  value=2,  ability='none',       quote='Chill, Alter, es kommen auch gute Zeiten.',  count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=3,  name='Arnold',                 value=3,  ability='none',       quote='I choose four',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=4,  name='Cartman',                value=4,  ability='none',       quote='Respect My Authority!',                    count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=5,  name='Barbie',                 value=5,  ability='none',       quote='Ciao bella ciao!',                         count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=6,  name='Hawk Tuah Girl',         value=6,  ability='none',       quote='Bee water my friend',                      count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=7,  name='Ronaldo',                value=7,  ability='see_own',    quote='SUUUI ...your own card!!!',                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=8,  name='Leo',                     value=8,  ability='see_own',    quote='check this out',                           count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=9,  name='Penny',                  value=9,  ability='see_others', quote='They see everything..',                    count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=10, name='Merkel',                 value=10, ability='see_others', quote='Lets fuck up',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=11, name='Joker',                  value=11, ability='swap',       quote="Let's do some confusion.",                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=12, name='Hund',                   value=12, ability='see_swap',   quote='To the moon!',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=13, name='Mr Hankey',              value=13, ability='none',       quote='shit happens.',                            count=2,  colors=['#F44336','#F44336']),
    dict(nr=14, name='Titi',                    value=0,  ability='none',       quote='Congratulations, you got me.',             count=1,  colors=['#9E9E9E']),
    dict(nr=15, name='Katze',                  value=-1, ability='none',       quote='You lucky bastard.',                       count=1,  colors=['#FFD700']),
]
IMAGE_FILES = {
    1:'01_Olli.png', 2:'02_tupac.jpg', 3:'03_arnold schwarzenegger.jpg',
    4:'04_Eric Cartman.png', 5:'fotos/05-barbie.webp', 6:'fotos/06-hawk-tuah.webp',
    7:'07_Ronaldo.jpeg', 8:'08_Leonardo DiCaprio.jpg', 9:'fotos/09-penny.webp',
    10:'fotos/10-merkel.webp', 11:'11_joker.jpg', 12:'12_Hund.jpg',
    13:'13_MrHankey.jpg', 14:'14_Thierry Henry.jpeg', 15:'15_Katze.jpg',
}
IMAGES_DIR = Path(__file__).parent / 'public' / 'Bilder'
PUBLIC_DIR = Path(__file__).parent / 'public'
REVEAL_SECONDS = 6
# Flugfenster: so lange sehen alle Spieler die Karten von Slot zu Slot fliegen,
# bevor die zeitkritische Schnapp-Phase startet. Muss zur Client-Animation passen
# (card-flying: 900ms + Nachglühen).
FLIGHT_SECONDS = 1.4
# Schnapp-Fenster. Gilt für die Zeitleiste am Tisch (#race-bar im Client) –
# gezielt länger als die alten 3 s des Vollbild-Overlays, weil jetzt kleine
# Tischkarten getroffen werden müssen statt großer Overlay-Karten.
RACE_SECONDS = 5.0
# So lange bleibt eine im Schnapp aufgedeckte Karte für alle sichtbar.
# Muss zur Client-Animation passen (Flip + Halten in animateRaceReveal).
RACE_REVEAL_SECONDS = 1.8
# Zeit für den Gewinner, eine eigene Karte als Ersatz in den frei gewordenen
# Gegner-Slot zu legen. Läuft sie ab, wählt der Server die letzte Karte.
RACE_GIVE_SECONDS = 12.0

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

sessions = {}
ws_map = {}

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
        # Schnapp-Phase: Deadline für die Zeitleiste, Spieler die ihren einen
        # Versuch schon verbraucht haben, und die offene Karten-Abgabe nach
        # einem Treffer auf eine gegnerische Karte.
        race_deadline=0.0, race_missed=set(),
        race_give=None, race_give_task=None,
        end_called_by=None, final_round_left=0,
        round_number=1, match_scores={}, round_scores={},
        score_breakdown={},
        reveal_all=False, ability_reveal_task=None,
        swap_flight=None, swap_flight_task=None,
    )
    sessions[sid] = s
    _add_player(s, host_id, host_name, host_ws)
    return s

def _add_player(s, pid, name, ws):
    # known_cards: uid → {value,nr,name,ability,quote,image,color}. Persistent per-player
    # knowledge of specific card identities (by uid). Populated when the player observes
    # a card (initial peek, see_own, see_others, see_swap, own drawn card kept). Cleared
    # for a uid when the card enters the discard pile (a re-shuffled draw is a fresh unknown).
    # Since uid is stable across slot swaps, knowledge naturally follows the card as it moves.
    s['players'].append(dict(
        id=pid, name=name, ws=ws, hand=[], connected=True,
        revealed={}, reveal_until=0.0, reveal_task=None,
        peek_selection=[], peek_revealing=False, peek_done=False,
        known_cards={},
    ))
    s['match_scores'][pid] = 0
    s['round_scores'][pid] = 0

def _now():
    return asyncio.get_event_loop().time()

def _cancel_reveal(p):
    if p.get('reveal_task'):
        p['reveal_task'].cancel()
    p['reveal_task'] = None
    p['revealed'] = {}
    p['reveal_until'] = 0.0

async def reveal_to_player(s, p, indices, seconds=REVEAL_SECONDS, on_expire=None):
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
    if s.get('ability_state') is not a or a.get('resolved'):
        return
    a['reveal_until'] = 0.0
    if a['type'] in ('see_own', 'see_others'):
        await _finish_peek_ability(s, a)
    else:
        # see_swap: nach 6 s verschwinden die Karten wieder, die Entscheidung
        # bleibt aber offen. Der Spieler tippt anschließend Tauschen/Nicht.
        a['revealed_cards'] = None
        await send_state(s)

def _cancel_swap_flight(s):
    if s.get('swap_flight_task'):
        s['swap_flight_task'].cancel()
    s['swap_flight_task'] = None
    s['swap_flight'] = None

def _flight_cards(s, *refs):
    """Slot-Referenzen mit uid anreichern – muss VOR dem Tausch aufgerufen werden,
    damit der Client weiss, welche Karte von wo nach wo fliegt."""
    out = []
    for r in refs:
        p = next((x for x in s['players'] if x['id'] == r['player_id']), None)
        if not p:
            return None
        i = r['card_index']
        if i < 0 or i >= len(p['hand']) or not p['hand'][i]:
            return None
        out.append({'playerId': p['id'], 'cardIndex': i, 'uid': p['hand'][i]['uid']})
    return out

async def start_swap_flight(s, cards, mode):
    """Kurzes Fenster, in dem alle Spieler die Karten wandern sehen. Erst danach
    startet die Schnapp-Phase – sonst konkurriert die Animation mit dem 3s-Timer.
    mode: 'swap' = Karten wechseln den Slot, 'stay' = Hund hat nicht getauscht."""
    _cancel_swap_flight(s)
    if not cards:
        await start_racing(s)
        return
    s['phase'] = 'swap_flight'
    s['swap_flight'] = dict(cards=cards, mode=mode)
    # Erst das Ereignis, dann der Zustand: der Client merkt sich das Ereignis und
    # animiert damit die Positionsänderung, die im folgenden State steckt.
    await broadcast(s, dict(type='swap_anim', cards=cards, mode=mode))
    await send_state(s)
    s['swap_flight_task'] = asyncio.ensure_future(_end_swap_flight(s))

async def _end_swap_flight(s):
    try:
        await asyncio.sleep(FLIGHT_SECONDS)
    except asyncio.CancelledError:
        return
    s['swap_flight_task'] = None
    s['swap_flight'] = None
    if s['phase'] == 'swap_flight':
        await start_racing(s)

async def send(ws, msg):
    try:
        if hasattr(ws, 'send_json'):
            await ws.send_json(msg)
        else:
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

# ── Knowledge tracking (per-player uid → card identity) ───────────────────────
# Enables the "reaction swap" mechanic: a player may play an opponent's card only
# for uids they already learned about (via peek/see_* abilities or by keeping a
# drawn card into a slot). Knowledge is keyed by uid, so slot swaps preserve it
# automatically. Discarding a card wipes that uid from all players' memory so a
# later reshuffle back into a hand does not leak.

def _note_seen(p, card):
    if not card or not p:
        return
    uid = card.get('uid')
    if not uid:
        return
    p['known_cards'][uid] = {
        k: card[k] for k in ('nr', 'name', 'value', 'ability', 'quote', 'image', 'color')
    }

def _forget_uid(s, uid):
    if not uid:
        return
    for p in s['players']:
        p['known_cards'].pop(uid, None)

def _find_card_slot(s, uid):
    """Return (player, hand_index) for the given uid, or (None, None). Small linear
    scan — hands are at most ~4×4 slots — is simpler than maintaining a side index."""
    if not uid:
        return None, None
    for p in s['players']:
        for i, c in enumerate(p['hand']):
            if c and c.get('uid') == uid:
                return p, i
    return None, None

async def send_state(s):
    now = _now()
    for viewer in s['players']:
        vi = s['players'].index(viewer)
        players_view = []
        for p in s['players']:
            hand_view = []
            for i, card in enumerate(p['hand']):
                shown = s.get('reveal_all') or (p['id'] == viewer['id'] and viewer['revealed'].get(str(i)))
                view = card_view(card, not shown)
                # knownByViewer lets the client mark cards the viewer has learned about
                # (via peek / see_* abilities / keeping a drawn card) without revealing
                # the value here. In der Schnapp-Phase darf zwar auf JEDE Karte getippt
                # werden – aber diese sind die, bei denen man nicht raten muss.
                if view and card and card.get('uid') in viewer.get('known_cards', {}):
                    view['knownByViewer'] = True
                hand_view.append(view)
            players_view.append(dict(
                id=p['id'], name=p['name'], connected=p['connected'],
                peekDone=p['peek_done'], isMe=(p['id'] == viewer['id']),
                hand=hand_view,
            ))

        ability_for_viewer = None
        if s['ability_state']:
            a = s['ability_state']
            selected_view = [{'playerId': x['player_id'], 'cardIndex': x['card_index']} for x in a.get('selected_cards', [])]
            ability_for_viewer = dict(
                type=a['type'], activatedBy=a['activated_by'],
                step=a.get('step'), waitingForSelection=a.get('waiting_for_selection'),
                selectedCards=selected_view,
            )
            if a['activated_by'] == viewer['id']:
                reveal_left = max(0.0, a.get('reveal_until', 0.0) - now)
                ability_for_viewer['revealSecondsLeft'] = round(reveal_left, 1)
                ability_for_viewer['revealedCard'] = card_view(a.get('revealed_card'), False) if (a.get('revealed_card') and reveal_left > 0) else None
                ability_for_viewer['revealedCards'] = [{'playerId': r['player_id'], 'cardIndex': r['card_index'], 'card': card_view(r['card'], False)} for r in a['revealed_cards']] if a.get('revealed_cards') else None

        cp = s['players'][s['current_player_index']] if s['players'] else None
        drawn_view = None
        if cp and cp['id'] == viewer['id'] and s['drawn_card']:
            drawn_view = card_view(s['drawn_card'], False)

        # Wer hält gerade eine gezogene Karte und überlegt noch? Das ist am echten
        # Tisch für alle sichtbar (nur der Kartenwert nicht) und treibt im Client die
        # Halte-Animation. Nur in 'playing' – legt der Spieler die Karte für eine
        # Fähigkeit ab, ist die Entscheidung gefallen und die Fähigkeitsanzeige
        # übernimmt, obwohl drawn_card serverseitig noch gesetzt ist.
        draw_holder = cp['id'] if (cp and s['drawn_card'] and s['phase'] == 'playing') else None

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
            drawnBy=draw_holder,
            abilityState=ability_for_viewer,
            racingCard=card_view(s['racing_card'], False) if s['racing_card'] else None,
            # Zeitleiste am Tisch: der Client zählt lokal flüssig herunter und
            # synchronisiert sich bei jedem State neu auf diesen Wert.
            raceSecondsLeft=round(max(0.0, s['race_deadline'] - now), 2) if s['phase'] == 'racing' else 0.0,
            raceTotalSeconds=RACE_SECONDS,
            raceMissed=(viewer['id'] in s['race_missed']),
            raceGive=(dict(
                racerId=s['race_give']['racer_id'],
                ownerId=s['race_give']['owner_id'],
                cardIndex=s['race_give']['card_index'],
                secondsLeft=round(max(0.0, s['race_give']['deadline'] - now), 1),
            ) if s.get('race_give') else None),
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
    _clear_race(s)
    _cancel_race_give(s)
    _cancel_ability_reveal(s)
    _cancel_swap_flight(s)
    for p in s['players']:
        p['hand'] = [s['deck'].pop() for _ in range(4)]
        _cancel_reveal(p)
        p['peek_selection'] = []
        p['peek_revealing'] = False
        p['peek_done'] = False
        p['known_cards'] = {}
        s['round_scores'][p['id']] = 0
    await send_state(s)

def _finish_peek(s, p):
    p['peek_revealing'] = False
    p['peek_done'] = True
    _check_all_peeked(s)

async def handle_peek(s, pid, card_index):
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
        for i in sel:
            _note_seen(p, p['hand'][i])
        await reveal_to_player(s, p, sel, REVEAL_SECONDS, on_expire=_finish_peek)
    await send_state(s)

async def handle_peek_done(s, pid):
    if s['phase'] != 'peek':
        return
    p = next((x for x in s['players'] if x['id'] == pid), None)
    if not p or p['peek_done'] or p['peek_revealing']:
        return
    if p['peek_selection']:
        p['peek_revealing'] = True
        for i in p['peek_selection']:
            _note_seen(p, p['hand'][i])
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
    await broadcast(s, dict(type='toast', key='log.callEnd', params={'name': cp['name']}, color='#ff9800',
                            anim={'kind': 'callEnd', 'playerId': pid}))
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
    await broadcast(s, dict(type='toast', key='log.draw', params={'name': cp['name']}, color='#60a5fa',
                            anim={'kind': 'draw', 'playerId': cp['id']}))
    await send_state(s)

async def handle_keep(s, pid, hand_index):
    if s['phase'] != 'playing' or not s['drawn_card']:
        return
    cp = s['players'][s['current_player_index']]
    if cp['id'] != pid or hand_index < 0 or hand_index >= len(cp['hand']):
        return
    replaced = cp['hand'][hand_index]
    # The drawer saw the drawn card in their preview; keeping it moves that
    # known identity into a slot. The replaced card goes public on discard,
    # so any per-player memory of that uid is cleared.
    _note_seen(cp, s['drawn_card'])
    _forget_uid(s, replaced['uid'])
    cp['hand'][hand_index] = s['drawn_card']
    cp['revealed'].pop(str(hand_index), None)
    s['drawn_card'] = None
    s['discard_pile'].append(replaced)
    await broadcast(s, dict(type='toast', key='log.keep',
                            params={'name': cp['name'], 'index': hand_index + 1}, color='#a78bfa',
                            anim={'kind': 'keep', 'playerId': cp['id'], 'cardIndex': hand_index,
                                  'card': card_view(replaced, False)}))
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
            resolved=False,
        )
        await send_state(s)
    else:
        _forget_uid(s, card['uid'])
        s['drawn_card'] = None
        s['discard_pile'].append(card)
        cp = s['players'][s['current_player_index']]
        await broadcast(s, dict(type='toast', key='log.discard', params={'name': cp['name']}, color='#60a5fa',
                                anim={'kind': 'deckToDiscard', 'playerId': cp['id'],
                                      'card': card_view(card, False)}))
        await start_racing(s)

# ── Schnapp-Phase ─────────────────────────────────────────────────────────────
# Nach jeder abgelegten Karte läuft ein kurzes Fenster, in dem JEDER Spieler auf
# eine beliebige Karte am Tisch tippen darf – die eigene oder eine gegnerische.
# Die getippte Karte wird für alle sichtbar aufgedeckt:
#   Treffer  → sie wandert auf den Ablagestapel, der Schnapper ist am Zug.
#              War es eine Gegnerkarte, füllt er die entstandene Lücke mit einer
#              eigenen Karte auf (race_give) – dadurch hat er eine Karte weniger.
#   Fehlgriff→ die Karte geht zurück an ihren Platz, der Schnapper zieht eine
#              Strafkarte und ist für den Rest dieses Fensters raus.

# Log-Animationen: jede Meldung im Ereignis-Log trägt optional einen `anim`-
# Deskriptor. Der Client kann ihn beim Klick auf die Zeile erneut abspielen –
# deshalb sind es Slot-Referenzen (Spieler + Position), keine Bildschirmwerte.
def _slot(ref):
    return {'playerId': ref['player_id'], 'cardIndex': ref['card_index']}

def _swap_anim(c1, c2):
    return {'kind': 'swap', 'slots': [_slot(c1), _slot(c2)]}

def _reindex_revealed(revealed, removed_index):
    """Reveal-Map nach dem Entfernen eines Slots neu durchnummerieren."""
    out = {}
    for k, v in revealed.items():
        ki = int(k)
        if ki < removed_index:
            out[str(ki)] = v
        elif ki > removed_index:
            out[str(ki - 1)] = v
    return out

def _cancel_race_give(s):
    if s.get('race_give_task'):
        s['race_give_task'].cancel()
    s['race_give_task'] = None
    s['race_give'] = None

def _clear_race(s):
    if s.get('racing_task'):
        s['racing_task'].cancel()
        s['racing_task'] = None
    s['racing_card'] = None
    s['race_deadline'] = 0.0
    s['race_missed'] = set()

async def start_racing(s):
    s['racing_card'] = s['discard_pile'][-1]
    s['phase'] = 'racing'
    s['race_missed'] = set()
    _cancel_race_give(s)
    s['race_deadline'] = _now() + RACE_SECONDS
    if s['racing_task']:
        s['racing_task'].cancel()
    s['racing_task'] = asyncio.ensure_future(_racing_timer(s))
    await send_state(s)

async def _racing_timer(s):
    try:
        await asyncio.sleep(RACE_SECONDS)
    except asyncio.CancelledError:
        return
    if s['phase'] != 'racing':
        return
    s['racing_task'] = None
    card = s['racing_card']
    _clear_race(s)
    s['phase'] = 'playing'
    await broadcast(s, dict(
        type='toast', key='log.raceTimeout', color='#64748b',
        anim={'kind': 'raceTimeout', 'card': card_view(card, False) if card else None},
    ))
    await advance_turn(s)

async def handle_race(s, pid, target_pid, card_index):
    """Ein Schnapp-Versuch auf eine beliebige Karte am Tisch."""
    if s['phase'] != 'racing' or not s['racing_card']:
        return
    p = next((x for x in s['players'] if x['id'] == pid), None)
    if not p:
        return
    # Ein Versuch pro Spieler und Fenster – sonst könnte man sich blind durch
    # alle Slots klicken, bis einer passt.
    if pid in s['race_missed']:
        return
    owner = p if not target_pid or target_pid == pid else next((x for x in s['players'] if x['id'] == target_pid), None)
    if not owner or card_index < 0 or card_index >= len(owner['hand']):
        return
    card = owner['hand'][card_index]
    if not card:
        return

    own = owner['id'] == pid
    match = card['value'] == s['racing_card']['value']

    # Wird VOR der Mutation gebaut: der Client braucht den Slot, an dem die Karte
    # in diesem Moment noch liegt, um die Aufdeck-Animation dort zu starten.
    reveal = dict(
        type='race_reveal', racerId=pid, racerName=p['name'],
        ownerId=owner['id'], ownerName=owner['name'], cardIndex=card_index,
        uid=card['uid'], card=card_view(card, False), match=match, own=own,
        revealSeconds=RACE_REVEAL_SECONDS,
    )

    if not match:
        s['race_missed'].add(pid)
        refill_deck(s)
        penalty_index = None
        if s['deck']:
            p['hand'].append(s['deck'].pop())
            penalty_index = len(p['hand']) - 1
        reveal['penalty'] = {'playerId': pid, 'cardIndex': penalty_index}
        await broadcast(s, reveal)
        await broadcast(s, dict(
            type='toast',
            key='log.raceMissOwn' if own else 'log.raceMissOther',
            params={'name': p['name'], 'owner': owner['name'], 'index': card_index + 1,
                    'cardNr': card['nr'], 'value': card['value']},
            color='#f44336',
            anim={'kind': 'raceMiss', 'racerId': pid, 'ownerId': owner['id'],
                  'cardIndex': card_index, 'card': card_view(card, False),
                  'penaltyIndex': penalty_index},
        ))
        await send_state(s)
        return

    # ── Treffer: Fenster sofort schließen ────────────────────────────────────
    _clear_race(s)
    _forget_uid(s, card['uid'])
    s['discard_pile'].append(card)
    await broadcast(s, reveal)

    if own:
        owner['hand'].pop(card_index)
        owner['revealed'] = _reindex_revealed(owner['revealed'], card_index)
        s['current_player_index'] = s['players'].index(p)
        s['phase'] = 'playing'
        await broadcast(s, dict(
            type='toast',
            key='log.raceHitOwn',
            params={'name': p['name'], 'index': card_index + 1,
                    'cardNr': card['nr'], 'value': card['value']},
            color='#4CAF50',
            anim={'kind': 'raceHit', 'racerId': pid, 'ownerId': owner['id'],
                  'cardIndex': card_index, 'card': card_view(card, False), 'own': True},
        ))
        await send_state(s)
        return

    # Gegnerkarte getroffen: der Slot bleibt als Lücke stehen und wird gleich
    # mit einer Karte des Gewinners aufgefüllt. Netto verliert der Gewinner die
    # Karte, der Gegner behält seine Handgröße.
    owner['hand'][card_index] = None
    owner['revealed'].pop(str(card_index), None)

    await broadcast(s, dict(
        type='toast',
        key='log.raceHitOther',
        params={'name': p['name'], 'owner': owner['name'], 'index': card_index + 1,
                'cardNr': card['nr'], 'value': card['value']},
        color='#9C27B0',
        anim={'kind': 'raceHit', 'racerId': pid, 'ownerId': owner['id'],
              'cardIndex': card_index, 'card': card_view(card, False), 'own': False},
    ))

    if not any(p['hand']):
        # Nichts abzugeben – die Lücke fällt ersatzlos weg.
        owner['hand'].pop(card_index)
        owner['revealed'] = _reindex_revealed(owner['revealed'], card_index)
        s['current_player_index'] = s['players'].index(p)
        s['phase'] = 'playing'
        await send_state(s)
        return

    s['phase'] = 'race_give'
    s['race_give'] = dict(racer_id=pid, owner_id=owner['id'], card_index=card_index,
                          deadline=_now() + RACE_GIVE_SECONDS)
    s['race_give_task'] = asyncio.ensure_future(_race_give_timer(s, s['race_give']))
    await send_state(s)

async def _race_give_timer(s, gv):
    try:
        await asyncio.sleep(RACE_GIVE_SECONDS)
    except asyncio.CancelledError:
        return
    if s['phase'] != 'race_give' or s.get('race_give') is not gv:
        return
    s['race_give_task'] = None
    p = next((x for x in s['players'] if x['id'] == gv['racer_id']), None)
    if not p:
        return
    # Zeit abgelaufen: der Server gibt die letzte Karte ab, damit das Spiel
    # nicht an einem abgelenkten Gewinner hängen bleibt.
    filled = [i for i, c in enumerate(p['hand']) if c]
    if not filled:
        return
    await _resolve_race_give(s, filled[-1], auto=True)

async def handle_race_give(s, pid, hand_index):
    if s['phase'] != 'race_give' or not s.get('race_give'):
        return
    if s['race_give']['racer_id'] != pid:
        return
    p = next((x for x in s['players'] if x['id'] == pid), None)
    if not p or hand_index < 0 or hand_index >= len(p['hand']) or not p['hand'][hand_index]:
        return
    await _resolve_race_give(s, hand_index)

async def _resolve_race_give(s, hand_index, auto=False):
    gv = s['race_give']
    if not gv:
        return
    p = next((x for x in s['players'] if x['id'] == gv['racer_id']), None)
    owner = next((x for x in s['players'] if x['id'] == gv['owner_id']), None)
    slot = gv['card_index']
    if not p or not owner or hand_index >= len(p['hand']) or not p['hand'][hand_index]:
        return
    given = p['hand'][hand_index]

    # Vor der Mutation aufnehmen – der Client braucht den Startslot.
    anim = dict(
        type='race_give_anim',
        fromPlayerId=p['id'], fromCardIndex=hand_index,
        toPlayerId=owner['id'], toCardIndex=slot, uid=given['uid'],
    )

    # Die abgegebene Karte behält ihre uid, also folgt das Wissen darüber
    # automatisch – der Gewinner weiß weiterhin, was der Gegner jetzt hält.
    owner['hand'][slot] = given
    owner['revealed'].pop(str(slot), None)
    p['hand'].pop(hand_index)
    p['revealed'] = _reindex_revealed(p['revealed'], hand_index)

    _cancel_race_give(s)
    s['current_player_index'] = s['players'].index(p)
    s['phase'] = 'playing'

    await broadcast(s, anim)
    await broadcast(s, dict(
        type='toast',
        key='log.giveAuto' if auto else 'log.give',
        params={'name': p['name'], 'owner': owner['name'], 'index': hand_index + 1},
        color='#9C27B0',
        anim={'kind': 'give', 'fromPlayerId': p['id'], 'fromCardIndex': hand_index,
              'toPlayerId': owner['id'], 'toCardIndex': slot},
    ))
    await send_state(s)

async def _finish_peek_ability(s, a):
    # Gemeinsame Schlusssequenz für see_own/see_others: gezogene Karte auf den
    # Ablagestapel, State auf None, Racing starten. `resolved` verhindert, dass
    # der Timer und ein "Fertig" gleichzeitig doppelt aufräumen.
    if a.get('resolved'):
        return
    a['resolved'] = True
    _cancel_ability_reveal(s)
    if s.get('ability_state') is a:
        _forget_uid(s, a['drawn_card']['uid'])
        s['discard_pile'].append(a['drawn_card'])
        s['drawn_card'] = None
        s['ability_state'] = None
    await start_racing(s)

async def handle_ability(s, pid, data):
    if s['phase'] != 'ability':
        return
    a = s['ability_state']
    if not a or a['activated_by'] != pid or a.get('resolved'):
        return

    t = a['type']
    # Für see_own/see_others: nur ein explizites `done` beendet die Fähigkeit.
    # Ohne diesen Marker wurde jede zweite Nachricht (z. B. ein Doppelklick auf
    # eine zweite Karte) fälschlich als Abschluss interpretiert und die Fähigkeit
    # damit direkt nach dem ersten Reveal geschlossen.
    done_flag = bool(data.get('done', data.get('done_ability')))

    def norm_card_ref(ref):
        if not ref:
            return None
        return {'player_id': ref.get('playerId', ref.get('player_id')), 'card_index': ref.get('cardIndex', ref.get('card_index', -1))}

    if t == 'see_own':
        if a['waiting_for_selection']:
            if done_flag:
                # Vorzeitig überspringen ohne Karte anzuschauen: direkt aufräumen.
                await _finish_peek_ability(s, a)
                return
            p = next(x for x in s['players'] if x['id'] == pid)
            idx = data.get('cardIndex', data.get('card_index', -1))
            if idx is None or idx < 0 or idx >= len(p['hand']):
                return
            a['revealed_card'] = p['hand'][idx]
            _note_seen(p, p['hand'][idx])
            a['selected_cards'] = [{'player_id': pid, 'card_index': idx}]
            a['waiting_for_selection'] = False
            start_ability_reveal(s, a)
            await broadcast(s, dict(type='toast', key='log.seeOwn',
                                    params={'name': p['name'], 'index': idx + 1}, color='#f472b6',
                                    anim={'kind': 'peek', 'slots': [{'playerId': p['id'], 'cardIndex': idx}]}))
            await send_state(s)
        else:
            # Reveal läuft: nur explizites Fertig beendet vorzeitig, alles andere
            # (weitere Kartenklicks während der 6 s) wird ignoriert.
            if done_flag:
                await _finish_peek_ability(s, a)

    elif t == 'see_others':
        if a['waiting_for_selection']:
            if done_flag:
                await _finish_peek_ability(s, a)
                return
            tpid = data.get('targetPlayerId', data.get('target_player_id'))
            tp = next((x for x in s['players'] if x['id'] == tpid), None)
            if not tp or tp['id'] == pid:
                return
            idx = data.get('cardIndex', data.get('card_index', -1))
            if idx is None or idx < 0 or idx >= len(tp['hand']):
                return
            a['revealed_card'] = tp['hand'][idx]
            activator = next(x for x in s['players'] if x['id'] == pid)
            _note_seen(activator, tp['hand'][idx])
            a['selected_cards'] = [{'player_id': tp['id'], 'card_index': idx}]
            a['waiting_for_selection'] = False
            start_ability_reveal(s, a)
            await broadcast(s, dict(type='toast', key='log.seeOther',
                                    params={'name': activator['name'], 'owner': tp['name'], 'index': idx + 1}, color='#f472b6',
                                    anim={'kind': 'peek', 'slots': [{'playerId': tp['id'], 'cardIndex': idx}]}))
            await send_state(s)
        else:
            if done_flag:
                await _finish_peek_ability(s, a)

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
                # Zweite Karte darf nicht die gleiche wie die erste sein.
                if c1['player_id'] == c2['player_id'] and c1['card_index'] == c2['card_index']:
                    return
                flight = _flight_cards(s, c1, c2)
                if not flight:
                    return
                a['resolved'] = True
                _do_swap(s, c1, c2)
                _forget_uid(s, a['drawn_card']['uid'])
                s['discard_pile'].append(a['drawn_card'])
                s['drawn_card'] = None
                _cancel_ability_reveal(s)
                s['ability_state'] = None
                activator = next(x for x in s['players'] if x['id'] == pid)
                p1n = next(x for x in s['players'] if x['id'] == c1['player_id'])['name']
                p2n = next(x for x in s['players'] if x['id'] == c2['player_id'])['name']
                await broadcast(s, dict(
                    type='toast',
                    key='log.swap',
                    params={'name': activator['name'], 'i1': c1['card_index']+1, 'p1': p1n,
                            'i2': c2['card_index']+1, 'p2': p2n},
                    color='#9C27B0',
                    anim=_swap_anim(c1, c2),
                ))
                await start_swap_flight(s, flight, 'swap')

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
                if c1['player_id'] == c2['player_id'] and c1['card_index'] == c2['card_index']:
                    return
                p1 = next(x for x in s['players'] if x['id'] == c1['player_id'])
                p2 = next(x for x in s['players'] if x['id'] == c2['player_id'])
                a['revealed_cards'] = [
                    {'player_id': c1['player_id'], 'card_index': c1['card_index'], 'card': p1['hand'][c1['card_index']]},
                    {'player_id': c2['player_id'], 'card_index': c2['card_index'], 'card': p2['hand'][c2['card_index']]},
                ]
                activator = next(x for x in s['players'] if x['id'] == pid)
                _note_seen(activator, p1['hand'][c1['card_index']])
                _note_seen(activator, p2['hand'][c2['card_index']])
                a['selected_cards'] = [c1, c2]
                a['step'] = 'decide_swap'
                a['waiting_for_selection'] = False
                start_ability_reveal(s, a)
                p1n = next(x for x in s['players'] if x['id'] == c1['player_id'])['name']
                p2n = next(x for x in s['players'] if x['id'] == c2['player_id'])['name']
                await broadcast(s, dict(
                    type='toast',
                    key='log.seeTwo',
                    params={'name': activator['name'], 'i1': c1['card_index']+1, 'p1': p1n,
                            'i2': c2['card_index']+1, 'p2': p2n},
                    color='#f472b6',
                    anim={'kind': 'peek', 'slots': [_slot(c1), _slot(c2)]},
                ))
                await send_state(s)
        elif a['step'] == 'decide_swap':
            # Nur der Tauschen/Nicht-tauschen-Marker beendet diesen Schritt –
            # Klicks auf Karten während des Reveals sind kein Auslöser mehr.
            if 'doSwap' not in data and 'do_swap' not in data:
                return
            a['resolved'] = True
            c1, c2 = a['selected_cards']
            do_swap = bool(data.get('doSwap', data.get('do_swap')))
            flight = _flight_cards(s, c1, c2)
            activator = next(x for x in s['players'] if x['id'] == pid)
            p1n = next(x for x in s['players'] if x['id'] == c1['player_id'])['name']
            p2n = next(x for x in s['players'] if x['id'] == c2['player_id'])['name']
            if do_swap and flight:
                _do_swap(s, c1, c2)
                await broadcast(s, dict(
                    type='toast',
                    key='log.swap',
                    params={'name': activator['name'], 'i1': c1['card_index']+1, 'p1': p1n,
                            'i2': c2['card_index']+1, 'p2': p2n},
                    color='#9C27B0',
                    anim=_swap_anim(c1, c2),
                ))
            else:
                # Auch "nicht getauscht" ist öffentliche Information – sonst wüssten
                # die anderen nicht, ob sich etwas verändert hat.
                await broadcast(s, dict(type='toast', key='log.noSwap',
                                        params={'name': activator['name']}, color='#64748b',
                                        anim={'kind': 'stay', 'slots': [_slot(c1), _slot(c2)]}))
            _forget_uid(s, a['drawn_card']['uid'])
            s['discard_pile'].append(a['drawn_card'])
            s['drawn_card'] = None
            _cancel_ability_reveal(s)
            s['ability_state'] = None
            await start_swap_flight(s, flight, 'swap' if do_swap else 'stay')

def _do_swap(s, c1, c2):
    p1 = next(x for x in s['players'] if x['id'] == c1['player_id'])
    p2 = next(x for x in s['players'] if x['id'] == c2['player_id'])
    i1, i2 = c1['card_index'], c2['card_index']
    p1['hand'][i1], p2['hand'][i2] = p2['hand'][i2], p1['hand'][i1]
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
    _clear_race(s)
    _cancel_race_give(s)
    _cancel_ability_reveal(s)
    _cancel_swap_flight(s)
    for p in s['players']:
        _cancel_reveal(p)
    # Offene Schnapp-Lücken (Gewinner hat nie abgegeben) verschwinden ersatzlos,
    # sonst würde die Wertung über None-Slots stolpern.
    for p in s['players']:
        p['hand'] = [c for c in p['hand'] if c]
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

    # Strafpunkte kann ausschliesslich der Spieler bekommen, der die Runde beendet
    # hat - und hoechstens einmal 30 Punkte pro Runde (die Gruende stapeln nicht).
    # Massgeblich ist nur seine Rundenpunktzahl auf der Hand, nie die Gesamtwertung.
    min_score = min(scores.values())
    caller = s['end_called_by']
    if caller and caller in scores:
        caller_score = scores[caller]
        # Nur die Gruende als Schluessel - den Satz darum baut der Client in der
        # Sprache des jeweiligen Spielers (siehe penaltyReason() im Frontend).
        reasons = []
        if caller_score != min_score:
            reasons.append('notWon')
        if caller_score > 7:
            reasons.append('over7')
        if reasons:
            penalty = 30
            scores[caller] = caller_score + penalty
            score_breakdown[caller]['penalties'].append({
                'amount': penalty,
                'reasons': reasons,
            })

    s['round_scores'] = scores
    s['score_breakdown'] = score_breakdown
    for pid, sc in scores.items():
        s['match_scores'][pid] = s['match_scores'].get(pid, 0) + sc

    s['reveal_all'] = True
    await send_state(s)

async def start_next_round(s):
    if s['round_number'] >= s['total_rounds']:
        s['phase'] = 'done'
        await send_state(s)
        return
    s['round_number'] += 1
    await start_game(s)

# ── WebSocket Handler ─────────────────────────────────────────────────────────
async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    ws_map[id(ws)] = {'ws': ws}

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                try:
                    data = json.loads(msg.data)
                    await dispatch(ws, data)
                except Exception:
                    pass
            elif msg.type == web.WSMsgType.ERROR:
                break
    finally:
        info = ws_map.pop(id(ws), None)
        if info and info.get('session_id'):
            s = sessions.get(info['session_id'])
            if s:
                p = next((x for x in s['players'] if x['id'] == info.get('player_id')), None)
                if p:
                    p['connected'] = False
                    await broadcast(s, dict(type='toast', key='log.disconnected',
                                            params={'name': p['name']}, color='#ff9800'))
                    await send_state(s)

    return ws

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
            await send(ws, dict(type='error', key='err.sessionNotFound')); return
        if s['phase'] != 'lobby':
            await send(ws, dict(type='error', key='err.gameStarted')); return
        if len(s['players']) >= 4:
            await send(ws, dict(type='error', key='err.sessionFull')); return
        if any(p['id'] == pid for p in s['players']):
            await send(ws, dict(type='error', key='err.alreadyIn')); return
        _add_player(s, pid, name, ws)
        ws_map[id(ws)].update(player_id=pid, session_id=sid)
        await send(ws, dict(type='joined', sessionId=sid))
        await broadcast(s, dict(type='toast', key='log.joined', params={'name': name}, color='#4CAF50'))
        await send_state(s)
        return

    info = ws_map.get(id(ws), {})
    pid = info.get('player_id')
    s = sessions.get(info.get('session_id'))
    if not s or not pid:
        return

    def gi(key):
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
        await handle_race(s, pid, g('targetPlayerId', 'target_player_id'), gi('cardIndex'))
    elif t == 'race_give':
        await handle_race_give(s, pid, gi('handIndex'))
    elif t == 'ability':
        await handle_ability(s, pid, msg)
    elif t == 'next_round':
        if s['phase'] in ('scoring', 'done'):
            await start_next_round(s)

# ── Static File Handler ───────────────────────────────────────────────────────
async def static_handler(request):
    path = request.match_info.get('path', '')

    if path.startswith('images/'):
        fpath = IMAGES_DIR / path[len('images/'):]
    else:
        if not path:
            path = 'index.html'
        fpath = PUBLIC_DIR / path
        if fpath.is_dir():
            fpath = fpath / 'index.html'

    if fpath.exists() and fpath.is_file():
        mime, _ = mimetypes.guess_type(str(fpath))
        return web.FileResponse(fpath, headers={'Content-Type': mime or 'text/html; charset=utf-8'})

    return web.Response(status=404, text='Not found')

async def index_handler(request):
    fpath = PUBLIC_DIR / 'index.html'
    return web.FileResponse(fpath, headers={'Content-Type': 'text/html; charset=utf-8'})

def create_app():
    app = web.Application()
    app.router.add_get('/ws', ws_handler)
    app.router.add_get('/', index_handler)
    app.router.add_get('/{path:.*}', static_handler)
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app = create_app()
    print(f'Karma running on http://0.0.0.0:{port}')
    web.run_app(app, host='0.0.0.0', port=port, print=lambda *args: None)
