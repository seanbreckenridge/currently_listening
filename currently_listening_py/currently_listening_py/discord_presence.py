import asyncio
import json
import time
from typing import AsyncGenerator, Optional
from asyncio import sleep

import websockets
from logzero import logger
from pydantic import BaseModel
from pypresence import AioPresence
from aiostream import stream


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
    server_url: str, poll_interval: Optional[int] = None
) -> AsyncGenerator[Payload, None]:
    # if were not polling, we want to send the message right away
    first: bool = poll_interval is None
    async for websocket in websockets.connect(server_url):
        try:
            if first:
                logger.debug("first loop; sending currently-listening message")
                await websocket.send("currently-listening")
                first = False
            if poll_interval is not None:
                await sleep(poll_interval)
                logger.debug("polling server for currently-listening...")
                await websocket.send("currently-listening")
            response = await websocket.recv()
            response = json.loads(response)
            response = Payload(**response)
            yield response
        except websockets.ConnectionClosed:
            logger.debug("Connection closed, reconnecting")
            await sleep(5)
            first = True
            continue


SENTINEL = object()


class SocketWithPoll:
    """
    this maintains two websocket connections, one with polls
    once every 3 minutes to help prevent rpc failures
    from leaving a stale presence

    the other is just the normal websocket connection
    which recieves broadcasts from the server

    since we have to wait 20 seconds between requests,
    if I spam skip on mpv with a bunch of songs, it ends up taking
    minutes before it catches up to the current song

    this maintains a queue which stores all requests, and
    only returns the latest one when we are ready to make a discord RPC request
    """

    def __init__(self, server_url: str) -> None:
        self.server_url = server_url
        self.poll_interval = 180

        self.combined = stream.merge(
            stream.iterate(get_currently_playing(server_url, poll_interval=180)),
            stream.iterate(get_currently_playing(server_url)),
        )

        self.items = asyncio.LifoQueue()
        self.lock = asyncio.Lock()
        self._websocket_task = asyncio.create_task(self.yield_iterator_to_queue())

    async def yield_iterator_to_queue(self):
        """
        whenever payloads are recieved from the websocket,
        asynchronously add them to this queue
        """

        async with self.combined.stream() as streamer:
            async for item in streamer:
                async with self.lock:
                    logger.debug(
                        f"adding {item} to queue, new size is {self.items.qsize() + 1}"
                    )
                    await self.items.put(item)

    def __aiter__(self):
        return self

    async def __anext__(self) -> Payload | object:
        # if empty, we block on the self.combined iterator
        # which returns an item when its available from the websocket
        if self.items.empty():
            # if there are no items from the websocket, spin until there are
            # returning a sentinel value to indicate that we should wait
            await sleep(1)
            return SENTINEL
        else:
            # if not empty, we only want the latest item, not any others that may have
            # accumulated while we were waiting for discord rate limit
            async with self.lock:
                next_item = self.items.get_nowait()
                self.items.task_done()
                logger.info(
                    f"returning {next_item} from queue, discarding {self.items.qsize()} other items"
                )

                # do this in a lock so that new items from the websocket
                # arent added while we are clearing the queue

                # empty rest of queue - no stdlib function to do this...?
                for _ in range(self.items.qsize()):
                    self.items.get_nowait()
                    self.items.task_done()

                return next_item


async def set_discord_presence_loop(
    server_url: str, client_id: str, discord_rpc_wait_time: int = 20
):
    RPC = AioPresence(client_id)
    await RPC.connect()
    current_state = None

    # offset first wait time so we dont wait first time updating presence
    last_request_at = time.time() - discord_rpc_wait_time * 2

    async def rate_limit() -> None:
        # should wait 15 seconds between updates
        sleep_for = discord_rpc_wait_time - (time.time() - last_request_at)
        if sleep_for > 0:
            logger.debug(f"Sleeping for {sleep_for} till next discord request")
            await sleep(sleep_for)

    socket = SocketWithPoll(server_url)

    while True:
        # wait till we can actually make a request, then try to fetch the next item
        # from the websocket queue. we wait first since otherwise new items may
        # accumulate while we are waiting for the rate limit
        await rate_limit()
        state = await socket.__anext__()
        if state == SENTINEL:
            # logger.debug("No new items from websocket, waiting")
            continue
        assert isinstance(state, Payload)
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
            last_request_at = time.time()
        else:
            logger.debug("Song is not playing, clearing presence")
            await rate_limit()
            current_state = None
            logger.debug(await RPC.clear())
            last_request_at = time.time()
