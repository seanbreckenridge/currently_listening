import json
from typing import AsyncGenerator
from asyncio import sleep

import websockets
from logzero import logger
from pydantic import BaseModel
from pypresence import AioPresence


class Song(BaseModel):
    title: str
    artist: str
    album: str | None

    def describe(self) -> str:
        desc = self.title
        if desc:
            desc = f"{desc} - {self.artist}"
        else:
            desc = self.artist

        if self.album:
            desc = f"{desc} ({self.album})"

        return desc


class SongPayload(BaseModel):
    song: Song | None
    playing: bool


class Payload(BaseModel):
    msg_type: str
    data: SongPayload


async def get_currently_playing(
    server_url: str,
) -> AsyncGenerator[Payload, None]:
    async for websocket in websockets.connect(server_url):
        try:
            await websocket.send("currently-listening")
            response = await websocket.recv()
            response = json.loads(response)
            response = Payload(**response)
            logger.debug(response)
            yield response
            await sleep(30)
        except websockets.ConnectionClosed:
            await sleep(60)
            continue


async def set_discord_presence_loop(server_url: str, client_id: str):
    RPC = AioPresence(client_id)
    await RPC.connect()
    current_state = None
    async for state in get_currently_playing(server_url):
        if state.data.playing and state.data.song is not None:
            if current_state == state.data:
                logger.debug("Song is playing, but no change in state")
                continue
            logger.debug("Song is playing, updating presence")
            kwargs = {}
            # TODO: add a lock here to prevent duplicate updates?
            await RPC.update(
                state=state.data.song.describe(),
                **kwargs,
            )
            # update local state after successful update
            current_state = state.data
        else:
            if current_state is not None:
                logger.debug("Song is not playing, clearing presence")
                await RPC.clear()
                # update local state after successful update
                current_state = None
            else:
                logger.debug("Song is not playing, but no change in state")
