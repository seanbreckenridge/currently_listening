.DEFAULT_GOAL := install
TARGET_BIN="${HOME}/.local/bin"

install: server_build listenbrainz_client_build
	mv -v ./currently_listening_server $(TARGET_BIN)
	mv -v ./listenbrainz_client $(TARGET_BIN)

server_build:
	go build -o currently_listening_server ./server/main.go

listenbrainz_client_build:
	go build -o listenbrainz_client ./listenbrainz_client/main.go
