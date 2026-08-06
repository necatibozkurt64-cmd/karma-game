#!/usr/bin/env python3
import asyncio, json, os
from aiohttp import web
from pathlib import Path

sessions = {}

async def ws_handler(request):
    ws = web.WebSocketResponse()
    await ws.prepare(request)
    await ws.send_json({"type": "connected"})

    try:
        async for msg in ws:
            if msg.type == web.WSMsgType.TEXT:
                data = json.loads(msg.data)
                t = data.get('type')

                if t == 'create':
                    sid = os.urandom(3).hex().upper()
                    pid = data.get('playerId')
                    name = data.get('playerName')
                    sessions[sid] = {'id': sid, 'host': pid, 'players': [{'id': pid, 'name': name}]}
                    await ws.send_json({'type': 'created', 'sessionId': sid})

                elif t == 'join':
                    sid = data.get('sessionId')
                    pid = data.get('playerId')
                    name = data.get('playerName')
                    if sid in sessions:
                        sessions[sid]['players'].append({'id': pid, 'name': name})
                        await ws.send_json({'type': 'joined', 'sessionId': sid})

                elif t == 'start':
                    sid = data.get('sessionId')
                    if sid in sessions:
                        await ws.send_json({'type': 'state', 'phase': 'playing'})
    except:
        pass
    finally:
        return ws

async def index(request):
    return web.FileResponse(Path(__file__).parent / 'public' / 'index.html')

async def static(request):
    path = request.match_info['path']
    fpath = Path(__file__).parent / 'public' / path
    if fpath.exists() and fpath.is_file():
        return web.FileResponse(fpath)
    return web.FileResponse(Path(__file__).parent / 'public' / 'index.html')

app = web.Application()
app.router.add_get('/ws', ws_handler)
app.router.add_get('/', index)
app.router.add_get('/{path:.*}', static)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 3000))
    print(f'Starting on http://0.0.0.0:{port}')
    web.run_app(app, host='0.0.0.0', port=port, print=lambda *_: None)
