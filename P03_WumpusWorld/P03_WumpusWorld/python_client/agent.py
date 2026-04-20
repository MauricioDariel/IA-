"""
agent.py
========
Decision-making and path-planning for the Wumpus World DPLL agent.

The agent combines DPLL-based inference (KB from kb.py) with a BFS on the
space of (x, y, direction) triples to turn high-level intentions (e.g.
"reach cell (2, 3)") into concrete action sequences for the server:
    Forward | TurnLeft | TurnRight | Shoot | Grab | Climb

Strategy (in priority order):
  1. Grab  – if glitter is visible and gold not yet held.
  2. Climb – if gold is held and agent is at (0, 0).
  3. Explore – move to the nearest provably-safe unvisited cell.
  4. Shoot  – if the Wumpus location is pinned, line up and fire.
  5. Retreat – walk home and Climb when no safe frontier exists.

Directions match the server encoding defined in game.go:
  East=0  North=1  West=2  South=3
"""

from __future__ import annotations

import logging
from collections import deque
from typing import Dict, List, Optional, Set, Tuple

from kb import KB, GRID_SIZE

log = logging.getLogger(__name__)

# Direction constants matching the server
EAST  = 0
NORTH = 1
WEST  = 2
SOUTH = 3

DIR_NAMES = {EAST: "East", NORTH: "North", WEST: "West", SOUTH: "South"}

# A state is the full agent pose: (x, y, direction)
State = Tuple[int, int, int]


# ---------------------------------------------------------------------------
# Pure navigation helpers
# ---------------------------------------------------------------------------

def _apply_action(s: State, action: str) -> State:
    """Return the pose reached by executing *action* from pose *s*."""
    x, y, d = s
    if action == "Forward":
        nx, ny = x, y
        if   d == EAST:  nx += 1
        elif d == NORTH: ny += 1
        elif d == WEST:  nx -= 1
        elif d == SOUTH: ny -= 1
        if 0 <= nx < GRID_SIZE and 0 <= ny < GRID_SIZE:
            return (nx, ny, d)
        return s   # bump – pose unchanged
    elif action == "TurnLeft":
        return (x, y, (d + 1) % 4)
    elif action == "TurnRight":
        return (x, y, (d - 1 + 4) % 4)
    return s


def _find_path(
    frm: State,
    to_x: int,
    to_y: int,
    safe: Set[Tuple[int, int]],
) -> Optional[List[str]]:
    """
    BFS over (x, y, direction) poses to find the shortest action sequence
    from *frm* that brings the agent to cell (to_x, to_y) while only
    stepping through cells in *safe*.
    Returns the action list, or None if unreachable.
    """
    if frm[0] == to_x and frm[1] == to_y:
        return []

    # The starting cell is always walkable
    walkable = safe | {(frm[0], frm[1])}

    visited: Set[State] = {frm}
    queue: deque = deque([(frm, [])])

    while queue:
        cur_state, actions = queue.popleft()
        for action in ("Forward", "TurnLeft", "TurnRight"):
            ns = _apply_action(cur_state, action)
            if action == "Forward":
                if ns == cur_state:          # bump
                    continue
                if (ns[0], ns[1]) not in walkable:
                    continue
            if ns in visited:
                continue
            visited.add(ns)
            new_actions = actions + [action]
            if ns[0] == to_x and ns[1] == to_y:
                return new_actions
            queue.append((ns, new_actions))

    return None   # unreachable


def _turns_to(frm: int, to: int) -> List[str]:
    """Return the shorter TurnLeft / TurnRight sequence from heading *frm* to *to*."""
    if frm == to:
        return []
    left_steps  = (to - frm + 4) % 4
    right_steps = (frm - to + 4) % 4
    if left_steps <= right_steps:
        return ["TurnLeft"] * left_steps
    return ["TurnRight"] * right_steps


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    """
    DPLL-powered Wumpus World player.

    Maintains the current pose, inventory, knowledge base and a queue of
    pre-planned actions.
    """

    def __init__(self, game_id: str) -> None:
        self.x:   int = 0
        self.y:   int = 0
        self.dir: int = EAST

        self.has_arrow: bool = True
        self.has_gold:  bool = False
        self.wumpus_killed: bool = False

        self.visited:    Set[Tuple[int, int]] = set()
        self.safe_known: Set[Tuple[int, int]] = {(0, 0)}

        self.kb:           KB         = KB()
        self.action_queue: List[str]  = []

        self._last_p: dict = {}
        self.game_id = game_id
        self._dpll_log: str = ""   # live reasoning log sent to the server

    # ------------------------------------------------------------------
    # State & knowledge update (called after every server response)
    # ------------------------------------------------------------------

    def update_state(self, action: str, perception: dict) -> None:
        """Adjust pose and inventory after executing *action*."""
        if action == "Forward":
            if perception.get("bump"):
                self.action_queue.clear()   # stale plan – discard
            else:
                if   self.dir == EAST:  self.x += 1
                elif self.dir == NORTH: self.y += 1
                elif self.dir == WEST:  self.x -= 1
                elif self.dir == SOUTH: self.y -= 1
        elif action == "TurnLeft":
            self.dir = (self.dir + 1) % 4
        elif action == "TurnRight":
            self.dir = (self.dir - 1 + 4) % 4
        elif action == "Grab":
            self.has_gold = True
        elif action == "Shoot":
            self.has_arrow = False

    def update_knowledge(self, perception: dict) -> None:
        """Integrate a new perception into the KB and refresh safe cells."""
        self._last_p = perception

        # Scream → Wumpus is dead
        if perception.get("scream") and not self.wumpus_killed:
            self.wumpus_killed = True
            self.kb.kill_wumpus()
            self.action_queue.clear()  # Force immediate replanning
            log.info("[KB] Scream heard → Wumpus killed, ¬W(·,·) added to KB")

        pos = (self.x, self.y)
        if pos not in self.visited:
            self.visited.add(pos)
            self.safe_known.add(pos)
            self.kb.add_visit_observation(
                self.x, self.y,
                perception.get("stench", False),
                perception.get("breeze", False),
            )

        self._refresh_safe_known()

    def _refresh_safe_known(self) -> None:
        """Ask DPLL about every unknown cell and promote proven-safe ones."""
        newly_safe: list = []
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                cell = (x, y)
                if cell in self.safe_known:
                    continue
                if self.kb.is_safe(x, y):
                    self.safe_known.add(cell)
                    newly_safe.append(cell)
                    log.info("[DPLL] proved safe: (%d, %d)", x, y)

        # --- Build live DPLL log for the server ---
        self._dpll_log = self._build_dpll_log(newly_safe)

    def _build_dpll_log(self, newly_safe: list) -> str:
        """
        Construct a human-readable string describing the agent's current
        reasoning state.  This is sent to the Go server as ``dpll_log``.
        """
        parts: list = []
        p = self._last_p

        # 1. What was perceived
        sensors = []
        if p.get("stench"):  sensors.append("Stench")
        if p.get("breeze"):  sensors.append("Breeze")
        if p.get("glitter"): sensors.append("Glitter")
        if p.get("bump"):    sensors.append("Bump")
        if p.get("scream"):  sensors.append("Scream")
        if sensors:
            parts.append(f"Perceived [{','.join(sensors)}] at ({self.x},{self.y})")
        else:
            parts.append(f"Perceived [nothing] at ({self.x},{self.y})")

        # 2. What DPLL proved safe this turn
        if newly_safe:
            cells = ", ".join(f"({x},{y})" for x, y in newly_safe)
            parts.append(f"DPLL proved safe: {cells}")

        # 3. Wumpus status
        if self.wumpus_killed:
            parts.append("Wumpus is DEAD")
        elif self.has_arrow:
            wx, wy, found = self.kb.confirmed_or_only_wumpus()
            if found:
                parts.append(f"DPLL: Wumpus confirmed at ({wx},{wy}) -> SHOOT planned")
            else:
                parts.append("Wumpus location unknown")

        # 4. Inventory
        inv = []
        if self.has_gold:  inv.append("GOLD")
        if self.has_arrow: inv.append("ARROW")
        if inv:
            parts.append(f"Inventory: {','.join(inv)}")

        # 5. Safe frontier size
        frontier = self.safe_known - self.visited
        parts.append(f"Safe frontier: {len(frontier)} cells")

        return " -> ".join(parts)

    @property
    def dpll_log(self) -> str:
        """The most recent DPLL reasoning log string."""
        return self._dpll_log

    # ------------------------------------------------------------------
    # Decision making
    # ------------------------------------------------------------------

    def decide_action(self) -> str:
        """
        Return the next action to execute.  Priority order:
          1. Grab if glitter and gold not yet held.
          2. Climb if gold held and at (0, 0).
          3. Consume the pre-planned queue.
          4. Build a new plan.
        """
        # 1. Grab
        if self._last_p.get("glitter") and not self.has_gold:
            self.action_queue.clear()
            return "Grab"

        # 2. Climb with gold
        if self.has_gold and self.x == 0 and self.y == 0:
            self.action_queue.clear()
            return "Climb"

        # 3. Consume queue
        if self.action_queue:
            return self.action_queue.pop(0)

        # 4. Plan
        return self._plan()

    def _plan(self) -> str:
        """
        Build a new action sequence and return its first action.

        Priority:
          1. Return home with gold → Climb.
          2. Explore nearest proven-safe unvisited cell.
          3. Shoot confirmed Wumpus.
          4. Retreat home → Climb.
          5. Climb in place (last resort).
        """
        start: State = (self.x, self.y, self.dir)
        safe  = set(self.safe_known)

        # 1. Return home with gold
        if self.has_gold:
            path = _find_path(start, 0, 0, safe)
            if path is not None:
                self.action_queue = path + ["Climb"]
                return self._pop_queue("return-home-with-gold")

        # 2. Explore nearest safe unvisited cell (Safe prioritization)
        best_path: Optional[List[str]] = None
        best_target: Optional[Tuple[int, int]] = None
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                cell = (x, y)
                if cell not in self.safe_known or cell in self.visited:
                    continue
                path = _find_path(start, x, y, safe)
                if path is not None:
                    if best_path is None or len(path) < len(best_path):
                        best_path   = path
                        best_target = cell
        if best_path is not None:
            log.info("[plan] explore %s (%d moves)", best_target, len(best_path))
            self.action_queue = best_path
            return self._pop_queue("explore")

        # 3. Shoot confirmed or uniquely-consistent Wumpus (Fallback hunt)
        if self.has_arrow and not self.wumpus_killed:
            wx, wy, found = self.kb.confirmed_or_only_wumpus()
            if found:
                shoot_plan = self._plan_shoot(wx, wy, safe)
                if shoot_plan is not None:
                    log.info("[plan] shoot Wumpus at (%d,%d) via %d actions",
                             wx, wy, len(shoot_plan))
                    self.action_queue = shoot_plan
                    return self._pop_queue("shoot")

        # 4. Retreat home
        path = _find_path(start, 0, 0, safe)
        if path is not None:
            log.info("[plan] no safe frontier – returning home")
            self.action_queue = path + ["Climb"]
            return self._pop_queue("retreat")

        # 5. Absolute last resort
        log.warning("[plan] trapped – climbing in place")
        return "Climb"

    def _pop_queue(self, reason: str) -> str:
        """Remove and return the first queued action."""
        if not self.action_queue:
            return "Climb"
        action = self.action_queue.pop(0)
        log.info("[queue:%s] → %s (%d remaining)",
                 reason, action, len(self.action_queue))
        return action

    def _plan_shoot(
        self,
        wx: int, wy: int,
        safe: Set[Tuple[int, int]],
    ) -> Optional[List[str]]:
        """
        Build an action sequence that ends with a Shoot reaching the Wumpus
        at (wx, wy).  The agent lines up on the same row or column through a
        safe path, then turns to face the Wumpus before firing.
        """
        candidates: List[Tuple[int, int, int]] = []   # (x, y, shoot_dir)

        # Same row – fire East from x < wx, West from x > wx
        for x in range(GRID_SIZE):
            if x == wx:
                continue
            if (x, wy) not in safe:
                continue
            d = EAST if x < wx else WEST
            candidates.append((x, wy, d))

        # Same column – fire North from y < wy, South from y > wy
        for y in range(GRID_SIZE):
            if y == wy:
                continue
            if (wx, y) not in safe:
                continue
            d = NORTH if y < wy else SOUTH
            candidates.append((wx, y, d))

        best: Optional[List[str]] = None
        for cx, cy, shoot_dir in candidates:
            path = _find_path((self.x, self.y, self.dir), cx, cy, safe)
            if path is None:
                continue
            # Find the direction we face after following the path
            s: State = (self.x, self.y, self.dir)
            for act in path:
                s = _apply_action(s, act)
            full = path + _turns_to(s[2], shoot_dir) + ["Shoot"]
            if best is None or len(full) < len(best):
                best = full

        return best
