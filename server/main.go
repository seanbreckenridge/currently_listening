package main

import (
	"encoding/json"
	"fmt"
	"github.com/olahol/melody"
	"github.com/urfave/cli/v2"
	"log"
	"net/http"
	"os"
	"sync"
)

// struct for setting the currently playing song
type CurrentlyPlaying struct {
	Artist    string `json:"artist"`
	Album     string `json:"album"`
	Title     string `json:"title"`
	StartedAt int    `json:"started_at"`
}

type CurrentlyPlayingResponse struct {
	Song    *CurrentlyPlaying `json:"song"`
	Playing bool              `json:"playing"`
}

type WebsocketResponse struct {
	MsgType string      `json:"msg_type"`
	Data    interface{} `json:"data"`
}

func server(port int, password string) {
	m := melody.New()
	m.HandleConnect(func(s *melody.Session) {
		log.Printf("Opened connection from %s\n", s.Request.RemoteAddr)
	})

	m.HandleDisconnect(func(s *melody.Session) {
		log.Printf("Closed connection from %s\n", s.Request.RemoteAddr)
	})

	lock := sync.RWMutex{}

	// global state
	var currentlyPlayingSong *CurrentlyPlaying
	var isCurrentlyPlaying bool

	currentlyPlayingJSON := func() ([]byte, error) {
		songBytes, err := json.Marshal(
			WebsocketResponse{
				MsgType: "currently-listening",
				Data: CurrentlyPlayingResponse{
					Song:    currentlyPlayingSong,
					Playing: isCurrentlyPlaying,
				},
			},
		)
		if err != nil {
			return nil, err
		}
		return songBytes, nil
	}

	m.HandleMessage(func(s *melody.Session, msg []byte) {
		switch string(msg) {
		case "currently-listening":
			if cur, err := currentlyPlayingJSON(); err == nil {
				s.Write(cur)
			} else {
				fmt.Println("Error marshalling currently playing song to JSON")
				s.Write([]byte("Error converting currently playing song to JSON"))
			}
		case "ping":
			jsonBytes, err := json.Marshal(
				WebsocketResponse{
					MsgType: "pong",
					Data:    nil,
				},
			)
			if err != nil {
				log.Fatal(err)
			}
			s.Write(jsonBytes)
		default:
			fmt.Printf("Unknown message: %s\n", string(msg))
		}
	})

	http.HandleFunc("/ws", func(w http.ResponseWriter, r *http.Request) {
		m.HandleRequest(w, r)
	})

	authdPost := func(w http.ResponseWriter, r *http.Request) bool {
		if r.Method != http.MethodPost {
			w.WriteHeader(http.StatusMethodNotAllowed)
			w.Write([]byte("only POST requests are allowed"))
			return false
		}

		if r.Header.Get("password") != password {
			w.WriteHeader(http.StatusUnauthorized)
			w.Write([]byte("invalid password"))
			return false
		}

		return true
	}

	handleError := func(w http.ResponseWriter, err error) {
		fmt.Printf("Error: %s\n", err.Error())
		w.WriteHeader(http.StatusInternalServerError)
		w.Write([]byte("Error converting currently playing song to JSON"))
	}

	http.HandleFunc("/set-listening", func(w http.ResponseWriter, r *http.Request) {
		if !authdPost(w, r) {
			return
		}

		// parse body to CurrentlyPlaying
		var cur CurrentlyPlaying
		err := json.NewDecoder(r.Body).Decode(&cur)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			w.Write([]byte("error parsing JSON body"))
			return
		}

		// set currently playing
		lock.Lock()
		currentlyPlayingSong = &cur
		isCurrentlyPlaying = true
		lock.Unlock()

		if sendBody, err := currentlyPlayingJSON(); err == nil {
			// broadcast to all clients
			m.Broadcast(sendBody)
			// respond to client
			msg := fmt.Sprintf("Set currently playing song to Artist: %s, Album: %s, title: %s", cur.Artist, cur.Album, cur.Title)
			fmt.Println(msg)
			w.Write([]byte(msg))
		} else {
			handleError(w, err)
		}
	})

	http.HandleFunc("/clear-listening", func(w http.ResponseWriter, r *http.Request) {
		if !authdPost(w, r) {
			return
		}

		// unset currently playing
		lock.Lock()
		currentlyPlayingSong = nil
		isCurrentlyPlaying = false
		lock.Unlock()

		if sendBody, err := currentlyPlayingJSON(); err == nil {
			// broadcast to all clients
			m.Broadcast(sendBody)
			// respond to client
			msg := "Unset currently playing song"
			fmt.Println(msg)
			w.Write([]byte(msg))
		} else {
			handleError(w, err)
		}
	})

	fmt.Printf("Listening on port %d\n", port)
	http.ListenAndServe(fmt.Sprintf(":%d", port), nil)
}

func main() {

	app := &cli.App{
		Name:  "currently-listening",
		Usage: "Get the song I'm currently listening to",
		Flags: []cli.Flag{
			&cli.IntFlag{
				Name:  "port",
				Value: 3030,
				Usage: "Port to listen on",
			},
			&cli.StringFlag{
				Name:     "password",
				Value:    "",
				Usage:    "Password to authenticate setting the currently playing song",
				Required: true,
				EnvVars:  []string{"CURRENTLY_LISTENING_PASSWORD"},
			},
		},
		Action: func(c *cli.Context) error {
			port := c.Int("port")
			pw := c.String("password")
			server(port, pw)
			return nil
		},
	}

	if err := app.Run(os.Args); err != nil {
		log.Fatal(err)
	}
}
