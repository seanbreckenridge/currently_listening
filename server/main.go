package main

import (
	"encoding/json"
	"fmt"
	"github.com/olahol/melody"
	"github.com/seanbreckenridge/currently_listening"
	"github.com/urfave/cli/v2"
	"log"
	"net/http"
	"os"
	"sync"
)

type CurrentlyListeningResponse struct {
	Song    *currently_listening.SetListening `json:"song"`
	Playing bool                              `json:"playing"`
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
	var currentlyListeningSong *currently_listening.SetListening
	var currentTimeStamp *int64
	var isCurrentlyPlaying bool

	currentlyListeningJSON := func() ([]byte, error) {
		songBytes, err := json.Marshal(
			WebsocketResponse{
				MsgType: "currently-listening",
				Data: CurrentlyListeningResponse{
					Song:    currentlyListeningSong,
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
			if cur, err := currentlyListeningJSON(); err == nil {
				s.Write(cur)
			} else {
				fmt.Println("Error marshalling currently listening song to JSON")
				s.Write([]byte("Error converting currently listening song to JSON"))
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
		w.Write([]byte("Error converting currently listening song to JSON"))
	}

	http.HandleFunc("/set-listening", func(w http.ResponseWriter, r *http.Request) {
		if !authdPost(w, r) {
			return
		}

		// parse body
		var cur currently_listening.SetListening
		err := json.NewDecoder(r.Body).Decode(&cur)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			w.Write([]byte("error parsing JSON body"))
			return
		}

		// check if currently playing song is newer
		if currentlyListeningSong != nil && currentTimeStamp != nil && cur.StartedAt < *currentTimeStamp {
			msg := fmt.Sprintf("cannot set currently playing song, started before latest known timestamp (started at %d, latest timestamp %d)", cur.StartedAt, *currentTimeStamp)
			fmt.Println(msg)
			w.WriteHeader(http.StatusBadRequest)
			w.Write([]byte(msg))
			return
		}

		// set currently playing
		lock.Lock()
		currentlyListeningSong = &cur
		currentTimeStamp = &cur.StartedAt
		isCurrentlyPlaying = true
		lock.Unlock()

		if sendBody, err := currentlyListeningJSON(); err == nil {
			// broadcast to all clients
			m.Broadcast(sendBody)
			// respond to POST request
			msg := fmt.Sprintf("Set currently playing song to Artist: '%s', Album: '%s', Title: '%s', Image '%s'", cur.Artist, cur.Album, cur.Title, cur.Base64Image[0:10])
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

		// parse body
		var cur currently_listening.ClearListening
		err := json.NewDecoder(r.Body).Decode(&cur)
		if err != nil {
			w.WriteHeader(http.StatusInternalServerError)
			w.Write([]byte("error parsing JSON body"))
			return
		}

		// check if clear-playing request is newer than current timestamp
		if currentTimeStamp != nil && cur.EndedAt < *currentTimeStamp {
			msg := fmt.Sprintf("cannot clear currently playing song, started before latest known timestamp (started at %d, latest timestamp %d)", cur.EndedAt, *currentTimeStamp)
			fmt.Println(msg)
			w.WriteHeader(http.StatusBadRequest)
			w.Write([]byte(msg))
			return
		}

		// unset currently playing
		lock.Lock()
		currentlyListeningSong = nil
		currentTimeStamp = &cur.EndedAt
		isCurrentlyPlaying = false
		lock.Unlock()

		if sendBody, err := currentlyListeningJSON(); err == nil {
			// broadcast to all clients
			m.Broadcast(sendBody)
			// respond to POST request
			msg := "Unset currently listening song"
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
				Usage:    "Password to authenticate setting the currently listening song",
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
