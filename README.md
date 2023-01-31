A personal Websocket based currently playing web-service

This has lots of parts:

- `./server/main.go` [runs on Remote Server] - accepts `POST` requests from other clients, maintains the currently playing status/song data, accepts websocket connections on `/ws`
- `./listenbrainz_client/main.go` [runs on Remote Server] - polls listenbrainz [`playing-now`](https://listenbrainz.readthedocs.io/en/latest/users/api/core.html) every few seconds to get music I may be listening to in my browser or on my phone. Sends a request to `./server/main.go` whenever it detects currently playing music. That synced to ListenBrainz with [Pano Scrobbler](https://play.google.com/store/apps/details?id=com.arn.scrobble&hl=en_US&gl=US) (on Android) or [WebScrobbler](https://web-scrobbler.com/) (in Browser)
- [`mpv-history-daemon`](https://github.com/seanbreckenridge/mpv-history-daemon) with a custom `SocketData` class which intercepts calls to save metadata, sending it to a local server instead. That local server processes/filters it to music (not including any movies/tv shows I may be watching with `mpv`), and then sends it up to `./server/main.go`. Those commands [both run locally on my machine and,] look like:
  - `python3 -m mpv_history_daemon daemon /tmp/mpvsockets ~/data/mpv --socket-class-qualname 'currently_listening_py.socket_data.SocketDataServer'` to start `mpv_history_daemon` with the custom `SocketDataServer` class to intercept data
  - `python3 -m currently_listening_py server` to run the local server which processes the data

To authenticate the POST requests to update data, set the `CURRENTLY_LISTENING_PASSWORD` environment variable

To consume this, send a `currently-listening` message to the websocket URL, e.g.:

```python
import websockets

async with websockets.connect("ws://localhost:3030/ws") as websocket:
    await websocket.send("currently-listening")
    response = await websocket.recv()
    logger.info(response)
```

I have [some react code](https://github.com/seanbreckenridge/glue/blob/9ecb067f500cf7e32eccee023d0d417eb2fb2383/assets/frontend/currently_listening.tsx) that connects to the server here and displays it on my website. That appears on [my website](https://sean.fish) in the bottom left if I'm currently listening to something:

![demo sean.fish image](https://github.com/seanbreckenridge/currently_listening/blob/main/.github/demo.png?raw=true)

I also use this to set my discord presence, like:

`python3 -m currently_listening_py discord-presence --server-url wss://sean.fish/currently_listening/ws`

![demo discord image](https://github.com/seanbreckenridge/currently_listening/blob/main/.github/discord.png?raw=true)

To set that up see [pypresence](https://qwertyquerty.github.io/pypresence/html/info/quickstart.html) docs to get your client ID

TODO: add install/run instructions for each part
