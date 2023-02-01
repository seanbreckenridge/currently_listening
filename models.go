package currently_listening

// struct for setting the currently playing song
type SetListening struct {
	Artist      string `json:"artist"`
	Album       string `json:"album"`
	Title       string `json:"title"`
	StartedAt   int64  `json:"started_at"`
	Base64Image string `json:"base64_image"`
}

type ClearListening struct {
	EndedAt int64 `json:"ended_at"`
}
