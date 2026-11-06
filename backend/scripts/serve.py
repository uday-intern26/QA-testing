"""Keep the QA API listening on every network interface.

The process retries if the port is busy and starts again if the server exits,
so a sign-in task can leave it running for this computer.
"""

from __future__ import annotations

import os
import socket
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent
sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

os.environ.setdefault("DATA_DIR", str(ROOT / "data"))
os.environ.setdefault("DATABASE_URL", "sqlite:///" + (ROOT / "data" / "qa.sqlite3").as_posix())
os.environ.setdefault("FACE_MODEL_PATH", str(BACKEND / "models" / "face_landmarker.task"))
os.environ.setdefault("PLAYWRIGHT_HEADLESS", "false")


def bind_socket(port: int = 8000) -> socket.socket:
    while True:
        sock = socket.socket(socket.AF_INET6, socket.SOCK_STREAM)
        try:
            sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("::", port))
            sock.listen(2048)
            sock.set_inheritable(True)
            return sock
        except OSError:
            sock.close()
            time.sleep(2)


def main() -> None:
    import uvicorn

    while True:
        sock = bind_socket()
        config = uvicorn.Config("app.main:app", host="::", port=8000, log_level="info")
        try:
            uvicorn.Server(config).run(sockets=[sock])
        except Exception:
            time.sleep(2)


if __name__ == "__main__":
    main()
