import json
import time
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
    first: bool = True
    async for websocket in websockets.connect(server_url):
        try:
            if first:
                logger.debug("first loop; sending currently-listening message")
                await websocket.send("currently-listening")
                first = False
            logger.debug("waiting for response")
            response = await websocket.recv()
            response = json.loads(response)
            response = Payload(**response)
            logger.debug(response)
            yield response
        except websockets.ConnectionClosed:
            logger.debug("Connection closed, reconnecting")
            await sleep(5)
            first = True
            continue


async def set_discord_presence_loop(
    server_url: str, client_id: str, discord_rpc_wait_time: int = 20
):
    RPC = AioPresence(client_id)
    await RPC.connect()
    logger.debug(await RPC.clear())
    current_state = None
    # offset first wait time so we dont wait first time updating presence
    last_request_at = time.time() - discord_rpc_wait_time * 2

    async def rate_limit() -> None:
        nonlocal last_request_at
        # should wait 15 seconds between updates
        sleep_for = discord_rpc_wait_time - (time.time() - last_request_at)
        if sleep_for > 0:
            logger.debug(f"Sleeping for {sleep_for} seconds")
            await sleep(sleep_for)
        last_request_at = time.time()

    async for state in get_currently_playing(server_url):
        if state.data.playing and state.data.song is not None:
            if current_state == state.data:
                logger.debug("Song is playing, but no change in state")
                continue

            await rate_limit()

            logger.debug("Song is playing, updating presence")
            current_state = state.data
            # TODO: add a lock here to prevent duplicate updates?
            logger.debug(
                await RPC.update(
                    state=state.data.song.describe(),
                )
            )
        else:
            logger.debug("Song is not playing, clearing presence")
            await rate_limit()
            current_state = None
            logger.debug(await RPC.clear())
