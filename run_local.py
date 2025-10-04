"""Local development runner for SimpleSpecs."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
import webbrowser
from pathlib import Path
from typing import Iterable


ROOT = Path(__file__).resolve().parent
FRONTEND_DIR = ROOT / "frontend"
FRONTEND_URL = "http://127.0.0.1:3000"


def _spawn(command: Iterable[str]) -> subprocess.Popen[str]:
    """Launch ``command`` inheriting the current stdio."""

    return subprocess.Popen(list(command), text=True)


def _terminate(process: subprocess.Popen[str]) -> None:
    """Attempt a graceful shutdown of ``process``."""

    if process.poll() is None:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _wait_for_port(host: str, port: int, timeout: float = 20) -> bool:
    """Poll ``host``/``port`` until a service is accepting connections."""

    deadline = time.time() + timeout
    while time.time() < deadline:
        with socket.socket() as sock:
            sock.settimeout(1)
            try:
                sock.connect((host, port))
            except OSError:
                time.sleep(0.25)
                continue
            else:
                return True
    return False


def _open_preview(url: str) -> None:
    """Attempt to open ``url`` in the user's default browser."""

    if os.environ.get("SIMPLESPECS_NO_BROWSER"):
        return

    try:
        opened = webbrowser.open(url, new=2)
    except Exception as exc:  # pragma: no cover - best effort UX only
        print(f"Unable to launch browser automatically: {exc}", file=sys.stderr)
        return

    if opened:
        print(f"Opened preview in your browser: {url}")
    else:
        print(f"Preview available at {url}")


def main() -> int:
    """Run the backend and static frontend for local development."""

    if not FRONTEND_DIR.exists():
        msg = "Frontend directory not found. Expected at: {path}"
        raise RuntimeError(msg.format(path=FRONTEND_DIR))

    backend_cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "backend.main:create_app",
        "--factory",
        "--host",
        "127.0.0.1",
        "--port",
        "8000",
        "--reload",
    ]
    frontend_cmd = [
        sys.executable,
        "-m",
        "http.server",
        "3000",
        "--bind",
        "127.0.0.1",
        "--directory",
        str(FRONTEND_DIR),
    ]

    processes: list[tuple[str, subprocess.Popen[str]]] = []

    try:
        print("Starting backend on http://127.0.0.1:8000 ...", flush=True)
        processes.append(("backend", _spawn(backend_cmd)))

        print("Starting frontend on http://127.0.0.1:3000 ...", flush=True)
        processes.append(("frontend", _spawn(frontend_cmd)))

        if not _wait_for_port("127.0.0.1", 8000):
            print(
                "Backend did not report ready within 20s; check logs above for issues.",
                file=sys.stderr,
            )

        if _wait_for_port("127.0.0.1", 3000):
            _open_preview(FRONTEND_URL)
        else:
            print(f"Preview available at {FRONTEND_URL}")

        while True:
            for name, process in processes:
                return_code = process.poll()
                if return_code is not None:
                    if return_code != 0:
                        print(f"{name} exited with status {return_code}", file=sys.stderr)
                        return return_code
                    return 0
            time.sleep(0.25)
    except KeyboardInterrupt:
        print("Received interrupt, shutting down...", flush=True)
        return 0
    finally:
        for _, process in processes:
            _terminate(process)


if __name__ == "__main__":
    raise SystemExit(main())
