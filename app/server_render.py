#!/usr/bin/env python3
"""Karma card game server — aiohttp (single port for HTTP + WebSocket)."""
import asyncio
import json
import os
import random
import secrets
import string
from pathlib import Path
import mimetypes
from aiohttp import web

# Import all game logic from existing server
import sys
sys.path.insert(0, str(Path(__file__).parent))
from server import (
    CARD_DEFS, IMAGE_FILES, make_deck, gen_session_id,
    sessions, ws_map, new_session, _add_player, _now, _cancel_reveal,
    _cancel_ability_reveal, advance_turn, end_round, start_next_round,
    start_game, broadcast, send, send_state,
    handle_peek, handle_peek_done, handle_call_end, handle_draw,
    handle_keep, handle_discard_drawn, handle_race, handle_ability,
)

IMAGES_DIR = Path(__file__).parent / 'public' / 'Bilder'
PUBLIC_DIR = Path(__file__).parent / 'public'

async def dispatch(ws, msg):
    """Forward to server.py dispatch logic (copy the core)."""
    t = msg.get('type')

    def g(key, alt=None):
        return msg.get(key, msg.get(alt or key))

    def gi(key):
        import re
        def _to_snake(name):
            return re.sub(r'(?<!^)(?=[A-Z])', '_', name).lower()
        val = msg.get(key, msg.get(_to_snake(key), -1))
        return int(val) if val is not None else -1

    pid = g('playerId', 'player_id')

    if t == 'create':
        name = g('playerName', 'player_name')
        mode = g('gameMode', 'game_mode') or 'single'
        s = new_session(pid, name, ws, mode)
        ws_map[id(ws)].update(player_id=pid, session_id=s['id'])
        await send(ws, dict(type='created', sessionId=s['id']))
        await send_state(s)
        return

    if t == 'join':
        name = g('playerName', 'player_name')
        sid = (g('sessionId', 'session_id') or '').upper()
        s = sessions.get(sid)
        if not s:
            await send(ws, dict(type='error', msg='Session nicht gefunden'))
            return
        if len(s['players']) >= 4:
            await send(ws, dict(type='error', msg='Session voll'))
            return
        _add_player(s, pid, name, ws)
        ws_map[id(ws)].update(player_id=pid, session_id=s['id'])
        await broadcast(s, dict(type='toast', msg=f"{name} tritt bei.", color='#4CAF50'))
        await send_state(s)
        return

    s = sessions.get(ws_map.get(id(ws), {}).get('session_id'))
    if not s:
        return

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

async def ws_handler(request):
    """WebSocket handler using aiohttp."""
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
                    await broadcast(s, dict(type='toast', msg=f"{p['name']} hat die Verbindung getrennt.", color='#ff9800'))
                    await send_state(s)

    return ws

async def static_file(request):
    """Serve static files."""
    path = request.match_info.get('path', 'index.html')

    if path.startswith('images/'):
        fpath = IMAGES_DIR / path[len('images/'):]
    else:
        fpath = PUBLIC_DIR / path
        if fpath.is_dir():
            fpath = fpath / 'index.html'

    if fpath.exists() and str(fpath).startswith(str(PUBLIC_DIR.parent)):
        mime, _ = mimetypes.guess_type(str(fpath))
        return web.FileResponse(fpath, content_type=mime or 'text/html; charset=utf-8')

    return web.Response(status=404, text='Not found')

async def index(request):
    """Serve index.html."""
    fpath = PUBLIC_DIR / 'index.html'
    return web.FileResponse(fpath, content_type='text/html; charset=utf-8')

def create_app():
    app = web.Application()
    app.router.add_get('/ws', ws_handler)
    app.router.add_get('/', index)
    app.router.add_get('/{path:.*}', static_file)
    return app

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    app = create_app()
    print(f'Karma running on http://0.0.0.0:{port}')
    web.run_app(app, host='0.0.0.0', port=port)
