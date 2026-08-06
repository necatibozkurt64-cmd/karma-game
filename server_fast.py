#!/usr/bin/env python3
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import json, os, asyncio, random, secrets
from pathlib import Path

app = FastAPI()
PUBLIC_DIR = Path(__file__).parent / 'public'

sessions = {}
ws_map = {}

def gen_session_id():
    return ''.join(random.choices('ABCDEFGHJKLMNPQRSTUVWXYZ23456789', k=6))

async def send(ws, msg):
    try:
        await ws.send_json(msg)
    except:
        pass

async def broadcast(s, msg):
    for p in s['players']:
        await send(p['ws'], msg)

async def send_state(s):
    for p in s['players']:
        await send(p['ws'], dict(type='state', phase=s['phase'], sessionId=s['id']))

async def start_game(s):
    s['phase'] = 'playing'
    await send_state(s)

async def dispatch(ws, msg):
    t = msg.get('type')

    if t == 'create':
        pid = msg.get('playerId')
        name = msg.get('playerName')
        sid = gen_session_id()
        s = dict(
            id=sid, host_id=pid, players=[dict(id=pid, name=name, ws=ws)],
            phase='lobby', match_scores={pid: 0}, round_scores={pid: 0}
        )
        sessions[sid] = s
        ws_map[id(ws)] = {'player_id': pid, 'session_id': sid}
        await send(ws, dict(type='created', sessionId=sid))
        await send_state(s)

    elif t == 'join':
        pid = msg.get('playerId')
        name = msg.get('playerName')
        sid = msg.get('sessionId', '').upper()
        s = sessions.get(sid)
        if not s:
            await send(ws, dict(type='error', msg='Session nicht gefunden'))
            return
        if len(s['players']) >= 4:
            await send(ws, dict(type='error', msg='Voll'))
            return
        s['players'].append(dict(id=pid, name=name, ws=ws))
        s['match_scores'][pid] = s['round_scores'][pid] = 0
        ws_map[id(ws)] = {'player_id': pid, 'session_id': sid}
        await broadcast(s, dict(type='toast', msg=f'{name} ist beigetreten'))
        await send_state(s)

    elif t == 'start':
        info = ws_map.get(id(ws), {})
        s = sessions.get(info.get('session_id'))
        if s and info.get('player_id') == s['host_id'] and len(s['players']) >= 2:
            await start_game(s)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    try:
        while True:
            data = await websocket.receive_json()
            await dispatch(websocket, data)
    except:
        pass
    finally:
        info = ws_map.pop(id(websocket), None)

@app.get("/")
async def index():
    return FileResponse(PUBLIC_DIR / 'index.html')

@app.get("/{full_path:path}")
async def serve_static(full_path: str):
    fpath = PUBLIC_DIR / full_path
    if fpath.exists() and fpath.is_file():
        return FileResponse(fpath)
    return FileResponse(PUBLIC_DIR / 'index.html')

if __name__ == '__main__':
    import uvicorn
    port = int(os.environ.get('PORT', 3000))
    uvicorn.run(app, host='0.0.0.0', port=port, log_level='error')
