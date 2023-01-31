const websocketUrl = Deno.env.get("WEBSOCKET_URL") || "ws://localhost:3030/ws";

const ws = new WebSocket(websocketUrl);

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
