import os
import json
import asyncio
from pathlib import Path
from typing import Union, Optional, List
from mpv_history_daemon.utils import MediaAllowed

import click

server_password = None


@click.group(context_settings={"max_content_width": 120})
@click.option(
    "--password",
    envvar="CURRENTLY_LISTENING_PASSWORD",
    show_envvar=True,
    help="Password for the server",
)
def main(password: str) -> None:
    global server_password
    server_password = password


def _generate_currently_playing_image(
    album: Union[str, None], artist: str, title: str, base64_image: str
) -> None:
    import base64

    from pathlib import Path
    from tempfile import NamedTemporaryFile

    from PIL import Image  # type: ignore[import]
    import imgkit  # type: ignore[import]

    # create a box with the album art, sort of like
    #
    # the background color should match your terminal, you can
    # set it with the BACKGROUND_COLOR environment variable

    ##################################
    #         # Song                 #
    #  IMAGE  # Artist               #
    #         # Album                #
    ##################################

    cache_dir = Path().home() / ".cache" / "currently-listening-py"
    cache_dir.mkdir(parents=True, exist_ok=True)

    cache_image = cache_dir / "currently_listening.jpg"

    # this is done with wkhtmltoimage, which creates a flexbox with the image on the left and the text on the right
    with cache_image.open("wb") as f:
        with NamedTemporaryFile(suffix=".jpg") as tf:
            tf.write(base64.b64decode(base64_image))
            tf.flush()
            img = Image.open(tf.name)
            width, height = img.size

        background_color = os.environ.get("BACKGROUND_COLOR", "#282828")
        text_color = os.environ.get("TEXT_COLOR", "#ebdbb2")

        template = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <style>
        html {{
            height: {height}px;
            width: {width * 5}px;
            background-color: {background_color};
            color: {text_color};
        }}
        body {{
            margin: 0;
            padding: 0;
            display: flex;
            flex-direction: row;
            justify-content: left;
            align-items: center;
            height: {height}px;
            width: {width * 5}px;
        }}
        .image {{
            height: {height}px;
            width: {width}px;
            background-image: url('data:image/jpg;base64,{base64_image}');
            background-size: contain;
            background-repeat: no-repeat;
            background-position: center;
        }}
        .text {{
            /* fit the text to the remaining space */
            width: {width * 4}px;
            padding-left: 5px;
            flex: 1;
            font-weight: bold;
            display: flex;
            flex-direction: column;
            align-items: left;
            font-family: sans-serif;
            margin-top: auto;
            margin-bottom: auto;
        }}
        </style>
</head>
<body>
    <div class="image"></div>
    <div class="text">
        <div>{title}</div>
        <div>{artist}</div>
        {"<div>" + album + "</div>" if album is not None else ""}
    </div>
</body>
</html>"""

        imgkit.from_string(
            template,
            f.name,
            options={"format": "jpg", "width": width * 5, "log-level": "warn"},
        )
        click.echo(f"Saved image to {f.name}", err=True)


async def _get_currently_playing(server_url: str, output: str) -> None:
    from websockets.client import connect

    async with connect(server_url) as websocket:
        await websocket.send("currently-listening")
        response = json.loads(await websocket.recv())

        if output == "json":
            click.echo(json.dumps(response, indent=2))
            return

        from .discord_presence import Payload

        data = Payload.model_validate(response).data
        song = data.song
        if song is None:
            click.echo("Nothing playing", err=True)
            exit(1)
        else:
            if output == "image" and song.base64_image is not None:
                return _generate_currently_playing_image(
                    song.album, song.artist, song.title, song.base64_image
                )

            if song.album is not None:
                click.echo(f"{song.title} - {song.artist} ({song.album})")
            else:
                click.echo(f"{song.title} - {song.artist}")


@click.option(
    "--server-url",
    default="ws://localhost:3030/ws",
    help="remote server url",
    show_default=True,
)
@click.option(
    "-o",
    "--output",
    type=click.Choice(["json", "text", "image"]),
    default="json",
    help="output format",
)
@main.command(short_help="print currently playing")
def print(server_url: str, output: str) -> None:
    asyncio.run(_get_currently_playing(server_url, output))


def _parse_matcher_config_file(
    matcher_config_file: Optional[Path],
) -> Union[MediaAllowed, None]:
    if matcher_config_file is None:
        return None

    if not matcher_config_file.exists():
        raise click.BadParameter(
            f"Matcher config file {matcher_config_file} does not exist"
        )

    from pydantic import BaseModel

    class MediaAllowedConfig(BaseModel):
        allow_prefixes: list[str] = []
        ignore_prefixes: list[str] = []
        allow_extensions: list[str] = []
        ignore_extensions: list[str] = []
        allow_stream: bool = False
        strict: bool = False

    known_keys: List[str] = list(MediaAllowedConfig.__fields__.keys())  # type: ignore
    assert isinstance(
        known_keys, list
    ), "error computing known_keys, may have been a pydantic API update"
    assert all(
        isinstance(key, str) for key in known_keys
    ), f"error computing known_keys, may have been a pydantic API update"

    with matcher_config_file.open("r") as f:
        data = json.loads(f.read())
        # make sure there are no extra keys
        for key in data.keys():
            if key not in known_keys:
                raise click.BadParameter(
                    f"Unknown key {key} in matcher config file {matcher_config_file}"
                )
        parsed = MediaAllowedConfig.model_validate(data)

    return MediaAllowed(
        allow_prefixes=parsed.allow_prefixes,
        ignore_prefixes=parsed.ignore_prefixes,
        allow_extensions=parsed.allow_extensions,
        ignore_extensions=parsed.ignore_extensions,
        allow_stream=parsed.allow_stream,
        strict=parsed.strict,
    )


@main.command(short_help="run local server")
@click.option(
    "--server-url",
    default="http://localhost:3030",
    help="remote server url",
    show_default=True,
)
@click.option(
    "--send-images/--no-send-images",
    default=False,
    is_flag=True,
    help="if available, send base64 encoded images to the server. This caches compressed thumbnails to a local cache dir",
)
@click.option("--port", default=3040, help="local port to host on")
@click.option(
    "--matcher-config-file",
    default=None,
    help="path to a matcher config file",
    type=click.Path(dir_okay=False, path_type=Path),
)
def server(
    server_url: str,
    port: int,
    send_images: bool,
    matcher_config_file: Optional[Path],
) -> None:
    assert (
        server_password is not None
    ), "Set password with `currently_listening_py --password '...' server` or set the CURRENTLY_LISTENING_PASSWORD environment variable"
    from .server import server as run_server

    matcher_config: Optional[MediaAllowed] = _parse_matcher_config_file(
        matcher_config_file
    )

    run_server(
        remote_server=server_url,
        port=port,
        server_password=server_password,
        cache_images=send_images,
        use_matcher=matcher_config,
    )


@main.command(short_help="set currently playing on discord")
@click.option(
    "--server-url",
    default="ws://localhost:3030/ws",
    help="remote server url",
    show_default=True,
)
@click.option(
    "--image-url",
    default="http://localhost:3030/currently-listening-image",
    help="endpoint for currently playing image url",
    show_default=True,
)
@click.option(
    "-d",
    "--discord-client-id",
    envvar="PRESENCE_CLIENT_ID",
    show_envvar=True,
    help="Discord client id for setting my presence",
)
@click.option(
    "-D",
    "--discord-rpc-wait-time",
    default=20,
    type=click.IntRange(min=15),
    help="Interval in seconds to wait between discord rpc requests",
)
@click.option(
    "-p",
    "--websocket-poll-interval",
    default=180,
    type=int,
    help="Interval in seconds to poll the websocket for updates, to make sure failed RPC requests dont lead to stale presence",
)
def discord_presence(
    server_url: str,
    image_url: str,
    discord_client_id: str,
    discord_rpc_wait_time: int,
    websocket_poll_interval: int,
) -> None:
    from .discord_presence import set_discord_presence_loop

    asyncio.run(
        set_discord_presence_loop(
            server_url,
            discord_client_id,
            image_url=image_url,
            discord_rpc_wait_time=discord_rpc_wait_time,
            websocket_poll_interval=websocket_poll_interval,
        )
    )


if __name__ == "__main__":
    main(prog_name="currently_listening_py")
