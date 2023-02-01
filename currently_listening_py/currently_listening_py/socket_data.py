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
import base64
from typing import Optional, Any, List
from pathlib import Path

import requests
import platformdirs
from more_itertools import last
from pydantic import BaseModel
from fastapi import APIRouter
from mpv_history_daemon.daemon import SocketData
from mpv_history_daemon.events import _read_event_stream, Media
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


class SocketDataManager:
    def __init__(
        self, remote_server: str, server_password: str, cache_images: bool
    ) -> None:
        self.currently_listening: Optional[SetListening] = None
        self.is_playing = False
        self.remote_server_url = remote_server
        self.server_password = server_password
        self.cache_images = cache_images
        self.cache_image_dir = Path(
            platformdirs.user_cache_dir(appname="currently-listening-py")
        )

    def _post_to_server(
        self, path: str, body: SetListening | ClearListening | None = None
    ) -> None:
        data: dict[str, Any] = body.dict() if body is not None else {}
        resp = requests.post(
            f"{self.remote_server_url}/{path}",
            json=data,
            headers={"password": self.server_password},
        )
        if resp.status_code != 200:
            logger.error(f"Got status code {resp.status_code} from {path}: {resp.text}")

    def update_currently_listening(
        self, body: SetListening | ClearListening, is_playing: bool
    ) -> None:
        if isinstance(body, ClearListening):
            if not is_playing and self.is_playing:
                logger.debug("Clearing currently listening")
                self.currently_listening = None
                self.is_playing = False
                self._post_to_server(
                    path="clear-listening",
                    body=body,
                )
                return
        else:
            if is_playing and self.currently_listening != body:
                logger.debug(
                    f"Setting currently listening to: {body.artist=} {body.title=} {body.album=}"
                )
                self.currently_listening = body
                self.is_playing = True
                self._post_to_server(
                    path="set-listening",
                    body=body,
                )

    COVERS = [
        "cover.jpg",
        "cover.png",
        "Folder.jpg",
        "Folder.png",
        "thumb.jpg",
    ]

    @classmethod
    def get_cover_art(cls, media: Media) -> Optional[Path]:
        collection_dir = os.path.dirname(media.path)
        for cover in cls.COVERS:
            cover_path = os.path.join(collection_dir, cover)
            if os.path.exists(cover_path):
                return Path(cover_path)
        return None

    @classmethod
    def cache_compressed_cover_art(cls, image: Path, save_to: Path) -> Path:
        from PIL import Image

        with open(image, "rb") as f:
            img = Image.open(f)
            img.thumbnail((100, 100))
            with open(save_to, "wb") as tf:
                img.save(tf, "JPEG")
            logger.debug(f"Saved compressed cover art to {save_to}")
        return save_to

    def get_compressed_cover_art(self, media: Media) -> Optional[str]:
        cover_art = self.get_cover_art(media)
        if cover_art is None:
            logger.debug(f"No cover art found for {media.path} using {self.COVERS=}")
            return None
        # exclude first part of path '/'
        # and last part of path (song filename)
        cache_dir_target = self.cache_image_dir / os.path.join(
            *Path(media.path).absolute().parts[1:-1]
        )
        logger.debug(f"Found source art: {cover_art=}")
        cache_target = (cache_dir_target / cover_art.name).with_suffix(".jpg")
        if not cache_target.exists():
            logger.debug(f"No cached cover art found: {cache_target=}")
            cache_target.parent.mkdir(parents=True, exist_ok=True)
            try:
                self.cache_compressed_cover_art(cover_art, save_to=cache_target)
            except Exception as e:
                logger.error(f"Failed to cache cover art: {e}")
                return None

        if cache_target.exists():
            logger.debug(f"Found cached cover art: {cache_target=}")
            # load image as base64
            with open(cache_target, "rb") as f:
                return base64.b64encode(f.read()).decode("utf-8")

        return None

    def process_currently_listening(self, body: SocketBody) -> None:
        from my_feed.sources.mpv import _media_is_allowed, _has_metadata

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

        cover_art = ""
        if self.cache_images and body.is_playing:
            cover_art = self.get_compressed_cover_art(current)

        sendbody: SetListening | ClearListening
        if body.is_playing:
            sendbody = SetListening(
                title=title,
                artist=artist,
                album=album,
                started_at=int(current.start_time.timestamp()),
                base64_image=cover_art or "",
            )
        else:
            sendbody = ClearListening(
                ended_at=int(current.start_time.timestamp()),
            )
        self.update_currently_listening(
            body=sendbody,
            is_playing=body.is_playing,
        )


manager: Optional[SocketDataManager] = None


def create_manager(
    remote_server: str, server_password: str, cache_images: bool
) -> None:
    global manager
    manager = SocketDataManager(remote_server, server_password, cache_images)


def create_router() -> APIRouter:
    router = APIRouter()

    @router.post("/socket_data")
    def _socket_data(body: SocketBody) -> None:
        assert manager is not None
        manager.process_currently_listening(body)

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
        resp = requests.post(
            f"http://localhost:{self.port}/socket_data",
            json=SocketBody(
                events=self.events,
                filename=f"{self.socket_time}.json",
                is_playing=not is_paused,
            ).dict(),
        )
        if resp.status_code != 200:
            logger.error(f"Failed to send data: {resp.status_code} {resp.text}")

    def store_file_metadata(self) -> None:
        super().store_file_metadata()
        self._started = True
        self._send_data()
