import argparse

import uvicorn

from .config import HOST, PORT


def main() -> None:
    parser = argparse.ArgumentParser(prog="clipawesome", description="ClipAwesome API server")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--reload", action="store_true", help="auto-reload on code changes (development)")
    args = parser.parse_args()
    uvicorn.run("clipawesome.api.app:app", host=args.host, port=args.port, reload=args.reload, log_level="info")


if __name__ == "__main__":
    main()
