import json
import asyncio

import click
from logzero import logger

from .server import server as run_server

server_password = None


@click.group()
@click.option(
    "--password",
    envvar="CURRENTLY_LISTENING_PASSWORD",
    help="Password for the server",
)
def main(password: str) -> None:
    global server_password
    server_password = password


async def _get_currently_playing(server_url: str) -> None:
    import websockets  # type: ignore[import]

    async with websockets.connect(server_url) as websocket:
        await websocket.send("currently-listening")
        response = json.loads(await websocket.recv())
        click.echo(json.dumps(response, indent=2))


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


@main.command(short_help="set currently playing on discord")
@click.option(
    "--server-url",
    default="ws://localhost:3030/ws",
    help="remote server url",
    show_default=True,
)
@click.option(
    "-d",
    "--discord-client-id",
    envvar="PRESENCE_CLIENT_ID",
    help="Discord client id for setting my presence",
)
def discord_presence(server_url: str, discord_client_id: str) -> None:
    from .discord_presence import set_discord_presence_loop

    asyncio.run(set_discord_presence_loop(server_url, discord_client_id))


if __name__ == "__main__":
    main(prog_name="currently_listening_py")
