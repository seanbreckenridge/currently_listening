const websocketUrl = Deno.env.get("WEBSOCKET_URL") || "ws://localhost:3030/ws";

function connect() {
  let ws = new WebSocket(websocketUrl);

  ws.onopen = () => {
    console.log("Connected to websocket server");
    ws.send("currently-listening");
  };

  ws.onmessage = (event) => {
    console.log(
      "Received message from websocket server:",
      JSON.parse(event?.data ?? "{}", null, 2)
    );
  };

  ws.onclose = () => {
    console.log("Disconnected from websocket server");
    // reconnect
    setTimeout(() => {
      console.log("Reconnecting to websocket server");
      connect();
    }, 1000);
  };
}

connect();
