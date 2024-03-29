from __future__ import annotations
import json
import hashlib
import time
from typing import AsyncGenerator, Optional, Tuple
from asyncio import sleep, LifoQueue, Lock, create_task, CancelledError
from datetime import datetime

from websockets.client import connect, WebSocketClientProtocol
from websockets.exceptions import ConnectionClosed
from logzero import logger  # type: ignore[import]
from pydantic import BaseModel, Field
from pypresence import AioPresence  # type: ignore[import]


def _clamp_string(string: str, min_len: int = 2, max_len: int = 128) -> str:
    # pad with spaces
    if len(string) < min_len:
        string = string + " " * (min_len - len(string))
    # truncate
    if len(string) > max_len:
        string = string[:max_len]
    return string


class Song(BaseModel):
    title: str
    artist: str
    album: str | None
    base64_image: str = Field(repr=False)

    def describe_artist_album(self) -> str:
        desc = f"{self.artist}"

        if self.album:
            desc = f"{desc} ({self.album})"

        return desc


class SongPayload(BaseModel):
    song: Song | None
    playing: bool


class Payload(BaseModel):
    msg_type: str
    data: SongPayload


SENTINEL = object()


class SocketWithPoll:
    """
    This polls once every 3 minutes to help prevent rpc failures
    from leaving a stale presence

    Since we have to wait 20 seconds between requests to discord,
    if I spam websocket broadcasts on mpv with a bunch of songs, it ends up taking
    minutes before it catches up to the current song

    This maintains a queue which stores all requests, and
    only returns the latest one (discarding the rest),
    when we are ready to make a discord RPC request
    """

    def __init__(self, server_url: str, poll_interval: int) -> None:
        self.server_url = server_url
        self.poll_interval = poll_interval

        self._stream = self.get_currently_playing()
        self._items: LifoQueue[Tuple[datetime, SongPayload]] = LifoQueue()
        self._lock = Lock()
        self._websocket_task = create_task(self.yield_iterator_to_queue())

    async def get_currently_playing(
        self,
    ) -> AsyncGenerator[SongPayload, None]:
        current_websocket: Optional[WebSocketClientProtocol] = None

        async def _poll_on_websocket() -> None:
            assert self.poll_interval is not None
            # if websocket hasn't connected yet, wait until it is ready
            while current_websocket is None:
                await sleep(1)
            logger.debug(f"polling every {self.poll_interval} seconds")
            while True:
                await sleep(self.poll_interval)
                logger.debug("polling server for currently-listening...")
                if current_websocket.open:
                    await current_websocket.send("currently-listening")
                elif current_websocket.closed:
                    logger.debug("poll task: websocket closed, waiting..")

        poll_task = None
        async for websocket in connect(self.server_url):
            logger.debug("connected to websocket")
            current_websocket = websocket
            if self.poll_interval is not None and poll_task is None:
                poll_task = create_task(_poll_on_websocket())
            await websocket.send("currently-listening")
            while True:
                try:
                    response = await websocket.recv()
                    yield Payload(**json.loads(response)).data
                except ConnectionClosed:
                    logger.debug("Connection closed, reconnecting")
                    await sleep(1)
                    if poll_task is not None:
                        try:
                            poll_task.cancel()
                            await poll_task  # wait for task to finish, throw exception
                        except CancelledError as e:
                            logger.debug(f"poll task cancelled: {type(e)} {e}")
                        poll_task = None
                    break

    async def yield_iterator_to_queue(self) -> None:
        """
        whenever payloads are received from the websocket,
        asynchronously add them to this queue
        """

        async for item in self._stream:
            async with self._lock:
                logger.debug(
                    f"adding {item} to queue, new size is {self._items.qsize() + 1}"
                )
                await self._items.put((datetime.now(), item))

    def __aiter__(self) -> SocketWithPoll:
        return self

    async def __anext__(self) -> SongPayload | object:
        # if empty, we block on the self.combined iterator
        # which returns an item when its available from the websocket
        if self._items.empty():
            # if there are no items from the websocket, spin until there are
            # returning a sentinel value to indicate that we should wait
            await sleep(1)
            return SENTINEL
        else:
            # do this in a lock so that new items from the websocket
            # aren't added while we are clearing the queue
            async with self._lock:
                # if not empty, we only want the latest item, not any others that may have
                # accumulated while we were waiting for discord rate limit
                queue_items: list[Tuple[datetime, SongPayload]] = []
                while not self._items.empty():
                    queue_items.append(self._items.get_nowait())
                    self._items.task_done()  # let the queue know we're done with this task

                # sort by datetime, and return the latest item
                queue_items.sort(key=lambda x: x[0])
                next_item: SongPayload = queue_items[-1][1]
                logger.info(
                    f"returning {next_item} from queue, discarding {len(queue_items) - 1} other items"
                )
                return next_item


async def set_discord_presence_loop(
    server_url: str,
    client_id: str,
    *,
    image_url: str,
    discord_rpc_wait_time: int = 20,
    websocket_poll_interval: int = 180,
) -> None:
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

    socket = SocketWithPoll(server_url, poll_interval=websocket_poll_interval)

    while True:
        # wait till we can actually make a request, then try to fetch the next item
        # from the websocket queue. we wait first since otherwise new items may
        # accumulate while we are waiting for the rate limit
        await rate_limit()
        state = await anext(socket)
        if state == SENTINEL:
            # logger.debug("No new items from websocket, waiting")
            continue
        assert isinstance(state, SongPayload)
        if state.playing is True and state.song is not None:
            if current_state == state:
                logger.debug("Song is playing, but no change in state")
                continue
            current_state = state
            csong: Song = state.song

            logger.debug("Song is playing, updating presence")
            kwargs = {}
            if b64 := csong.base64_image.strip():
                # hash the base64 image to prevent discord from caching it
                # just using a prefix/suffix from the base64 here doesn't always produce a unique url
                imgurl = f"{image_url}/{hashlib.md5(b64.encode()).hexdigest()}"
                logger.debug(f"image url: {imgurl}")
                kwargs["large_image"] = imgurl
                kwargs["large_text"] = csong.album or csong.artist or "  "
            logger.debug(
                await RPC.update(
                    details=_clamp_string(csong.title),
                    state=_clamp_string(csong.describe_artist_album()),
                    **kwargs,
                )
            )
            last_request_at = time.time()
        else:
            logger.debug("Song is not playing, clearing presence")
            current_state = None
            logger.debug(await RPC.clear())
            last_request_at = time.time()
