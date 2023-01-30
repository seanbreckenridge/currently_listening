import asyncio

import click
from logzero import logger

from .server import server as run_server

server_password = None


@click.group()
@click.option(
    "--password",
    envvar="CURRENTLY_PLAYING_PASSWORD",
    help="Password for the server",
)
def main(password: str) -> None:
    global server_password
    server_password = password


async def _get_currently_playing(server_url: str) -> None:
    import websockets  # type: ignore[import]

    async with websockets.connect(server_url) as websocket:
        await websocket.send("currently-playing")
        response = await websocket.recv()
        logger.info(response)


@click.option(
    "--server-url",
    default="ws://localhost:3030/ws",
    help="remote server url",
    show_default=True,
)
@main.command(short_help="print currently playing")
def print(server_url: str) -> None:
    asyncio.run(_get_currently_playing(server_url))


@main.command(short_help="run local server")
@click.option(
    "--server-url",
    default="http://localhost:3030",
    help="remote server url",
    show_default=True,
)
@click.option("--port", default=3040, help="local port to host on")
def server(server_url: str, port: int) -> None:
    assert server_password is not None
    run_server(remote_server=server_url, port=port, server_password=server_password)


if __name__ == "__main__":
    main(prog_name="currently_listening_py")
