"""
kb.py
=====
Propositional Knowledge Base for the Wumpus World expressed as CNF clauses.
The KB is queried through the DPLL engine (dpll.py) to decide whether a given
cell is safe (free of pits and the Wumpus) and, when possible, to pinpoint the
Wumpus location.

Propositional variables (4×4 grid):
  pit_var(x, y)     = y * GRID_SIZE + x + 1            → range  1 …16
  wumpus_var(x, y)  = GRID_SIZE² + y * GRID_SIZE + x + 1 → range 17 …32

Encoding matches the Go implementation in client/kb.go exactly.
"""

from __future__ import annotations
from typing import List, Tuple

from dpll import CNF, Clause, Literal, is_sat, entails

GRID_SIZE: int = 4   # must match the server value


# ---------------------------------------------------------------------------
# Variable helpers
# ---------------------------------------------------------------------------

def pit_var(x: int, y: int) -> int:
    """Variable id for 'there is a pit at (x, y)'."""
    return y * GRID_SIZE + x + 1


def wumpus_var(x: int, y: int) -> int:
    """Variable id for 'the Wumpus is at (x, y)'."""
    return GRID_SIZE * GRID_SIZE + y * GRID_SIZE + x + 1


def p_lit(v: int) -> Literal:
    """Positive (TRUE) literal for variable v."""
    return v


def n_lit(v: int) -> Literal:
    """Negative (FALSE) literal for variable v."""
    return -v


def neighbors_of(x: int, y: int) -> List[Tuple[int, int]]:
    """Return the valid orthogonal neighbors of (x, y) within the grid."""
    result = []
    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nx, ny = x + dx, y + dy
        if 0 <= nx < GRID_SIZE and 0 <= ny < GRID_SIZE:
            result.append((nx, ny))
    return result


# ---------------------------------------------------------------------------
# Knowledge Base
# ---------------------------------------------------------------------------

class KB:
    """
    Propositional Knowledge Base that accumulates CNF clauses derived from
    the agent's perceptions and uses DPLL for inference.
    """

    def __init__(self) -> None:
        self.clauses: CNF = []
        self._seed()

    # ------------------------------------------------------------------
    # Initialisation
    # ------------------------------------------------------------------

    def _seed(self) -> None:
        """
        Seed the KB with world axioms:
          • (0,0) is safe – the agent starts there alive.
          • At most one Wumpus exists on the board
            (¬W(i) ∨ ¬W(j) for every pair i ≠ j).
          • At least one Wumpus exists (disjunction of all W(x,y)).
        """
        # Start cell is safe
        self.clauses.append([n_lit(pit_var(0, 0))])
        self.clauses.append([n_lit(wumpus_var(0, 0))])

        total = GRID_SIZE * GRID_SIZE

        # At most one Wumpus: ¬W(i) ∨ ¬W(j) for every pair i < j
        for i in range(total):
            wi = GRID_SIZE * GRID_SIZE + i + 1
            for j in range(i + 1, total):
                wj = GRID_SIZE * GRID_SIZE + j + 1
                self.clauses.append([n_lit(wi), n_lit(wj)])

        # At least one Wumpus somewhere on the board
        w_lits: Clause = []
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                w_lits.append(p_lit(wumpus_var(x, y)))
        self.clauses.append(w_lits)

    # ------------------------------------------------------------------
    # Observation recording
    # ------------------------------------------------------------------

    def add_visit_observation(
        self, x: int, y: int, stench: bool, breeze: bool
    ) -> None:
        """
        Record that the agent entered (x, y) and survived (no pit, no live
        Wumpus there), then add stench/breeze evidence.

        Stench ↔ at least one neighbour has the Wumpus.
        Breeze ↔ at least one neighbour has a pit.
        """
        # Survived → cell is safe
        self.clauses.append([n_lit(pit_var(x, y))])
        self.clauses.append([n_lit(wumpus_var(x, y))])

        nb = neighbors_of(x, y)

        # ---- Stench ----
        if stench:
            # ∃ neighbour with Wumpus
            disj: Clause = [p_lit(wumpus_var(nx, ny)) for nx, ny in nb]
            if disj:
                self.clauses.append(disj)
        else:
            # ∀ neighbours: no Wumpus
            for nx, ny in nb:
                self.clauses.append([n_lit(wumpus_var(nx, ny))])

        # ---- Breeze ----
        if breeze:
            # ∃ neighbour with pit
            disj = [p_lit(pit_var(nx, ny)) for nx, ny in nb]
            if disj:
                self.clauses.append(disj)
        else:
            # ∀ neighbours: no pit
            for nx, ny in nb:
                self.clauses.append([n_lit(pit_var(nx, ny))])

    def kill_wumpus(self) -> None:
        """
        Register that the Wumpus has been killed (scream perceived).
        Asserts ¬Wumpus(x, y) for every cell so that DPLL can now prove
        wumpus-related cells safe.
        """
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                self.clauses.append([n_lit(wumpus_var(x, y))])

    # ------------------------------------------------------------------
    # Inference queries
    # ------------------------------------------------------------------

    def is_safe(self, x: int, y: int) -> bool:
        """
        Return True iff KB proves (x, y) is free of both pits and the Wumpus.

        Uses DPLL refutation:
            KB ⊨ ¬Pit(x,y)   AND   KB ⊨ ¬Wumpus(x,y)
        """
        if not entails(self.clauses, n_lit(pit_var(x, y))):
            return False
        return entails(self.clauses, n_lit(wumpus_var(x, y)))

    def has_confirmed_wumpus(self) -> Tuple[int, int, bool]:
        """
        Return (wx, wy, True) if DPLL proves the Wumpus must be at exactly
        one cell.  Otherwise returns (0, 0, False).
        """
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                if entails(self.clauses, p_lit(wumpus_var(x, y))):
                    return x, y, True
        return 0, 0, False

    def confirmed_or_only_wumpus(self) -> Tuple[int, int, bool]:
        """
        Extended wumpus location query used by the agent to decide when to shoot.

        Strategy (two levels of confidence):

        Level 1 — Full certainty (DPLL refutation):
            KB ⊨ W(x,y)  iff  KB ∧ ¬W(x,y)  is UNSAT.
            If this holds for some cell, the Wumpus MUST be there.

        Level 2 — Only consistent candidate (SAT check):
            For every cell (x,y), test whether KB ∧ [W(x,y)] is SAT.
            If exactly ONE cell passes the test, the Wumpus can only be
            there given all current evidence → safe to shoot.

        CNF query for "Is (x,y) a consistent Wumpus location?":
            test_clauses = self.clauses + [[wumpus_var(x, y)]]
            is_sat(test_clauses)   # SAT → consistent · UNSAT → ruled out

        Returns (wx, wy, True) on success, (0, 0, False) otherwise.
        """
        # --- Level 1: full logical certainty ---
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                if entails(self.clauses, p_lit(wumpus_var(x, y))):
                    return x, y, True

        # --- Level 2: unique consistent candidate ---
        candidates = []
        for x in range(GRID_SIZE):
            for y in range(GRID_SIZE):
                # CNF query: assume W(x,y)=True as a unit clause, check SAT
                test = [list(c) for c in self.clauses]
                test.append([p_lit(wumpus_var(x, y))])
                if is_sat(test):
                    candidates.append((x, y))

        if len(candidates) == 1:
            wx, wy = candidates[0]
            return wx, wy, True

        return 0, 0, False

    def maybe_pit(self, x: int, y: int) -> bool:
        """
        Return True if it is consistent with the KB that (x, y) contains a
        pit.  Useful for risk-ordering moves when no safe frontier exists.
        """
        test = [list(c) for c in self.clauses]
        test.append([p_lit(pit_var(x, y))])
        return is_sat(test)
