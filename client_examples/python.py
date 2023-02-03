import os
import sys
import json
import asyncio

from websockets.client import connect
from websockets.exceptions import ConnectionClosed


async def _websocket_loop(server_url: str) -> None:
    async for websocket in connect(server_url):
        await websocket.send("currently-listening")
        try:
            while True:
                message = await websocket.recv()
                print(json.loads(message))
        except ConnectionClosed:
            print("Connection closed", file=sys.stderr)
            await asyncio.sleep(1)
            continue


asyncio.run(_websocket_loop(os.environ.get("WEBSOCKET_URL", "ws://localhost:3030/ws")))
