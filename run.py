#!/usr/bin/env python3
"""Convenience launcher for the SimpleSpecs frontend and backend services."""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Tuple, Type

BACKEND_APP = "backend.main:app"
DEFAULT_BACKEND_HOST = "0.0.0.0"
DEFAULT_BACKEND_PORT = 7600
DEFAULT_FRONTEND_HOST = "0.0.0.0"
DEFAULT_FRONTEND_PORT = 3600


def _create_frontend_handler(directory: Path) -> Type[SimpleHTTPRequestHandler]:
    """Return a HTTP handler that serves the compiled frontend bundle."""

    class FrontendHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(directory), **kwargs)

        def translate_path(self, path: str) -> str:  # noqa: D401 - inherited docstring
            """Map `/` to `index.html` and `/static/*` to the frontend directory."""

            stripped = path.split("?", 1)[0].split("#", 1)[0]
            if stripped in {"", "/"}:
                stripped = "/index.html"
            elif stripped.startswith("/static/"):
                stripped = stripped[len("/static") :]
                if stripped in {"", "/"}:
                    stripped = "/index.html"
            return SimpleHTTPRequestHandler.translate_path(self, stripped)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A003 - match base signature
            sys.stdout.write("[frontend] " + (format % args) + "\n")

    return FrontendHandler


def parse_args() -> argparse.Namespace:
    """Parse command line arguments for the launcher script."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--backend-host",
        default=os.getenv("BACKEND_HOST", DEFAULT_BACKEND_HOST),
        help="Host interface for the backend server.",
    )
    parser.add_argument(
        "--backend-port",
        type=int,
        default=int(os.getenv("BACKEND_PORT", DEFAULT_BACKEND_PORT)),
        help="Port for the backend server.",
    )
    parser.add_argument(
        "--frontend-host",
        default=os.getenv("FRONTEND_HOST", DEFAULT_FRONTEND_HOST),
        help="Host interface for the frontend server.",
    )
    parser.add_argument(
        "--frontend-port",
        type=int,
        default=int(os.getenv("FRONTEND_PORT", DEFAULT_FRONTEND_PORT)),
        help="Port for the frontend server.",
    )
    parser.add_argument(
        "--log-level",
        default=os.getenv("LOG_LEVEL", "info"),
        help="Log level passed to Uvicorn.",
    )
    return parser.parse_args()


def launch_backend(host: str, port: int, log_level: str) -> subprocess.Popen[str]:
    """Start the backend FastAPI application via Uvicorn."""

    env = os.environ.copy()
    env.setdefault("HOST", host)
    env.setdefault("PORT", str(port))
    env.setdefault("LOG_LEVEL", log_level)

    command = [
        sys.executable,
        "-m",
        "uvicorn",
        BACKEND_APP,
        "--host",
        host,
        "--port",
        str(port),
        "--log-level",
        log_level,
    ]
    process = subprocess.Popen(command, env=env)
    sys.stdout.write(f"[backend] Started uvicorn on {host}:{port} (PID {process.pid}).\n")
    return process


def launch_frontend(host: str, port: int, directory: Path) -> Tuple[ThreadingHTTPServer, threading.Thread]:
    """Start the static frontend HTTP server in a background thread."""

    handler = _create_frontend_handler(directory)
    server = ThreadingHTTPServer((host, port), handler)

    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": 0.5}, daemon=True)
    thread.start()
    sys.stdout.write(f"[frontend] Serving {directory} on {host}:{port}.\n")
    return server, thread


def shutdown_backend(process: subprocess.Popen[str]) -> None:
    """Terminate the backend process gracefully."""

    if process.poll() is not None:
        return

    process.terminate()
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def shutdown_frontend(server: ThreadingHTTPServer, thread: threading.Thread) -> None:
    """Stop the frontend server and wait for its worker thread."""

    server.shutdown()
    thread.join(timeout=5)


def main() -> None:
    args = parse_args()
    frontend_dir = Path(__file__).resolve().parent / "frontend"
    if not frontend_dir.exists():
        raise SystemExit(f"Frontend directory not found: {frontend_dir}")

    shutdown_event = threading.Event()

    def _request_shutdown(signum: int, _frame: object) -> None:
        sys.stdout.write(f"[run] Received signal {signum}, shutting down...\n")
        shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, _request_shutdown)

    backend_process = launch_backend(args.backend_host, args.backend_port, args.log_level)
    frontend_server, frontend_thread = launch_frontend(args.frontend_host, args.frontend_port, frontend_dir)

    sys.stdout.write("[run] Application started. Press Ctrl+C to stop.\n")

    try:
        while not shutdown_event.is_set():
            if backend_process.poll() is not None:
                sys.stdout.write("[run] Backend process exited unexpectedly.\n")
                shutdown_event.set()
                break
            time.sleep(0.5)
    finally:
        shutdown_frontend(frontend_server, frontend_thread)
        shutdown_backend(backend_process)
        sys.stdout.write("[run] Shutdown complete.\n")


if __name__ == "__main__":
    main()
