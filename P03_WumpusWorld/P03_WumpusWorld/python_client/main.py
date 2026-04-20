"""
main.py
=======
HTTP client and game loop for the DPLL-based Wumpus World Python agent.

This program connects to the Go server (server.go / game.go) via HTTP/JSON:

    POST /game/new                   → { "gameId": "...", "perception": {...} }
    POST /game/{gameId}/action  ← { "action": "Forward|TurnLeft|TurnRight|
                                                Shoot|Grab|Climb" }
                                     → Perception JSON

Usage
-----
    # Start the Go server first (from the project root):
    #   go run server.go game.go
    #
    # Then, in another terminal (inside python_client/):
    #   pip install requests          (one-time install)
    #
    # Play one full autonomous game:
    python main.py
    
    # Play 5 games and show a summary:
    python main.py --games 5
    
    # Run a single manual command and exit:
    python main.py --cmd new
    python main.py --cmd forward
    python main.py --cmd left
    python main.py --cmd right
    python main.py --cmd shoot
    
    # Use a different server URL:
    python main.py --server http://192.168.1.10:8080 --games 3

Options
-------
  --server  Base URL of the Wumpus World server  [default: http://localhost:8080]
  --games   Number of complete games to play     [default: 1]
  --cmd     Single one-shot command (new|forward|left|right|shoot)
  --delay   Seconds to wait between steps        [default: 0]
  --debug   Enable verbose DEBUG logging
"""

from __future__ import annotations

import argparse
import logging
import sys
import time
from typing import Optional, Tuple

import requests

from agent import Agent

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------

class Transport:
    """Thin wrapper around the HTTP calls to the Wumpus World server."""

    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.session  = requests.Session()
        self.timeout  = timeout

    def start_new_game(self) -> Tuple[str, dict]:
        """POST /game/new → (game_id, perception_dict)."""
        resp = self.session.post(
            f"{self.base_url}/game/new",
            timeout=self.timeout,
        )
        resp.raise_for_status()
        data = resp.json()
        return data["gameId"], data["perception"]

    def send_action(self, game_id: str, action: str, dpll_log: str = "") -> dict:
        """POST /game/{game_id}/action with body {action, dpll_log} → perception_dict."""
        payload = {"action": action}
        if dpll_log:
            payload["dpll_log"] = dpll_log
        resp = self.session.post(
            f"{self.base_url}/game/{game_id}/action",
            json=payload,
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _describe_perception(p: dict) -> str:
    """Return a compact human-readable rendering of a perception dict."""
    flags = []
    if p.get("stench"):  flags.append("stench")
    if p.get("breeze"):  flags.append("breeze")
    if p.get("glitter"): flags.append("glitter")
    if p.get("bump"):    flags.append("bump")
    if p.get("scream"):  flags.append("scream")
    sensor_str = ",".join(flags) if flags else "(nothing)"
    return f"score={p.get('score', 0)}  sensors=[{sensor_str}]"


def _game_over_suffix(p: dict) -> str:
    if not p.get("gameOver"):
        return ""
    return f"  [GAME OVER: {p.get('message', '')}]"


# ---------------------------------------------------------------------------
# One full autonomous game
# ---------------------------------------------------------------------------

MAX_STEPS = 400   # safety valve to avoid infinite loops


def play_one(transport: Transport, delay: float = 0.0) -> dict:
    """
    Run one complete game autonomously using the DPLL agent.
    Returns the final perception dict.
    """
    game_id, perception = transport.start_new_game()
    log.info("=== New game %s ===", game_id)
    log.info("  initial: %s", _describe_perception(perception))

    agent = Agent(game_id)
    agent.update_knowledge(perception)

    step = 0
    while step < MAX_STEPS and not perception.get("gameOver"):
        step += 1
        action = agent.decide_action()
        log.info(
            "[step %3d] at (%d,%d) facing %s → %s",
            step, agent.x, agent.y,
            {0:"East",1:"North",2:"West",3:"South"}.get(agent.dir, "?"),
            action,
        )

        perception = transport.send_action(game_id, action, dpll_log=agent.dpll_log)
        agent.update_state(action, perception)
        agent.update_knowledge(perception)

        log.info(
            "           → %s%s",
            _describe_perception(perception),
            _game_over_suffix(perception),
        )

        if delay > 0:
            time.sleep(delay)

    log.info(
        "=== Game %s finished: %s (score %d) ===",
        game_id,
        perception.get("message", ""),
        perception.get("score", 0),
    )
    return perception


# ---------------------------------------------------------------------------
# One-shot manual command (for assignment requirement demo)
# ---------------------------------------------------------------------------

_CMD_MAP = {
    "new":      None,
    "forward":  "Forward",
    "left":     "TurnLeft",
    "right":    "TurnRight",
    "shoot":    "Shoot",
}


def run_one_shot(transport: Transport, command: str) -> None:
    """
    Start a fresh game and execute a single action, printing the result.
    Used to demonstrate the five individual commands required by the assignment.
    """
    game_id, perception = transport.start_new_game()
    print(f"\n{'='*60}")
    print(f"Started game: {game_id}")
    print(f"Initial:  {_describe_perception(perception)}")

    action: Optional[str] = _CMD_MAP.get(command.lower())
    if action is None:
        print("(no action sent – only 'new game' was requested)")
        return

    result = transport.send_action(game_id, action)
    print(f"Action:   {action}")
    print(f"Result:   {_describe_perception(result)}{_game_over_suffix(result)}")
    print(f"{'='*60}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Wumpus World DPLL Python client.\n\n"
            "Without --cmd the agent plays --games complete games autonomously.\n"
            "With --cmd it starts a new game, executes that one command, and exits."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--server",
        default="http://localhost:8080",
        help="Base URL of the Wumpus World server (default: http://localhost:8080)",
    )
    parser.add_argument(
        "--games",
        type=int,
        default=1,
        help="Number of complete games to play autonomously (default: 1)",
    )
    parser.add_argument(
        "--cmd",
        metavar="COMMAND",
        help=(
            "Run one manual command and exit. "
            "Choices: new | forward | left | right | shoot"
        ),
    )
    parser.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to wait between steps (default: 0)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable verbose DEBUG logging",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()

    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    transport = Transport(args.server)

    # Verify server connectivity
    try:
        transport.session.get(args.server, timeout=5)
    except requests.ConnectionError:
        print(
            f"\n[ERROR] Cannot reach the Wumpus World server at {args.server}.\n"
            "Make sure the Go server is running:\n"
            "  cd <project-root>\n"
            "  go run server.go game.go\n",
            file=sys.stderr,
        )
        sys.exit(1)

    # ---- One-shot command mode ----
    if args.cmd:
        cmd_lower = args.cmd.lower()
        if cmd_lower not in _CMD_MAP:
            print(
                f"[ERROR] Unknown command '{args.cmd}'. "
                f"Choose from: {', '.join(_CMD_MAP)}",
                file=sys.stderr,
            )
            sys.exit(1)
        run_one_shot(transport, cmd_lower)
        return

    # ---- Autonomous DPLL agent mode ----
    wins        = 0
    losses      = 0
    total_score = 0

    for i in range(1, args.games + 1):
        log.info("--- Starting game %d / %d ---", i, args.games)
        final = play_one(transport, delay=args.delay)
        total_score += final.get("score", 0)
        if "victory" in final.get("message", "").lower():
            wins += 1
        else:
            losses += 1

    avg = total_score / args.games if args.games else 0
    print("\n" + "=" * 60)
    print(f"  Summary: {args.games} game(s) played")
    print(f"  Wins:    {wins}")
    print(f"  Losses:  {losses}")
    print(f"  Average score: {avg:.1f}")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    main()
