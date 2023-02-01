import json
import asyncio

import click

server_password = None


@click.group()
@click.option(
    "--password",
    envvar="CURRENTLY_LISTENING_PASSWORD",
    show_envvar=True,
    help="Password for the server",
)
def main(password: str) -> None:
    global server_password
    server_password = password


async def _get_currently_playing(server_url: str) -> None:
    from websockets.client import connect

    async with connect(server_url) as websocket:
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
@click.option(
    "--send-images/--no-send-images",
    default=False,
    is_flag=True,
    help="send base64 encoded images to server. This caches the compression to a local cache dir",
)
@click.option("--port", default=3040, help="local port to host on")
def server(server_url: str, port: int, send_images: bool) -> None:
    assert (
        server_password is not None
    ), "Set password with `currently_listening_py --password '...' server` or set the CURRENTLY_LISTENING_PASSWORD environment variable"
    from .server import server as run_server

    run_server(
        remote_server=server_url,
        port=port,
        server_password=server_password,
        cache_images=send_images,
    )


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
    discord_client_id: str,
    discord_rpc_wait_time: int,
    websocket_poll_interval: int,
) -> None:
    from .discord_presence import set_discord_presence_loop

    asyncio.run(
        set_discord_presence_loop(
            server_url,
            discord_client_id,
            discord_rpc_wait_time=discord_rpc_wait_time,
            websocket_poll_interval=websocket_poll_interval,
        )
    )


if __name__ == "__main__":
    main(prog_name="currently_listening_py")
