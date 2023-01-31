A personal Websocket based currently playing web-service. Generally, this follows something like:

```
/**************************************************************************************/
/* client code which polls applications/websites for music I'm currently listening to */
/**************************************************************************************/
                                       |
                                       |
                                       |
                                       ▼
/*********************************************************************************/
/*                                  main server                                  */
/* accepts requests from other client code here to update currently listening to */
/*               broadcasts currently listening data on a websocket              */
/*********************************************************************************/
                                       |
                                       |
                                       |
                                       ▼
       /***************************************************************/
       /* enduser/applications which consume the websocket to display */
       /*       e.g. as part of my website/discord presence           */
       /***************************************************************/

```

As an example, I have [some react code](https://github.com/seanbreckenridge/glue/blob/master/assets/frontend/currently_listening.tsx) that connects to the main server here and displays it on my website. That appears on [my website](https://sean.fish) in the bottom left if I'm currently listening to something:

https://user-images.githubusercontent.com/7804791/215680067-6ca15266-c620-41b5-8809-6d4a38f1f317.mp4

I also use this to set my discord presence:

![demo discord image](https://github.com/seanbreckenridge/currently_listening/blob/main/.github/discord.png?raw=true)

## Install

Requires `python3.9+` and `go`

### `server`

The main server `./server/main.go` can be built with:

```bash
git clone https://github.com/seanbreckenridge/currently_listening
cd currently_listening
go build -o currently_listening_server ./server/main.go
cp ./currently_listening_server ~/.local/bin
```

Run `./currently_listening_server`:

```
GLOBAL OPTIONS:
   --port value      Port to listen on (default: 3030)
   --password value  Password to authenticate setting the currently playing song [$CURRENTLY_LISTENING_PASSWORD]
   --help, -h        show help
```

Set the `CURRENTLY_LISTENING_PASSWORD` environment variable to authenticate `POST` requests (so that only you can set what music you're listening to)

Accepts `POST` requests from other clients here to set/clear the currently playing song, and provides the `/ws` endpoint which broadcasts to other clients whenever there are changes

If you want to be able to use this from other devices/have this public, you need to host this on a server somewhere public.

I do so on my server with `nginx` under the `/currently_listening` path:

```conf
location /currently_listening/ {
  add_header "Access-Control-Allow-Origin"  *;
  proxy_http_version 1.1;
  proxy_set_header X-Cluster-Client-Ip $remote_addr;
  proxy_set_header Upgrade $http_upgrade;
  proxy_set_header Connection "upgrade";
  proxy_pass http://127.0.0.1:3030/;
}
```

---

The rest of the code here are clients which set the song I'm currently listening to, or which consume the websocket endpoint in some way (e.g., to set my discord presence)

### `listenbrainz_client`

Install (you can also use the `Makefile` here to build both `go` tools):

```bash
git clone https://github.com/seanbreckenridge/currently_listening
cd currently_listening
go build -o listenbrainz_client_poll ./listenbrainz_client/main.go
cp ./listenbrainz_client_poll ~/.local/bin
```

This polls the `playing-now` endpoint at [ListenBrainz](https://listenbrainz.org/) (like a open-source last-fm) every few seconds to fetch what I'm currently listening to.

Whenever it detects currently playing music/music finishes playing, it sends a request to `./server/main.go`. Similar to Lastfm, ListenBrainz is updated by scrobblers, like [Pano Scrobbler](https://play.google.com/store/apps/details?id=com.arn.scrobble&hl=en_US&gl=US) on my phone, or [WebScrobbler](https://web-scrobbler.com/) in my browser

```
GLOBAL OPTIONS:
   --password value               Password to authenticate setting the currently playing song [$CURRENTLY_LISTENING_PASSWORD]
   --listenbrainz-username value  ListenBrainz username [$LISTENBRAINZ_USERNAME]
   --server-url value             URL of the server to send the currently playing song to (default: "http://localhost:3030")
   --poll-interval value          Interval in seconds to poll ListenBrainz for currently playing song (default: 30)
   --debug                        Enable debug logging (default: false)
   --help, -h                     show help
```

This could run either on your local machine or remotely, but I prefer remotely as it means its always active -- even if I'm out somewhere listening on my phone it still works.

### `mpv_history_daemon`

This requires:

- <https://github.com/seanbreckenridge/mpv-history-daemon>
- <https://github.com/seanbreckenridge/mpv-sockets>

This is a pretty complex source with lots of moving parts, so to summarize:

```
                               /*********************/
                               /* mpv (application) */
                               /*********************/
                                       |
                                       ▼
                      /****************************************/
                      /*      mpv_sockets wrapper script      */
                      /* launches mpv with unique IPC sockets */
                      /****************************************/
                                       |
                                       ▼
        /*********************************************************************/
        /*                       mpv_history_daemon                          */
        /* connects to active mpv IPC sockets and saves to local JSON files. */
        /*   launched with the custom SocketDataServer class installed here, */
        /* this also sends the JSON to a local currently_listening_py server */
        /*********************************************************************/
                                       |
                                       ▼
     /*************************************************************************/
     /*              currently_listening_py server (run locally)              */
     /* uses my_feed/HPI to parse/filter the raw JSON from mpv_history_daemon */
     /*************************************************************************/
                                       |
                                       ▼
        /********************************************************************/
        /*                   main server (server/main.go)                   */
        /* recieves updates whenever mpv song changes/mpv is paused/resumes */
        /********************************************************************/
                                       |
                                       ▼
                    /*******************************************/
                    /* clients recieve broadcasts on websocket */
                    /*******************************************/
```

To install the python library/server here:

```bash
git clone https://github.com/seanbreckenridge/currently_listening
cd currently_listening/currently_listening_py
python3 -m pip install .
```

However (for now), you also need to setup [my_feed](https://github.com/seanbreckenridge/my_feed), which in turn requires [HPI](https://github.com/seanbreckenridge/HPI). That is used in the `currently_listening_py` server to process the blobs of JSON from `mpv_history_daemon` and filter to music (instead of including movies/TV shows as well). In my `~/.config/my/my/config/feed.py` I have:

```python
ignore_mpv_prefixes: set[str] = {
    "/home/sean/Repos/",
    "/home/sean/Downloads",
}

allow_mpv_prefixes: set[str] = {
    "/home/sean/Music/",
    "/home/data/media/music/",
    "/home/sean/Downloads/Sort/",
    "/Users/sean/Music",
}
```

To run, first start the `currently_listening_py` server, e.g.:

`currently_listening_py server --server-url https://.../currently_listening`

Then, run the `mpv_history_daemon` with the custom `SocketDataServer` class installed here

`mpv_history_daemon_restart ~/data/mpv --socket-class-qualname 'currently_listening_py.socket_data.SocketDataServer'`

That still saves all the data to `~/data/mpv`, in addition to `POST`ing the currently playing song to `currently_listening_py server` for further processing

### `discord-presence`

To setup your client ID, see [pypresence](https://qwertyquerty.github.io/pypresence/html/info/quickstart.html) docs, and set the `PRESENCE_CLIENT_ID` with your applications `ClientID`.

This must be run on your computer which the `discord` application active to connect with RPC, e.g.:

`currently_listening_py discord-presence --server-url wss://sean.fish/currently_listening/ws`

To comply with the discord API rate limit, this only updates every ~20 seconds, so you may notice some lag if you're constantly skipping songs with `mpv`

![demo discord image](https://github.com/seanbreckenridge/currently_listening/blob/main/.github/discord.png?raw=true)

### Adding new sources

TODO: expand more on the `POST` body/internals how one could create a new source
