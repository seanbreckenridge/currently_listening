"""
A subclass of the SocketData class from mpv_history_daemon

goes from:

mpv_history_daemon with custom SocketDataServer subclass ->
this server (parses/checks if its a song) ->
remote server (tracks current state) ->
web clients through websocket

the socketdataserver is used like
python3 -m mpv_history_daemon daemon /tmp/mpvsockets ~/data/mpv --socket-class-qualname 'currently_listening_py.socket_data.SocketDataServer'
"""

import os
from typing import Optional, Any, List

import requests
from more_itertools import last
from pydantic import BaseModel
from fastapi import APIRouter
from mpv_history_daemon.daemon import SocketData
from mpv_history_daemon.events import _read_event_stream, Media
from my_feed.sources.mpv import _media_is_allowed, _has_metadata
from python_mpv_jsonipc import MPV  # type: ignore[import]

from logzero import logger


class SocketBody(BaseModel):
    events: Any
    filename: str
    is_playing: bool


class SocketSend(BaseModel):
    title: str
    artist: str
    album: str
    started_at: int


class SocketDataManager:
    def __init__(self, remote_server: str, server_password: str) -> None:
        self.currently_playing: Optional[SocketSend] = None
        self.is_playing = False
        self.remote_server_url = remote_server
        self.server_password = server_password

    def _post(self, path: str, body: SocketSend) -> None:
        requests.post(
            f"{self.remote_server_url}/{path}",
            json=body.dict(),
            headers={"password": self.server_password},
        )

    def update_currently_playing(self, body: SocketSend, is_playing: bool) -> None:
        if not is_playing and self.is_playing:
            logger.debug("Clearing currently playing")
            self.currently_playing = None
            self.is_playing = False
            self._post(
                path="clear-playing",
                body=body,
            )
            return

        if is_playing and (
            self.currently_playing is None or self.currently_playing != body
        ):
            logger.debug(f"Setting currently playing to: {body.artist=} {body.title=} {body.album=}")
            self.currently_playing = body
            self.is_playing = True
            self._post(
                path="set-playing",
                body=body,
            )

    def process_currently_playing(self, body: SocketBody) -> None:
        # allow_if_playing_for=0 means every song is allowed, since
        # current time is always larger than the mpv start time
        data: List[Media] = list(
            _read_event_stream(
                body.events, filename=body.filename, allow_if_playing_for=0
            )
        )
        if len(data) == 0:
            return
        data.sort(key=lambda x: x.start_time)
        current = last(data)
        if not _media_is_allowed(current):
            logger.info(f"Media not allowed: {current}")
            return

        metadata = _has_metadata(current)
        if not metadata:
            logger.info(f"Media doesnt have enough metadata: {current.metadata}")
            return

        title, album, artist = metadata

        sendbody = SocketSend(
            title=title,
            artist=artist,
            album=album,
            started_at=int(current.start_time.timestamp()),
        )
        self.update_currently_playing(
            body=sendbody,
            is_playing=body.is_playing,
        )


manager: Optional[SocketDataManager] = None


def create_manager(remote_server: str, server_password: str) -> None:
    global manager
    manager = SocketDataManager(remote_server, server_password)


@staticmethod
def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/socket_data")
    def _socket_data(body: SocketBody) -> None:
        assert manager is not None
        manager.process_currently_playing(body)

    return router


class SocketDataServer(SocketData):

    SEND_EVENTS = set(
        [
            "eof",
            "paused",
            "resumed",
        ]
    )

    def __init__(
        self,
        socket: MPV,
        socket_loc: str,
        data_dir: str,
        write_period: Optional[int] = None,
    ):
        self.port = int(os.environ.get("MPV_CURRENTLY_PLAYING_LOCAL_SERVER_PORT", 3040))
        self._started = False
        super().__init__(socket, socket_loc, data_dir, write_period)

    def nevent(self, event_name: str, event_data: Optional[Any] = None) -> None:
        super().nevent(event_name, event_data)
        if not self._started:
            return
        # if eof/paused/resumed
        if event_name in self.SEND_EVENTS:
            self._send_data()
        if event_name == "final-write":
            self._send_data(is_final=True)

    def _send_data(self, is_final: bool = False) -> None:
        is_paused: Any
        if not is_final:
            try:
                is_paused = self.socket.pause
            except (ConnectionRefusedError, BrokenPipeError):
                # is finished, so is 'paused'/done
                is_paused = True
        else:
            # sort of a hack to make this set a 'clear-playing'
            # event when mpv is quit
            is_paused = True
        assert isinstance(
            is_paused, bool
        ), f"Expected bool, got {type(is_paused)} {is_paused=}"
        resp = requests.post(
            f"http://localhost:{self.port}/socket_data",
            json={
                "events": self.events,
                "filename": f"{self.socket_time}.json",
                "is_playing": not is_paused,
            },
        )
        if resp.status_code != 200:
            logger.error(
                f"Failed to send data: {resp.status_code} {resp.json()}", exc_info=True
            )

    def store_file_metadata(self) -> None:
        super().store_file_metadata()
        self._started = True
        self._send_data()
