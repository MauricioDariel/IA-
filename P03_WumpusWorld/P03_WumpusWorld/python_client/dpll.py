"""
dpll.py
=======
DPLL (Davis–Putnam–Logemann–Loveland) satisfiability solver used as the
inference engine for the Wumpus World agent.

The solver operates on a formula in Conjunctive Normal Form (CNF) and is
used by the knowledge base (kb.py) to answer entailment queries of the
form KB ⊨ φ via proof by refutation:

    KB ⊨ φ  iff  KB ∧ ¬φ  is UNSAT.

A literal is represented as a non-zero integer:
  +v  → variable v is TRUE
  -v  → variable v is FALSE
Variable identifiers must be strictly positive integers.

A Clause  is a list of literals  (disjunction / OR).
A CNF     is a list of Clauses   (conjunction / AND).
"""

from __future__ import annotations
from typing import Dict, List, Optional, Tuple

# Type aliases
Literal = int          # non-zero signed integer
Clause  = List[Literal]
CNF     = List[Clause]


def _var(lit: Literal) -> int:
    """Return the underlying positive variable id."""
    return abs(lit)


def _is_pos(lit: Literal) -> bool:
    """Return True if the literal asserts the variable TRUE."""
    return lit > 0


# ---------------------------------------------------------------------------
# Core helpers
# ---------------------------------------------------------------------------

def _simplify(clauses: CNF, assignment: Dict[int, bool]) -> Tuple[Optional[CNF], bool]:
    """
    Evaluate every clause against the current partial assignment.

    - Clauses that contain a satisfied literal are removed.
    - Falsified literals are dropped from their clause.
    - A clause reduced to the empty set signals UNSAT (returns None, False).

    Returns (simplified_cnf, True) or (None, False) on contradiction.
    """
    result: CNF = []
    for clause in clauses:
        satisfied = False
        remaining: Clause = []
        for lit in clause:
            v = _var(lit)
            if v in assignment:
                if _is_pos(lit) == assignment[v]:
                    satisfied = True
                    break
                # literal is false under assignment – drop it
            else:
                remaining.append(lit)
        if satisfied:
            continue
        if not remaining:
            return None, False   # empty clause → UNSAT
        result.append(remaining)
    return result, True


def _choose_branch_var(clauses: CNF, assignment: Dict[int, bool]) -> int:
    """Return the first unassigned variable found in the clauses, or 0."""
    for clause in clauses:
        for lit in clause:
            v = _var(lit)
            if v not in assignment:
                return v
    return 0


def _dpll(clauses: CNF, assignment: Dict[int, bool]) -> bool:
    """
    Recursive DPLL core.  Returns True iff the CNF is satisfiable under
    some extension of the supplied partial assignment.

    Applies unit propagation first, then branches on an unassigned variable
    (trying True first, then False).
    """
    # Unit-propagation loop
    while True:
        unit_found = False
        for clause in clauses:
            if len(clause) != 1:
                continue
            lit = clause[0]
            v   = _var(lit)
            val = _is_pos(lit)

            if v in assignment:
                if assignment[v] != val:
                    return False    # conflict between two unit clauses
                continue

            assignment[v] = val
            clauses, ok = _simplify(clauses, {v: val})
            if not ok:
                return False
            if not clauses:
                return True
            unit_found = True
            break                   # restart scan with simplified clauses

        if not unit_found:
            break

    # All clauses satisfied?
    if not clauses:
        return True

    # Choose a branching variable
    v = _choose_branch_var(clauses, assignment)
    if v == 0:
        return True   # every remaining clause was already satisfied

    # Branch: try v = True
    asgn_true = dict(assignment)
    asgn_true[v] = True
    sub, ok = _simplify(clauses, {v: True})
    if ok and _dpll(sub, asgn_true):
        return True

    # Branch: try v = False
    asgn_false = dict(assignment)
    asgn_false[v] = False
    sub, ok = _simplify(clauses, {v: False})
    return ok and _dpll(sub, asgn_false)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_sat(clauses: CNF) -> bool:
    """Return True if the CNF formula is satisfiable."""
    # Work on a copy so the caller's formula is not modified.
    return _dpll([list(c) for c in clauses], {})


def entails(kb: CNF, query: Literal) -> bool:
    """
    Return True when the knowledge base entails `query`, using proof by
    refutation:

        KB ⊨ query  ⇔  KB ∧ ¬query  is UNSAT.
    """
    negated = -query                           # flip the sign
    test = [list(c) for c in kb] + [[negated]]
    return not _dpll(test, {})
