import uvicorn  # type: ignore[import]
from fastapi import FastAPI


def server(
    *, port: int, remote_server: str, server_password: str, debug: bool = True
) -> None:

    app = FastAPI()

    @app.get("/ping")
    def _ping() -> str:
        return "pong"

    from .socket_data import create_router, create_manager

    create_manager(remote_server, server_password)

    app.include_router(create_router())

    uvicorn.run(app, host="127.0.0.1", port=port, debug=debug)  # type: ignore
