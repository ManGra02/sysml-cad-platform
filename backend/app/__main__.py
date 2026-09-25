"""Startet das Backend -- ausschliesslich auf Loopback.

    uv run python -m app            # Normalbetrieb
    uv run python -m app --reload   # Entwicklung

``--host 0.0.0.0``, "damit jemand anderes das Frontend testen kann", ist der
wahrscheinlichste reale Sicherheitsvorfall dieses Projekts. Deshalb gibt es
hier keinen Host-Schalter; wer von einem anderen Rechner zugreifen muss, nimmt
``ssh -L 8000:127.0.0.1:8000``.
"""

import argparse
import os

import uvicorn

from app import config


def main():
    parser = argparse.ArgumentParser(prog="python -m app")
    parser.add_argument("--reload", action="store_true", help="bei Codeaenderung neu laden")
    parser.add_argument("--dev", action="store_true",
                        help="Vite-Dev-Server (Port 5173) als Herkunft erlauben")
    args = parser.parse_args()

    if args.dev:
        os.environ["PLATFORM_DEV"] = "1"

    uvicorn.run(
        "app.main:app",
        host=config.HOST,  # fest 127.0.0.1
        port=config.PORT,  # fest 8000 -- lauter Fehlschlag, wenn belegt
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
