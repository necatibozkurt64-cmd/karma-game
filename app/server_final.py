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
    dict(nr=1,  name='Willy',             value=1,   ability='none',         quote='Was los, Meister?!',               count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=2,  name='Fabrice',           value=2,   ability='none',         quote='No Risk, no Story.',               count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=3,  name='Tom',               value=3,   ability='none',         quote='ham wir noch pep?',                count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=4,  name='Ugur',              value=4,   ability='none',         quote='einmal zwei döner',                count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=5,  name='Barbie',            value=5,   ability='none',         quote='Ciao bella ciao!',                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=6,  name='Carlin',            value=6,   ability='none',         quote='guys, I lost my phone..',          count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=7,  name='Ronaldo',           value=7,   ability='see_own',      quote='SUUUI ...your own card!!!',        count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=8,  name='Leo',               value=8,   ability='see_own',      quote='check this out',                   count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=9,  name='Penny',             value=9,   ability='see_others',   quote='They see everything..',            count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=10, name='Merkel',            value=10,  ability='see_others',   quote='alles Neuland.',                   count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=11, name='Joker',             value=11,  ability='swap',         quote="Let's do some confusion.",         count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=12, name='Hund',              value=12,  ability='see_swap',     quote='To the moon!',                     count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=13, name='Murat Abi',         value=13,  ability='none',         quote='Batterie abgeklemmt!',             count=2,  colors=['#F44336','#F44336']),
    dict(nr=14, name='Titi',              value=0,   ability='none',         quote='Cheers!',                          count=1,  colors=['#9E9E9E']),
    dict(nr=15, name='Katze',             value=-1,  ability='none',         quote='You lucky bastard.',               count=1,  colors=['#FFD700']),
]
IMAGE_FILES = {
    1:'fotos/01-willy.webp', 2:'fotos/02-fabrice.webp', 3:'fotos/03-tom.webp',
    4:'fotos/04-ugur.webp', 5:'fotos/05-barbie.webp', 6:'fotos/06-carlin.webp',
    7:'07_Ronaldo.jpeg', 8:'08_Leonardo DiCaprio.jpg', 9:'fotos/09-penny.webp',
    10:'fotos/10-merkel.webp', 11:'11_joker.jpg', 12:'12_Hund.jpg',
    13:'fotos/13-murat-abi.webp', 14:'14_Thierry Henry.jpeg', 15:'15_Katze.jpg',
}
IMAGES_DIR = Path(__file__).parent / 'public' / 'Bilder'
PUBLIC_DIR = Path(__file__).parent / 'public'
REVEAL_SECONDS = 6
# Flugfenster: so lange sehen alle Spieler die Karten von Slot zu Slot fliegen,
# bevor die zeitkritische Schnapp-Phase startet. Muss zur Client-Animation passen
# (SWAP_FLIGHT_MS: 1170ms + Nachglühen).
FLIGHT_SECONDS = 1.8
# Dasselbe Fenster für den Handtausch aus dem Nachziehstapel (handle_keep). Der
# Vorgang passiert jede Runde und besteht nur aus zwei gleichzeitigen Flügen –
# er braucht kein Aufdecken und darf deshalb kürzer sein als der Fähigkeitstausch.
# Ohne dieses Fenster liefe die Animation gegen den Schnapp-Timer: die Karte, auf
# die geschnappt werden soll, wäre noch unterwegs, während die Uhr schon läuft.
KEEP_FLIGHT_SECONDS = 1.5
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

sessions = {}
ws_map = {}

def gen_session_id():
    """Vierstelliger Zahlencode (0000-9999) - kurz genug zum Vorlesen und auf
    der Handy-Zahlentastatur einzutippen. Es gibt aber nur 10 000 davon und
    Sessions werden nie aufgeraeumt: der Vorrat kann theoretisch ausgehen.
    Deshalb liefert die Funktion einen *freien* Code bzw. None, wenn alle
    vergeben sind - ein 'while sid in sessions'-Retry wuerde den Server haengen.
    """
    for _ in range(50):
        sid = f'{random.randrange(10000):04d}'
        if sid not in sessions:
            return sid
    free = [f'{n:04d}' for n in range(10000) if f'{n:04d}' not in sessions]
    return random.choice(free) if free else None

def new_session(host_id, host_name, host_ws, game_mode, host_avatar=None):
    sid = gen_session_id()
    if sid is None:
        return None
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
        # Züge seit Rundenbeginn. Nur die Bots lesen das: eine Runde, in der
        # niemand "beenden" ruft, läuft sonst ewig (siehe _bot_should_call_end).
        round_turns=0,
        round_number=1, match_scores={}, round_scores={},
        score_breakdown={},
        # Ein Eintrag je beendeter Runde. Der Endstand baut daraus die Tabelle
        # "wie kam die Gesamtpunktzahl zustande" - match_scores allein ist nur
        # die Summe und verrät nicht, welche Runde teuer war. Wird nie geleert:
        # eine Session spielt genau ein Match.
        round_history=[],
        reveal_all=False, ability_reveal_task=None,
        swap_flight=None, swap_flight_task=None,
        # Treiber-Task der KI-Gegner. Höchstens einer je Session (siehe bot_kick).
        bot_task=None,
    )
    sessions[sid] = s
    _add_player(s, host_id, host_name, host_ws, host_avatar)
    return s

# Profilbild: die ID einer Figur aus dem Client-Katalog (AVATARS), z. B.
# 'card-11' oder 'legacy-trump'. Der Server prüft sie NICHT gegen eine Liste –
# er reicht sie nur durch, und der Client bildet unbekannte IDs auf den
# Namens-Initial ab. Sonst müsste der Katalog in drei Dateien gepflegt werden.
# Länge ist begrenzt, damit niemand über das Feld beliebig viel State ablegt.
AVATAR_MAX_LEN = 40

def _clean_avatar(v):
    return v[:AVATAR_MAX_LEN] if isinstance(v, str) and v else None

def _add_player(s, pid, name, ws, avatar=None, bot_level=None):
    # known_cards: uid → {value,nr,name,ability,quote,image,color}. Persistent per-player
    # knowledge of specific card identities (by uid). Populated when the player observes
    # a card (initial peek, see_own, see_others, see_swap, own drawn card kept). Cleared
    # for a uid when the card enters the discard pile (a re-shuffled draw is a fresh unknown).
    # Since uid is stable across slot swaps, knowledge naturally follows the card as it moves.
    # Ein Bot ist derselbe Eintrag ohne WebSocket (ws=None) – siehe Bot-Abschnitt.
    s['players'].append(dict(
        id=pid, name=name, ws=ws, hand=[], connected=True,
        avatar=_clean_avatar(avatar),
        revealed={}, reveal_until=0.0, reveal_task=None,
        peek_selection=[], peek_revealing=False, peek_done=False,
        known_cards={},
        is_bot=bool(bot_level), bot_level=bot_level,
        race_at=0.0, race_done=True, ability_plan=None,
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
    s['swap_flight_task'] = asyncio.ensure_future(_end_swap_flight(s, FLIGHT_SECONDS))

async def start_keep_flight(s, pid, hand_index, replaced):
    """Fenster für den Handtausch aus dem Nachziehstapel.

    Am echten Tisch sieht jeder, wie eine Karte in die Hand wandert und eine
    andere in die Ablage geht. Im Client war davon nichts zu sehen: die ersetzte
    Karte verschwindet vom Tisch und die neue trägt eine frische uid – die
    FLIP-Animation (runTableFlip) findet also weder Vorher- noch Nachher-Position
    und der Zug lief bei den Mitspielern komplett stumm ab.

    Wie beim Fähigkeitstausch kommt deshalb erst das Ereignis, dann der Zustand:
    `keep_anim` sagt, welcher Slot betroffen ist und welche Karte er abgegeben
    hat (die ist ab jetzt öffentlich, sie liegt oben auf der Ablage)."""
    _cancel_swap_flight(s)
    p = next((x for x in s['players'] if x['id'] == pid), None)
    new_card = p['hand'][hand_index] if p and 0 <= hand_index < len(p['hand']) else None
    s['phase'] = 'swap_flight'
    s['swap_flight'] = dict(cards=[], mode='keep')
    await broadcast(s, dict(
        type='keep_anim', playerId=pid, cardIndex=hand_index,
        uid=new_card['uid'] if new_card else None,
        card=card_view(replaced, False),
    ))
    await send_state(s)
    s['swap_flight_task'] = asyncio.ensure_future(_end_swap_flight(s, KEEP_FLIGHT_SECONDS))

async def _end_swap_flight(s, secs):
    try:
        await asyncio.sleep(secs)
    except asyncio.CancelledError:
        return
    s['swap_flight_task'] = None
    s['swap_flight'] = None
    if s['phase'] == 'swap_flight':
        await start_racing(s)

async def send(ws, msg):
    # Bots haben keine Verbindung – ihr "Client" ist der Treiber weiter unten.
    if ws is None:
        return
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
        # Ein Bot baut sich nie eine Sicht – er liest den Zustand direkt aus s.
        # Ihm eine zu bauen wäre nicht nur Arbeit umsonst, sondern auch die
        # Stelle, an der aus Versehen Hellsicht entstehen könnte.
        if viewer['ws'] is None:
            continue
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
                avatar=p.get('avatar'),
                isBot=bool(p.get('is_bot')), botLevel=p.get('bot_level'),
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
            roundHistory=s.get('round_history', []),
            sessionId=s['id'],
            revealSecondsLeft=round(max(0.0, viewer['reveal_until'] - now), 1),
            revealTotalSeconds=REVEAL_SECONDS,
            myPeekSelection=list(viewer['peek_selection']),
            peekRevealing=viewer['peek_revealing'],
        ))

    # Jeder Zustandswechsel ist der Anstoß für die Bots. Der Treiber selbst ruft
    # send_state auf – der Wächter in bot_kick sorgt dafür, dass daraus keine
    # zweite Schleife wird.
    bot_kick(s)

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
    # Der Startspieler wird jede Runde neu ausgelost - der Host hat kein Vorrecht.
    s['current_player_index'] = random.randrange(len(s['players']))
    s['drawn_card'] = None
    s['ability_state'] = None
    s['end_called_by'] = None
    s['final_round_left'] = 0
    s['round_turns'] = 0
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
        p['race_done'] = True
        p['ability_plan'] = None
        s['round_scores'][p['id']] = 0
    await send_state(s)
    # Das Los bleibt sonst unsichtbar: die Runde beginnt mit der Peek-Phase, und
    # wer dran ist, sieht man erst danach. Ohne diese Zeile wirkt es, als finge
    # immer der Host an.
    await broadcast(s, dict(type='toast', key='log.startPlayer',
                            params={'name': s['players'][s['current_player_index']]['name']},
                            color='#737bc4'))

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
    await start_keep_flight(s, cp['id'], hand_index, replaced)

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
    _bot_plan_race(s)
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
        # Der Fehlgriff dreht die Karte für ALLE sichtbar um und legt sie zurück.
        # Genau diese öffentliche Information darf sich der schwere Bot merken.
        _bot_note_race_reveal(s, card)
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

    # Auswahl zurücknehmen (Joker/Hund). Bewusst nur während der Auswahl selbst:
    # ab 'decide_swap' hat der Spieler die beiden Karten bereits gesehen, ein
    # "zurück" wäre dort ein zweiter Gratis-Blick auf ein neues Kartenpaar.
    # Zurückgesetzt wird immer auf select1 – bei zwei Klicks nacheinander ist die
    # erste Wahl fast immer die, die man revidieren will.
    if bool(data.get('undo')) and t in ('swap', 'see_swap') and a['step'] in ('select1', 'select2'):
        a['selected_cards'] = []
        a['step'] = 'select1'
        await send_state(s)
        return

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
    s['round_turns'] += 1
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

    # Rundenzeile für die Endstands-Tabelle. 'penalties' trägt nur die Summe je
    # Spieler - der Client markiert damit die Zelle mit '*', die Begründung steht
    # weiterhin ausformuliert in score_breakdown. Der Schutz gegen einen zweiten
    # Eintrag ist billig und hält die Tabelle auch dann ehrlich, wenn end_round
    # jemals doppelt ausgelöst würde.
    if not any(r['round'] == s['round_number'] for r in s['round_history']):
        s['round_history'].append({
            'round': s['round_number'],
            'scores': dict(scores),
            'penalties': {
                pid: sum(pen['amount'] for pen in bd['penalties'])
                for pid, bd in score_breakdown.items() if bd['penalties']
            },
        })

    s['reveal_all'] = True
    await send_state(s)

async def start_next_round(s):
    if s['round_number'] >= s['total_rounds']:
        s['phase'] = 'done'
        await send_state(s)
        return
    s['round_number'] += 1
    await start_game(s)

async def start_new_match(s):
    """'Neues Spiel' im Endstand - eine komplett neue Partie am selben Tisch.

    start_next_round() kann das nicht leisten: dort ist round_number bereits
    == total_rounds, der Aufruf fiele sofort wieder in den 'done'-Zweig und der
    Knopf tat schlicht gar nichts. Punktestand und Rundentabelle muessen dabei
    zurueck auf null, sonst zaehlt die neue Partie die alte weiter und die
    Tabelle im Endstand waechst ueber zwei Matches hinweg."""
    s['round_number'] = 1
    s['round_history'] = []
    s['score_breakdown'] = {}
    s['match_scores'] = {p['id']: 0 for p in s['players']}
    await start_game(s)

# ── Bots (KI-Gegner) ──────────────────────────────────────────────────────────
# Ein Bot ist ein ganz normaler Eintrag in s['players'] – nur ohne WebSocket
# (ws=None) und mit is_bot/bot_level. Er spielt AUSSCHLIESSLICH über dieselben
# handle_*-Funktionen wie ein Mensch. Dadurch gelten für ihn automatisch dieselben
# Regeln, dieselben Phasenprüfungen und dieselbe Wissensbuchführung (known_cards),
# und eine spätere Regeländerung kann nicht versehentlich nur eine der beiden
# Seiten treffen. Der Bot "schummelt" also nicht einmal versehentlich über einen
# eigenen Codepfad – er hat gar keinen.
#
# ⚠ KEINE HELLSICHT. Der einzige Zugang eines Bots zu einem Kartenwert ist
# bot_value(); die Funktion liest ausschliesslich aus known_cards, also aus dem,
# was der Bot wirklich gesehen hat (Peek zu Rundenbeginn, eigene Fähigkeiten,
# selbst behaltene Ziehkarten). Im Bot-Code darf card['value'] NIRGENDS direkt
# gelesen werden. Zwei Ausnahmen, die auch ein Mensch offen vor sich hat: die
# selbst gezogene Karte (s['drawn_card'] gehört dem Spieler am Zug) und die
# oberste Karte des Ablagestapels.
#
# Einzige Erweiterung nach oben: der SCHWERE Bot merkt sich zusätzlich Karten,
# die ein Fehlgriff beim Schnappen für alle sichtbar umgedreht und zurückgelegt
# hat (_bot_note_race_reveal). Das ist öffentliche Information – jeder am Tisch
# sieht sie –, nur merkt sie sich nicht jeder. Treffer gehören ausdrücklich nicht
# dazu: die Karte wandert in die Ablage, und _forget_uid löscht das Wissen ohnehin.

BOT_LEVELS = ('easy', 'medium', 'hard')

# Namen und Gesichter der Bots kommen aus dem Legacy-Avatar-Katalog des Clients
# (Bilder/avatare/legacy-*.webp) – am Tisch sitzt damit eine erkennbare Figur
# statt "Bot 2". Die IDs müssen zu AVATAR_LEGACY in index.html passen; eine
# unbekannte ID fällt dort auf den Namens-Initial zurück, mehr passiert nicht.
BOT_PERSONAS = [
    ('Olli', 'legacy-olli'),
    ('Arnold', 'legacy-arnold'),
    ('Cartman', 'legacy-cartman'),
    ('Zidane', 'legacy-zidane'),
    ('Tupac', 'legacy-tupac'),
    ('Snowden', 'legacy-snowden'),
    ('Bruce Lee', 'legacy-brucelee'),
    ('Trump', 'legacy-trump'),
]

# Erwartungswert einer unbekannten Karte: 337 Punkte auf 52 Karten im Deck.
# Damit rechnet der Bot Slots hoch, die er nie gesehen hat – genau wie ein Mensch,
# der weiss, was im Deck steckt, aber nicht, was vor ihm liegt.
UNKNOWN_EV = 6.5

# Was eine Fähigkeitskarte wert ist, wenn man sie ABLEGT statt sie auf die Hand
# zu nehmen – gerechnet in Punkten und direkt gegen den Gewinn des Handtauschs
# gestellt. Der leichte Bot ignoriert das (ability_worth=0) und wirft deshalb
# regelmässig einen guten Joker weg.
ABILITY_WORTH = {'none': 0.0, 'see_own': 2.0, 'see_others': 1.5, 'swap': 3.0, 'see_swap': 3.5}

# Die drei Stärken. Alles, was einen Bot besser oder schlechter macht, steht hier
# als Zahl – die Entscheidungsfunktionen selbst sind für alle Stärken dieselben.
#
# Am deutlichsten trennen die Stärken beim SCHNAPPEN, weil man das als Mensch
# unmittelbar merkt: wie schnell reagiert wird, wie oft danebengegriffen wird und
# ob überhaupt auf gegnerische Karten geschnappt wird.
#   race_delay        Reaktionszeit in Sekunden, ab Öffnen des Fensters. Muss
#                     unter RACE_SECONDS (5.0) bleiben, sonst kommt der Bot nie
#                     zum Zug.
#   race_accuracy     Trefferquote der eigenen Schnapp-Versuche. Der Rest geht
#                     bewusst daneben und kostet den Bot eine Strafkarte.
#   race_others       Schnappt auch auf Karten der Gegner (und schiebt dann eine
#                     eigene in die Lücke), nicht nur auf die eigenen.
#
#   think             Denkpause vor einem normalen Zug (Sekunden, von/bis).
#   blind_risk        Abschlag, wenn ein unbekannter Slot getauscht werden soll –
#                     der Bot weiss ja nicht, ob er gerade etwas Gutes wegwirft.
#   ability_worth     Faktor auf ABILITY_WORTH.
#   keep_margin       Wie viel Gewinn ein Handtausch mindestens bringen muss.
#   mistake           Wahrscheinlichkeit für einen schlicht falschen Zug.
#   end_*             Wann "Spiel beenden" gerufen wird.
#   patience          Ab wie vielen Zügen ein Vorsprung als Grund reicht, auch
#                     ohne perfekte Hand (Geduldsventil, s. _bot_should_call_end).
#   remembers_race    Merkt sich Karten aus Fehlgriffen beim Schnappen.
BOT_PROFILES = {
    'easy': dict(
        race_delay=4.0, race_accuracy=0.50, race_others=False,
        think=(1.2, 2.2),
        blind_risk=0.0, ability_worth=0.0, keep_margin=0.0,
        mistake=0.35,
        end_max_unknown=2, end_max_total=16.0, end_chance=0.2, patience=26,
        remembers_race=False,
    ),
    'medium': dict(
        race_delay=3.0, race_accuracy=0.65, race_others=True,
        think=(0.9, 1.6),
        blind_risk=0.8, ability_worth=1.0, keep_margin=0.5,
        mistake=0.12,
        end_max_unknown=2, end_max_total=8.0, end_chance=0.6, patience=22,
        remembers_race=False,
    ),
    'hard': dict(
        race_delay=2.5, race_accuracy=0.90, race_others=True,
        think=(0.6, 1.1),
        blind_risk=1.2, ability_worth=1.0, keep_margin=0.3,
        mistake=0.0,
        end_max_unknown=1, end_max_total=7.0, end_chance=0.95, patience=18,
        remembers_race=True,
    ),
}

def _prof(bot):
    return BOT_PROFILES.get(bot.get('bot_level'), BOT_PROFILES['medium'])

def bot_value(bot, card):
    """Der EINZIGE Weg, wie ein Bot an den Wert einer liegenden Karte kommt.

    Liefert None, solange der Bot die Karte nie gesehen hat. Alle Entscheidungen
    unten gehen durch diese Funktion – deshalb ist "der Bot kennt nur, was er
    gesehen hat" hier an genau einer Stelle durchgesetzt und nicht über ein
    Dutzend Heuristiken verteilt."""
    if not card:
        return None
    known = bot.get('known_cards', {}).get(card.get('uid'))
    return known['value'] if known else None

def _bot_note_race_reveal(s, card):
    """Fehlgriff beim Schnappen: die Karte lag offen auf dem Tisch und ging zurück.

    Nur der schwere Bot merkt sie sich. Leicht und mittel vergessen sie sofort
    wieder – auch dann, wenn sie den Fehlgriff selbst produziert haben."""
    for p in s['players']:
        if p.get('is_bot') and _prof(p)['remembers_race']:
            _note_seen(p, card)

def _bot_plan_race(s):
    """Reaktionszeiten für das gerade geöffnete Schnapp-Fenster auslosen.

    Jeder Bot bekommt EINEN Zeitpunkt und damit einen Versuch. Was er dann tippt,
    entscheidet er erst in diesem Moment – bis dahin kann ein Fehlgriff eines
    anderen ihm noch eine Karte verraten haben (nur schwer, siehe oben)."""
    now = _now()
    for p in s['players']:
        if p.get('is_bot'):
            p['race_at'] = now + _prof(p)['race_delay']
            p['race_done'] = False

def _bot_slots(bot, p):
    """[(index, wert-oder-None)] über die belegten Slots einer Hand."""
    return [(i, bot_value(bot, c)) for i, c in enumerate(p['hand']) if c]

def _bot_estimate(bot, p):
    """Geschätzte Punktzahl einer Hand aus Sicht dieses Bots."""
    return sum(UNKNOWN_EV if v is None else v for _, v in _bot_slots(bot, p))

def _bot_opponents(s, bot):
    return [p for p in s['players'] if p['id'] != bot['id']]

async def _bot_pause(bot, factor=1.0):
    """Denkpause. Immer als Vielfaches der Profil-Spanne, nie als feste Sekunde –
    sonst würde ein starker Bot an manchen Stellen doch wieder so lange grübeln
    wie ein schwacher."""
    a, b = _prof(bot)['think']
    await asyncio.sleep(random.uniform(a, b) * factor)

# ── Peek-Phase ────────────────────────────────────────────────────────────────
async def _bot_peek(s, bot):
    """Zwei der eigenen Karten ansehen.

    Welche, ist reine Willkür – zu diesem Zeitpunkt hat niemand Information, auch
    der schwere Bot nicht. Der Bot geht am Reveal-Timer vorbei (er muss sich
    nichts "einprägen", _note_seen genügt), sonst würde jede Runde 6 Sekunden
    warten, bevor der Mensch loslegen darf."""
    picks = random.sample(range(len(bot['hand'])), min(2, len(bot['hand'])))
    for i in picks:
        _note_seen(bot, bot['hand'][i])
    bot['peek_done'] = True
    _check_all_peeked(s)
    await send_state(s)

# ── Zug: ziehen, behalten oder ablegen ────────────────────────────────────────
def _bot_keep_index(s, bot):
    """Slot für die gezogene Karte, oder None fürs Ablegen.

    Die gezogene Karte liegt dem Bot offen vor (wie jedem Spieler am Zug), ihr
    Wert darf also direkt gelesen werden. Alles auf der Hand geht durch
    bot_value() und ist ohne Peek schlicht unbekannt."""
    card = s['drawn_card']
    prof = _prof(bot)
    if not card:
        return None
    v = card['value']

    best_i, best_gain = None, 0.0
    for i, c in enumerate(bot['hand']):
        if not c:
            continue
        kv = bot_value(bot, c)
        # Unbekannte Slots werden mit dem Erwartungswert gerechnet und um den
        # Blind-Abschlag gedrückt: eine ungesehene Karte wegzuwerfen ist eine
        # Wette, und je stärker der Bot, desto vorsichtiger wettet er.
        gain = (UNKNOWN_EV if kv is None else kv) - v
        if kv is None:
            gain -= prof['blind_risk']
        if gain > best_gain:
            best_i, best_gain = i, gain

    # Ablegen ist nicht "nichts tun": eine Fähigkeitskarte löst beim Ablegen ihre
    # Fähigkeit aus. Der Handtausch muss also mehr bringen als die Fähigkeit wert
    # ist – für den leichten Bot ist sie nichts wert, er wirft sie achtlos weg.
    worth = prof['ability_worth'] * ABILITY_WORTH.get(card['ability'], 0.0)
    if best_i is not None and best_gain >= worth + prof['keep_margin']:
        return best_i
    return None

def _bot_should_call_end(s, bot):
    """„Spiel beenden" rufen? Normalerweise nur mit einer vorzeigbaren Hand.

    Die Strafe von 30 Punkten trifft den Rufer, wenn er nicht die niedrigste Hand
    hat ODER über 7 Punkten liegt – daher die Schwellen. Weil unbekannte Karten
    mit 6,5 gerechnet werden, kann kein Bot gleich in den ersten Zügen rufen: mit
    zwei ungesehenen Slots liegt die Schätzung immer über jeder Schwelle.

    Dazu kommt ein Geduldsventil. Eine Hand mit fünf Karten kommt nie unter
    7 Punkte – ohne das Ventil würde eine Runde, in der kein Mensch mitspielt
    oder kein Mensch ruft, schlicht nie enden. Ab prof['patience'] Zügen genügt
    deshalb ein klarer Vorsprung, und noch später ruft der Bot notfalls auch mit
    einer mittelmässigen Hand."""
    if s['end_called_by'] or s['drawn_card']:
        return False
    prof = _prof(bot)
    slots = _bot_slots(bot, bot)
    if not slots:
        return True     # leere Hand = null Punkte, darauf muss man nicht warten
    unknown = sum(1 for _, v in slots if v is None)
    est = sum(UNKNOWN_EV if v is None else v for _, v in slots)
    # Liegt der Bot nach seinem eigenen Kenntnisstand vorn? Unbekannte Karten
    # zählen bei allen mit 6,5 – wer weniger Karten hält, steht damit besser da.
    ahead = all(_bot_estimate(bot, opp) > est + 1.0 for opp in _bot_opponents(s, bot))

    if unknown <= prof['end_max_unknown'] and est <= prof['end_max_total']:
        # Der schwere Bot ruft auch dann nur, wenn er wirklich vorne liegt.
        if not prof['remembers_race'] or ahead:
            return random.random() < prof['end_chance']

    turns = s.get('round_turns', 0)
    if turns >= prof['patience'] and ahead:
        return random.random() < 0.35
    if turns >= prof['patience'] * 2:
        return random.random() < 0.25
    return False

async def _bot_turn_step(s, bot):
    if not s['drawn_card']:
        if _bot_should_call_end(s, bot):
            await _bot_pause(bot)
            await handle_call_end(s, bot['id'])
            return True
        await _bot_pause(bot)
        await handle_draw(s, bot['id'])
        # Nachziehstapel leer und nichts zum Mischen: kein Zug möglich. Ohne
        # diesen Ausstieg würde der Treiber endlos gegen dieselbe Wand laufen.
        return bool(s['drawn_card'])

    await _bot_pause(bot)
    idx = _bot_keep_index(s, bot)
    if random.random() < _prof(bot)['mistake']:
        # Der leichte Bot vergreift sich: entweder er legt eine gute Karte weg
        # oder er tauscht eine gute Karte gegen eine schlechte.
        filled = [i for i, c in enumerate(bot['hand']) if c]
        idx = random.choice(filled) if (idx is None and filled) else None
    if idx is None:
        await handle_discard_drawn(s, bot['id'])
    else:
        await handle_keep(s, bot['id'], idx)
    return True

# ── Fähigkeiten ───────────────────────────────────────────────────────────────
def _bot_unknown_slots(bot, p):
    return [i for i, v in _bot_slots(bot, p) if v is None]

def _bot_pick_own_target(bot):
    """Eigener Slot, den anzusehen sich lohnt: einer, den der Bot nicht kennt."""
    unknown = _bot_unknown_slots(bot, bot)
    if unknown:
        return random.choice(unknown)
    filled = [i for i, _ in _bot_slots(bot, bot)]
    return random.choice(filled) if filled else None

def _bot_pick_other_target(s, bot):
    """(Gegner-Id, Slot) – bevorzugt bei dem Gegner, über den er am wenigsten weiss."""
    cands = []
    for opp in _bot_opponents(s, bot):
        unknown = _bot_unknown_slots(bot, opp)
        for i in unknown:
            cands.append((opp['id'], i, 0))
        if not unknown:
            for i, _ in _bot_slots(bot, opp):
                cands.append((opp['id'], i, 1))
    if not cands:
        return None
    best = min(c[2] for c in cands)
    pid, idx, _ = random.choice([c for c in cands if c[2] == best])
    return pid, idx

def _bot_swap_plan(s, bot):
    """Zwei Slots für Joker (blind) und Hund (nach dem Ansehen).

    Immer eine eigene Karte gegen eine gegnerische: die eigene ist die
    schlechteste bekannte (sonst eine beliebige), das Ziel eine bekannt bessere –
    und wenn der Bot nichts über den Gegner weiss, eine ungesehene als Wette.
    Der leichte Bot würfelt beides aus."""
    mine = _bot_slots(bot, bot)
    theirs = [(opp['id'], i, v) for opp in _bot_opponents(s, bot) for i, v in _bot_slots(bot, opp)]
    if not mine or not theirs:
        return None
    if random.random() < _prof(bot)['mistake']:
        mi = random.choice(mine)[0]
        tp, ti, _ = random.choice(theirs)
        return {'player_id': bot['id'], 'card_index': mi}, {'player_id': tp, 'card_index': ti}

    known_mine = [(i, v) for i, v in mine if v is not None]
    if known_mine:
        mi, mv = max(known_mine, key=lambda x: x[1])
    else:
        mi, mv = random.choice(mine)[0], None

    better = [x for x in theirs if x[2] is not None and (mv is None or x[2] < mv)]
    if better:
        tp, ti, _ = min(better, key=lambda x: x[2])
    else:
        unknown = [x for x in theirs if x[2] is None]
        tp, ti, _ = random.choice(unknown or theirs)
    return {'player_id': bot['id'], 'card_index': mi}, {'player_id': tp, 'card_index': ti}

def _as_ref(ref):
    return {'playerId': ref['player_id'], 'cardIndex': ref['card_index']}

async def _bot_ability_step(s, bot, a):
    kind = a['type']

    if kind in ('see_own', 'see_others'):
        if a['waiting_for_selection']:
            await _bot_pause(bot)
            if kind == 'see_own':
                idx = _bot_pick_own_target(bot)
                if idx is None:
                    await handle_ability(s, bot['id'], {'done': True})
                else:
                    await handle_ability(s, bot['id'], {'cardIndex': idx})
            else:
                pick = _bot_pick_other_target(s, bot)
                if not pick:
                    await handle_ability(s, bot['id'], {'done': True})
                else:
                    await handle_ability(s, bot['id'], {'targetPlayerId': pick[0], 'cardIndex': pick[1]})
        else:
            # Der Bot muss sich nichts einprägen – _note_seen ist schon passiert.
            # Er wartet die 6 Sekunden Reveal also nicht ab.
            await _bot_pause(bot, 0.6)
            await handle_ability(s, bot['id'], {'done': True})
        return True

    if kind in ('swap', 'see_swap'):
        if a['step'] == 'select1':
            plan = _bot_swap_plan(s, bot)
            if not plan:
                return False
            bot['ability_plan'] = plan
            await _bot_pause(bot)
            await handle_ability(s, bot['id'], {'card1': _as_ref(plan[0])})
            return True
        if a['step'] == 'select2':
            plan = bot.get('ability_plan') or _bot_swap_plan(s, bot)
            if not plan:
                return False
            await _bot_pause(bot, 0.5)
            await handle_ability(s, bot['id'], {'card2': _as_ref(plan[1])})
            return True
        if a['step'] == 'decide_swap':
            # Hund: beide Karten sind jetzt gesehen und stehen in known_cards –
            # der Bot rechnet also mit echtem Wissen, nicht mit Hellsicht.
            def seen_value(ref):
                owner = next((x for x in s['players'] if x['id'] == ref['player_id']), None)
                idx = ref['card_index']
                card = owner['hand'][idx] if owner and 0 <= idx < len(owner['hand']) else None
                return bot_value(bot, card)

            c1, c2 = a['selected_cards']
            v1, v2 = seen_value(c1), seen_value(c2)
            # c1 ist nach _bot_swap_plan immer die eigene Karte: getauscht wird,
            # wenn der Bot dabei die teurere der beiden loswird.
            do_swap = (v1 is not None and v2 is not None and v1 > v2)
            if random.random() < _prof(bot)['mistake']:
                do_swap = not do_swap
            await _bot_pause(bot, 0.8)
            await handle_ability(s, bot['id'], {'doSwap': do_swap})
            return True
    return False

# ── Schnapp-Phase ─────────────────────────────────────────────────────────────
def _bot_race_wrong(s, bot, target):
    """Danebengegriffen: ein Slot, der die abgelegte Karte gerade NICHT trifft.

    Bevorzugt eine Karte, von der der Bot weiss, dass sie nicht passt – so hält
    die Trefferquote aus dem Profil auch wirklich, statt sich über zufällig doch
    passende Blindtipper nach oben zu verschieben. Nur wenn er nichts kennt,
    greift er ins Ungewisse."""
    known_wrong, unknown = [], []
    for p in s['players']:
        for i, v in _bot_slots(bot, p):
            if v is None:
                unknown.append((p['id'], i))
            elif v != target:
                known_wrong.append((p['id'], i))
    pool = known_wrong or unknown
    return random.choice(pool) if pool else None

def _bot_race_pick(s, bot):
    """(Ziel-Spieler-Id, Slot) für einen Schnapp-Versuch, oder None.

    Geschnappt wird nur, wenn der Bot überhaupt eine passende Karte SIEHT – also
    eine, deren Wert er kennt (bot_value) und die zur abgelegten passt. Ohne
    Anlass tippt kein Bot ins Blaue.

    Ob der Versuch dann sitzt, entscheidet race_accuracy: der leichte Bot greift
    jedes zweite Mal daneben und kassiert die Strafkarte. Der leichte Bot sieht
    ausserdem nur die eigene Hand als Beute; ab mittel wird auch auf gegnerische
    Karten geschnappt – das ist die bessere Beute, weil der Bot die Karte los
    wird UND eine eigene in die entstandene Lücke schieben darf."""
    target = s['racing_card']['value']
    prof = _prof(bot)

    own = [(bot['id'], i) for i, v in _bot_slots(bot, bot) if v == target]
    theirs = []
    if prof['race_others']:
        theirs = [(opp['id'], i) for opp in _bot_opponents(s, bot)
                  for i, v in _bot_slots(bot, opp) if v == target]
    if not own and not theirs:
        return None

    if random.random() >= prof['race_accuracy']:
        return _bot_race_wrong(s, bot, target)

    # Auf eine gegnerische Karte zu schnappen lohnt sich vor allem, wenn der Bot
    # dabei etwas Teures loswird.
    my_worst = max((v for _, v in _bot_slots(bot, bot) if v is not None), default=None)
    if theirs and (not own or (my_worst is not None and my_worst >= 9)):
        return random.choice(theirs)
    return random.choice(own or theirs)

async def _bot_race_step(s):
    pending = [p for p in s['players']
               if p.get('is_bot') and not p['race_done'] and p['id'] not in s['race_missed']]
    if not pending:
        return False
    nxt = min(pending, key=lambda p: p['race_at'])
    wait = nxt['race_at'] - _now()
    if wait > 0:
        await asyncio.sleep(wait)
    if s['phase'] != 'racing':
        # Jemand war schneller (oder die Zeit lief ab) – die Schleife übernimmt
        # in der neuen Phase.
        return True
    nxt['race_done'] = True
    pick = _bot_race_pick(s, nxt)
    if pick:
        await handle_race(s, nxt['id'], pick[0], pick[1])
    return True

def _bot_give_index(s, bot):
    """Welche eigene Karte wandert nach einem Treffer zum Gegner? Die teuerste
    bekannte – und wenn der Bot keine seiner Karten kennt, eine beliebige."""
    slots = _bot_slots(bot, bot)
    if not slots:
        return None
    known = [(i, v) for i, v in slots if v is not None]
    if known and random.random() >= _prof(bot)['mistake']:
        return max(known, key=lambda x: x[1])[0]
    return random.choice(slots)[0]

# ── Treiber ───────────────────────────────────────────────────────────────────
def bot_kick(s):
    """Bots anstossen. Läuft schon eine Schleife, passiert nichts – send_state
    ruft diese Funktion auch aus der Schleife heraus wieder auf."""
    if not any(p.get('is_bot') for p in s['players']):
        return
    task = s.get('bot_task')
    if task and not task.done():
        return
    s['bot_task'] = asyncio.ensure_future(_bot_loop(s))

async def _bot_loop(s):
    """Arbeitet Bot-Aktionen nacheinander ab, bis nichts mehr zu tun ist.

    Die Obergrenze ist eine reine Notbremse: jeder Schritt geht durch die
    regulären handle_*-Funktionen, die einen unmöglichen Zug einfach verwerfen –
    ohne Zähler könnte ein solcher Fall die Schleife heiss laufen lassen."""
    try:
        for _ in range(600):
            if s['id'] not in sessions:
                return
            if not await _bot_step(s):
                return
    except asyncio.CancelledError:
        raise
    finally:
        s['bot_task'] = None

async def _bot_step(s):
    phase = s['phase']

    if phase == 'peek':
        bot = next((p for p in s['players']
                    if p.get('is_bot') and not p['peek_done'] and not p['peek_revealing']), None)
        if not bot:
            return False
        await _bot_pause(bot, 0.8)
        await _bot_peek(s, bot)
        return True

    if phase == 'racing':
        return await _bot_race_step(s)

    if phase == 'race_give':
        gv = s.get('race_give')
        bot = next((p for p in s['players'] if gv and p['id'] == gv['racer_id']), None)
        if not bot or not bot.get('is_bot'):
            return False
        await _bot_pause(bot)
        idx = _bot_give_index(s, bot)
        if idx is None:
            return False
        await handle_race_give(s, bot['id'], idx)
        return True

    if phase == 'ability':
        a = s.get('ability_state')
        bot = next((p for p in s['players'] if a and p['id'] == a['activated_by']), None)
        if not bot or not bot.get('is_bot') or a.get('resolved'):
            return False
        return await _bot_ability_step(s, bot, a)

    if phase == 'playing':
        if not s['players']:
            return False
        cp = s['players'][s['current_player_index']]
        if not cp.get('is_bot'):
            return False
        return await _bot_turn_step(s, cp)

    # lobby, swap_flight, scoring, done: die Bots haben nichts zu entscheiden.
    # swap_flight endet von selbst in start_racing – und das ruft send_state,
    # also auch bot_kick.
    return False

def add_bot(s, level):
    """Einen Bot an einen freien Platz setzen. Gibt seine Id zurück, sonst None."""
    if len(s['players']) >= 4:
        return None
    if level not in BOT_LEVELS:
        level = 'medium'
    used = {p['name'] for p in s['players']}
    pool = [x for x in BOT_PERSONAS if x[0] not in used] or BOT_PERSONAS
    name, avatar = random.choice(pool)
    pid = 'bot-' + secrets.token_hex(4)
    _add_player(s, pid, name, None, avatar, bot_level=level)
    return pid

def remove_bot(s, bot_id):
    p = next((x for x in s['players'] if x['id'] == bot_id and x.get('is_bot')), None)
    if not p:
        return False
    s['players'].remove(p)
    s['match_scores'].pop(bot_id, None)
    s['round_scores'].pop(bot_id, None)
    return True

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
        s = new_session(pid, name, ws, mode, g('avatar'))
        if s is None:
            await send(ws, dict(type='error', key='err.noFreeCode')); return
        # Einzelspieler: der Host bringt seine Gegner gleich mit. Sie sitzen ganz
        # normal am Tisch, es bleibt also eine ganz normale Session – ein Freund
        # kann sich immer noch auf einen freien Platz setzen.
        try:
            bots = int(g('bots') or 0)
        except (TypeError, ValueError):
            bots = 0
        level = g('botLevel', 'bot_level')
        for _ in range(max(0, min(3, bots))):
            add_bot(s, level)
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
        _add_player(s, pid, name, ws, g('avatar'))
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
    elif t == 'set_avatar':
        # Das Profilbild darf jederzeit gewechselt werden, auch mitten im Spiel –
        # es ist reine Anzeige und beeinflusst keine Spielregel. Der Wechsel ist
        # für alle sichtbar, deshalb geht danach ein State an den ganzen Tisch.
        p = next((x for x in s['players'] if x['id'] == pid), None)
        if p:
            p['avatar'] = _clean_avatar(g('avatar'))
            await send_state(s)
    elif t == 'add_bot':
        # Freie Plätze mit Bots auffüllen. Nur der Host, nur in der Lobby – ein
        # Bot, der mitten in der Runde dazukommt, hätte weder Hand noch Peek.
        if pid == s['host_id'] and s['phase'] == 'lobby':
            try:
                count = int(g('count') or 1)
            except (TypeError, ValueError):
                count = 1
            level = g('level')
            added = []
            for _ in range(max(1, min(4, count))):
                bid = add_bot(s, level)
                if not bid:
                    break
                added.append(next(x for x in s['players'] if x['id'] == bid))
            for b in added:
                await broadcast(s, dict(type='toast', key='log.botJoined',
                                        params={'name': b['name']}, color='#4CAF50'))
            if added:
                await send_state(s)
    elif t == 'remove_bot':
        if pid == s['host_id'] and s['phase'] == 'lobby':
            if remove_bot(s, g('botId', 'bot_id')):
                await send_state(s)
    elif t == 'next_round':
        if s['phase'] == 'scoring':
            await start_next_round(s)
        elif s['phase'] == 'done':
            await start_new_match(s)

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
