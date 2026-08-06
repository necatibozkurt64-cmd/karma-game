#!/usr/bin/env python3
import asyncio, json, os, random, secrets, re, mimetypes
from pathlib import Path
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

# ── Game Logic (copied from server.py) ────────────────────────────────────────
CARD_DEFS = [
    dict(nr=1,  name='Olli',                  value=1,  ability='none',       quote='Eier, we need Eier',                       count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=2,  name='Tupac',                  value=2,  ability='none',       quote='Chill, Alter, es kommen auch gute Zeiten.',  count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=3,  name='Arnold Schwarzenegger',  value=3,  ability='none',       quote='I choose four',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=4,  name='Eric Cartman',           value=4,  ability='none',       quote='Respect My Authority!',                    count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=5,  name='Zinedine Zidane',        value=5,  ability='none',       quote='Ciao bella ciao!',                         count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=6,  name='Bruce Lee',              value=6,  ability='none',       quote='Bee water my friend',                      count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=7,  name='Ronaldo',                value=7,  ability='see_own',    quote='SUUUI ...your own card!!!',                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=8,  name='Leonardo DiCaprio',      value=8,  ability='see_own',    quote='check this out',                           count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=9,  name='Snowden',                value=9,  ability='see_others', quote='They see everything..',                    count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=10, name='Trump',                  value=10, ability='see_others', quote='Lets fuck up',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=11, name='Joker',                  value=11, ability='swap',       quote="Let's do some confusion.",                 count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=12, name='Hund',                   value=12, ability='see_swap',   quote='To the moon!',                             count=4,  colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=13, name='Mr Hankey',              value=13, ability='none',       quote='shit happens.',                            count=2,  colors=['#F44336','#F44336']),
    dict(nr=14, name='Thierry Henry',          value=0,  ability='none',       quote='Congratulations, you got me.',             count=1,  colors=['#9E9E9E']),
    dict(nr=15, name='Katze',                  value=-1, ability='none',       quote='You lucky bastard.',                       count=1,  colors=['#FFD700']),
]
IMAGE_FILES = {1:'01_Olli.png', 2:'02_tupac.jpg', 3:'03_arnold schwarzenegger.jpg', 4:'04_Eric Cartman.png', 5:'05_zidane.jpg', 6:'06_bruce lee.jpg', 7:'07_Ronaldo.jpeg', 8:'08_Leonardo DiCaprio.jpg', 9:'09_snowden.jpg', 10:'10_trump.jpg', 11:'11_joker.jpg', 12:'12_Hund.jpg', 13:'13_MrHankey.jpg', 14:'14_Thierry Henry.jpeg', 15:'15_Katze.jpg'}
REVEAL_SECONDS = 6
PUBLIC_DIR = Path(__file__).parent / 'public'

def _to_snake(n): return re.sub(r'(?<!^)(?=[A-Z])', '_', n).lower()
def make_deck():
    deck = []
    for d in CARD_DEFS:
        for i in range(d['count']):
            card = dict(d)
            card['color'] = d['colors'][i % len(d['colors'])]
            card['image'] = IMAGE_FILES[d['nr']]
            card['uid'] = secrets.token_hex(4)
            del card['colors'], card['count']
            deck.append(card)
    random.shuffle(deck)
    return deck

def gen_session_id(): return ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))

sessions, ws_map = {}, {}

def new_session(hid, hname, hws, gmode):
    sid = gen_session_id()
    while sid in sessions: sid = gen_session_id()
    s = dict(id=sid, host_id=hid, game_mode=gmode, total_rounds={'single':1,'best_of_3':3,'best_of_5':5,'best_of_10':10}.get(gmode, 1), players=[], deck=[], discard_pile=[], phase='lobby', current_player_index=0, drawn_card=None, ability_state=None, racing_card=None, racing_task=None, end_called_by=None, final_round_left=0, round_number=1, match_scores={}, round_scores={}, score_breakdown={}, reveal_all=False, ability_reveal_task=None)
    sessions[sid] = s
    s['players'].append(dict(id=hid, name=hname, ws=hws, hand=[], connected=True, revealed={}, reveal_until=0.0, reveal_task=None, peek_selection=[], peek_revealing=False, peek_done=False))
    s['match_scores'][hid] = s['round_scores'][hid] = 0
    return s

def _now(): return asyncio.get_event_loop().time()
def _cancel_reveal(p): p['reveal_task'] = p['revealed'] = None; p['reveal_until'] = 0.0
def _cancel_ability_reveal(s): s['ability_reveal_task'] = None
async def send(ws, msg):
    try: await ws.send_json(msg)
    except: pass

async def broadcast(s, msg):
    for p in s['players']: await send(p['ws'], msg)

async def send_state(s):
    for viewer in s['players']:
        vi = s['players'].index(viewer)
        players_view = [dict(id=p['id'], name=p['name'], connected=p['connected'], peekDone=p['peek_done'], isMe=(p['id'] == viewer['id']), hand=[{'hidden': not (s.get('reveal_all') or (p['id'] == viewer['id'] and viewer['revealed'].get(str(i))))} if c else None for i, c in enumerate(p['hand'])]) for p in s['players']]
        cp = s['players'][s['current_player_index']] if s['players'] else None
        await send(viewer['ws'], dict(type='state', phase=s['phase'], myId=viewer['id'], myIndex=vi, isHost=(viewer['id'] == s['host_id']), players=players_view, currentPlayerIndex=s['current_player_index'], currentPlayerId=cp['id'] if cp else None, deckSize=len(s['deck']), sessionId=s['id']))

async def start_game(s):
    s['deck'] = make_deck()
    s['discard_pile'] = [s['deck'].pop()]
    s['phase'] = 'playing'
    s['current_player_index'] = 0
    for p in s['players']: p['hand'] = [s['deck'].pop() for _ in range(4)]; s['round_scores'][p['id']] = 0
    await send_state(s)

async def dispatch(ws, msg):
    t = msg.get('type')
    def g(k, a=None): return msg.get(k, msg.get(a or k))
    if t == 'create':
        pid, name, mode = g('playerId', 'player_id'), g('playerName', 'player_name'), g('gameMode', 'game_mode') or 'single'
        s = new_session(pid, name, ws, mode)
        ws_map[id(ws)] = {'player_id': pid, 'session_id': s['id']}
        await send(ws, dict(type='created', sessionId=s['id']))
        await send_state(s)
    elif t == 'join':
        pid, name, sid = g('playerId', 'player_id'), g('playerName', 'player_name'), (g('sessionId', 'session_id') or '').upper()
        s = sessions.get(sid)
        if not s: await send(ws, dict(type='error', msg='Session nicht gefunden.')); return
        if len(s['players']) >= 4: await send(ws, dict(type='error', msg='Session voll')); return
        s['players'].append(dict(id=pid, name=name, ws=ws, hand=[], connected=True, revealed={}, reveal_until=0.0, reveal_task=None, peek_selection=[], peek_revealing=False, peek_done=False))
        s['match_scores'][pid] = s['round_scores'][pid] = 0
        ws_map[id(ws)] = {'player_id': pid, 'session_id': sid}
        await broadcast(s, dict(type='toast', msg=f'{name} ist beigetreten!', color='#4CAF50'))
        await send_state(s)
    elif t == 'start':
        info = ws_map.get(id(ws), {})
        s = sessions.get(info.get('session_id'))
        if s and info.get('player_id') == s['host_id'] and s['phase'] == 'lobby' and len(s['players']) >= 2:
            await start_game(s)

app = FastAPI()

@app.websocket("/ws")
async def websocket_endpoint(websocket):
    await websocket.accept()
    ws_map[id(websocket)] = {}
    try:
        while True:
            data = await websocket.receive_json()
            await dispatch(websocket, data)
    except:
        ws_map.pop(id(websocket), None)

@app.get("/")
async def index():
    return FileResponse(PUBLIC_DIR / 'index.html')

@app.get("/{full_path:path}")
async def serve_file(full_path: str):
    if full_path.startswith('images/'):
        fpath = PUBLIC_DIR / full_path
    else:
        fpath = PUBLIC_DIR / full_path if full_path else PUBLIC_DIR / 'index.html'
        if fpath.is_dir(): fpath = fpath / 'index.html'
    return FileResponse(fpath) if fpath.exists() else FileResponse(PUBLIC_DIR / 'index.html')

if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 3000))
    print(f'Karma on http://0.0.0.0:{port}')
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='error')
