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
from typing import Optional, Any

import requests
from pydantic import BaseModel
from mpv_history_daemon.daemon import SocketData
from python_mpv_jsonipc import MPV  # type: ignore[import]

from logzero import logger  # type: ignore[import]


class SocketBody(BaseModel):
    events: Any
    filename: str
    is_playing: bool


class SetListening(BaseModel):
    title: str
    artist: str
    album: str
    started_at: int
    base64_image: str


class ClearListening(BaseModel):
    ended_at: int


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
        self.port = int(
            os.environ.get("MPV_CURRENTLY_LISTENING_LOCAL_SERVER_PORT", 3040)
        )
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
            except (ConnectionRefusedError, BrokenPipeError, TimeoutError):
                # is finished, so is 'paused'/done
                is_paused = True
        else:
            # sort of a hack to make this set a 'clear-listening'
            # event when mpv is quit
            is_paused = True
        assert isinstance(
            is_paused, bool
        ), f"Expected bool, got {type(is_paused)} {is_paused=}"
        try:
            resp = requests.post(
                f"http://localhost:{self.port}/socket_data",
                json=SocketBody(
                    events=self.events,
                    filename=f"{self.socket_time}.json",
                    is_playing=not is_paused,
                ).dict(),
            )
            if resp.status_code != 200:
                logger.warning(f"Failed to send data: {resp.status_code} {resp.text}")
        except requests.exceptions.RequestException as e:
            logger.exception(f"Failed to send data: {e}", exc_info=True)

    def store_file_metadata(self) -> None:
        super().store_file_metadata()
        self._started = True
        self._send_data()
