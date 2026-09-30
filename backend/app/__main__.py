"""Starts the backend -- on loopback only.

    uv run python -m app            # normal operation
    uv run python -m app --reload   # development

``--host 0.0.0.0``, "so someone else can test the frontend", is the most
likely real-world security incident of this project. That is why there is
no host switch here; anyone who needs access from another machine uses
``ssh -L 8000:127.0.0.1:8000``.
"""

import argparse
import os

import uvicorn

from app import config


def main():
    parser = argparse.ArgumentParser(prog="python -m app")
    parser.add_argument("--reload", action="store_true", help="reload on code changes")
    parser.add_argument("--dev", action="store_true",
                        help="allow the Vite dev server (port 5173) as an origin")
    args = parser.parse_args()

    if args.dev:
        os.environ["PLATFORM_DEV"] = "1"

    uvicorn.run(
        "app.main:app",
        host=config.HOST,  # fixed at 127.0.0.1
        port=config.PORT,  # fixed at 8000 -- fails loudly if in use
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
