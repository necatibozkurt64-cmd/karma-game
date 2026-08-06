#!/usr/bin/env python3
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pathlib import Path
import os

app = FastAPI()
PUBLIC_DIR = Path(__file__).parent / 'public'

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    await websocket.send_json({"type": "connected", "msg": "WebSocket verbunden!"})
    try:
        while True:
            data = await websocket.receive_json()
            await websocket.send_json({"type": "echo", "data": data})
    except WebSocketDisconnect:
        pass

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
    uvicorn.run(app, host='0.0.0.0', port=port)
