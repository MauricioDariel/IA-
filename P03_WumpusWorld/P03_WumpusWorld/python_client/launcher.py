"""
launcher.py
===========
One-command orchestrator for the Wumpus World system.

Starts the Go server, waits for it to be ready, then runs either:
  - The text-mode agent (main.py)          → default
  - The visual web interface (visualizer.py) → with --visual

Usage
-----
    python launcher.py                     # 1 game, text mode
    python launcher.py --games 5           # 5 games, text mode
    python launcher.py --visual            # visual mode (opens browser)
    python launcher.py --visual --games 3  # 3 games in the visualizer
    python launcher.py --debug --games 3   # verbose text mode
"""

from __future__ import annotations

import atexit
import os
import signal
import socket
import subprocess
import sys
import time

# ---------------------------------------------------------------------------
# Paths (relative to this script's location)
# ---------------------------------------------------------------------------

_SCRIPT_DIR     = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT   = os.path.dirname(_SCRIPT_DIR)             # P03_WumpusWorld/
_SERVER_DIR     = _PROJECT_ROOT                             # server.go + game.go
_CLIENT_SCRIPT  = os.path.join(_SCRIPT_DIR, "main.py")
_VIS_SCRIPT     = os.path.join(_SCRIPT_DIR, "visualizer.py")

_SERVER_HOST = "localhost"
_SERVER_PORT = 8080
_STARTUP_TIMEOUT = 10        # max seconds to wait for the Go server


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _port_open(host: str, port: int) -> bool:
    """Return True if a TCP connection to host:port succeeds."""
    try:
        with socket.create_connection((host, port), timeout=1):
            return True
    except (ConnectionRefusedError, OSError):
        return False


def _wait_for_server(host: str, port: int, timeout: float) -> bool:
    """Block until the server accepts connections or timeout expires."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if _port_open(host, port):
            return True
        time.sleep(0.25)
    return False


def _kill_process(proc: subprocess.Popen | None) -> None:
    """Terminate a subprocess tree.  Safe to call multiple times or on None."""
    if proc is None or proc.poll() is not None:
        return
    try:
        if sys.platform == "win32":
            subprocess.call(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        else:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            proc.wait(timeout=3)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Main orchestrator
# ---------------------------------------------------------------------------

def main() -> None:
    # ---- Detect --visual flag (consumed here, rest forwarded) ----
    visual_mode = "--visual" in sys.argv
    forward_args = [a for a in sys.argv[1:] if a != "--visual"]

    server_proc: subprocess.Popen | None = None

    def cleanup() -> None:
        _kill_process(server_proc)

    atexit.register(cleanup)

    # ---- 1. Start or detect the Go server ----
    if _port_open(_SERVER_HOST, _SERVER_PORT):
        print(f"[launcher] Port {_SERVER_PORT} already in use — assuming Go server is running.")
    else:
        print(f"[launcher] Starting Go server in {_SERVER_DIR} ...")
        popen_kwargs: dict = dict(
            cwd=_SERVER_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
        )
        if sys.platform != "win32":
            popen_kwargs["preexec_fn"] = os.setsid

        server_proc = subprocess.Popen(
            ["go", "run", "server.go", "game.go"],
            **popen_kwargs,
        )

        print(f"[launcher] Waiting for server on port {_SERVER_PORT} ", end="", flush=True)
        if not _wait_for_server(_SERVER_HOST, _SERVER_PORT, _STARTUP_TIMEOUT):
            print(" FAILED")
            print(f"[launcher] ERROR: Go server did not start within {_STARTUP_TIMEOUT}s.")
            print("[launcher] Make sure 'go' is on your PATH and the server compiles.")
            _kill_process(server_proc)
            sys.exit(1)
        print(" OK")

    # ---- 2. Choose which client to run ----
    if visual_mode:
        script = _VIS_SCRIPT
        print(f"[launcher] Starting VISUAL mode (browser) ...")
    else:
        script = _CLIENT_SCRIPT
        print(f"[launcher] Starting TEXT mode (terminal agent) ...")

    agent_cmd = [sys.executable, script] + forward_args
    print(f"[launcher] Command: {' '.join(agent_cmd)}")
    print("=" * 60)

    try:
        result = subprocess.run(agent_cmd, cwd=_SCRIPT_DIR)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("\n[launcher] Ctrl+C received — shutting down.")
    finally:
        _kill_process(server_proc)
        print("[launcher] Go server stopped. Bye!")


if __name__ == "__main__":
    main()
