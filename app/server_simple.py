#!/usr/bin/env python3
"""Karma server - HTTP + WebSocket on same port (for ngrok/single-port deployment)"""
import asyncio, json, os, random, secrets, re
from pathlib import Path
from http.server import BaseHTTPRequestHandler, HTTPServer
from websockets.asyncio.server import serve
import threading
import urllib.parse
import mimetypes

CARD_DEFS = [
    dict(nr=1, name='Olli', value=1, ability='none', quote='Eier, we need Eier', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=2, name='Tupac', value=2, ability='none', quote='Chill, Alter, es kommen auch gute Zeiten.', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=3, name='Arnold', value=3, ability='none', quote='I choose four', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=4, name='Cartman', value=4, ability='none', quote='Respect My Authority!', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=5, name='Zinedine Zidane', value=5, ability='none', quote='Ciao bella ciao!', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=6, name='Bruce Lee', value=6, ability='none', quote='Bee water my friend', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=7, name='Ronaldo', value=7, ability='see_own', quote='SUUUI ...your own card!!!', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=8, name='Leo', value=8, ability='see_own', quote='check this out', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=9, name='Snowden', value=9, ability='see_others', quote='They see everything..', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=10, name='Trump', value=10, ability='see_others', quote='Lets fuck up', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=11, name='Joker', value=11, ability='swap', quote="Let's do some confusion.", count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=12, name='Hund', value=12, ability='see_swap', quote='To the moon!', count=4, colors=['#4CAF50','#9C27B0','#2196F3','#FF9800']),
    dict(nr=13, name='Mr Hankey', value=13, ability='none', quote='shit happens.', count=2, colors=['#F44336','#F44336']),
    dict(nr=14, name='Titi', value=0, ability='none', quote='Congratulations, you got me.', count=1, colors=['#9E9E9E']),
    dict(nr=15, name='Katze', value=-1, ability='none', quote='You lucky bastard.', count=1, colors=['#FFD700']),
]
IMAGE_FILES = {1:'01_Olli.png', 2:'02_tupac.jpg', 3:'03_arnold schwarzenegger.jpg', 4:'04_Eric Cartman.png', 5:'05_zidane.jpg', 6:'06_bruce lee.jpg', 7:'07_Ronaldo.jpeg', 8:'08_Leonardo DiCaprio.jpg', 9:'09_snowden.jpg', 10:'10_trump.jpg', 11:'11_joker.jpg', 12:'12_Hund.jpg', 13:'13_MrHankey.jpg', 14:'14_Thierry Henry.jpeg', 15:'15_Katze.jpg'}
IMAGES_DIR = Path(__file__).parent / 'public' / 'Bilder'
PUBLIC_DIR = Path(__file__).parent / 'public'

def gen_session_id(): return ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))
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

sessions, ws_map = {}, {}

async def send(ws, msg):
    try: await ws.send(json.dumps(msg))
    except: pass

async def broadcast(s, msg):
    for p in s['players']: await send(p['ws'], msg)

async def send_state(s):
    for p in s['players']: await send(p['ws'], dict(type='state', phase=s['phase'], sessionId=s['id']))

async def start_game(s): s['phase'] = 'playing'; await send_state(s)

async def dispatch(ws, msg):
    t = msg.get('type')
    if t == 'create':
        pid, name = msg.get('playerId'), msg.get('playerName')
        sid = gen_session_id()
        s = dict(id=sid, host_id=pid, players=[dict(id=pid, name=name, ws=ws)], phase='lobby', match_scores={pid:0}, round_scores={pid:0})
        sessions[sid] = s
        ws_map[id(ws)] = {'player_id': pid, 'session_id': sid}
        await send(ws, dict(type='created', sessionId=sid))
        await send_state(s)
    elif t == 'join':
        pid, name, sid = msg.get('playerId'), msg.get('playerName'), msg.get('sessionId','').upper()
        s = sessions.get(sid)
        if not s: await send(ws, dict(type='error', msg='Session nicht gefunden')); return
        if len(s['players']) >= 4: await send(ws, dict(type='error', msg='Voll')); return
        s['players'].append(dict(id=pid, name=name, ws=ws))
        s['match_scores'][pid] = s['round_scores'][pid] = 0
        ws_map[id(ws)] = {'player_id': pid, 'session_id': sid}
        await broadcast(s, dict(type='toast', msg=f'{name} ist beigetreten'))
        await send_state(s)
    elif t == 'start':
        info = ws_map.get(id(ws), {})
        s = sessions.get(info.get('session_id'))
        if s and info.get('player_id') == s['host_id'] and len(s['players']) >= 2: await start_game(s)

async def ws_handler(websocket):
    try:
        async for msg_text in websocket:
            msg = json.loads(msg_text)
            await dispatch(websocket, msg)
    except: pass

class HTTPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass
    def do_GET(self):
        path = urllib.parse.unquote(self.path.split('?')[0])
        if path.startswith('/images/'): fpath = IMAGES_DIR / path[len('/images/'):]
        else: fpath = PUBLIC_DIR / path.lstrip('/');
        if fpath.is_dir(): fpath = fpath / 'index.html'
        if fpath.exists():
            data = fpath.read_bytes()
            mime, _ = mimetypes.guess_type(str(fpath))
            self.send_response(200)
            self.send_header('Content-Type', mime or 'text/html; charset=utf-8')
            self.send_header('Content-Length', str(len(data)))
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(data)
        else: self.send_response(404); self.end_headers()
    def do_HEAD(self): self.send_response(200); self.end_headers()

def run_http(port): HTTPServer(('', port), HTTPHandler).serve_forever()

async def main():
    port = int(os.environ.get('PORT', 3000))
    threading.Thread(target=run_http, args=(port,), daemon=True).start()
    print(f'HTTP  → http://0.0.0.0:{port}')
    print(f'WS    → ws://0.0.0.0:{port} (same port!)')
    async with serve(ws_handler, '', port + 1):
        print('Karma ready.')
        await asyncio.Future()

if __name__ == '__main__': asyncio.run(main())
