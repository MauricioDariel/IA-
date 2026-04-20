"""
test_dpll_kb.py
===============
Unit tests for the DPLL solver and Knowledge Base.
Run with:  python test_dpll_kb.py
Does NOT require the Go server to be running.
"""
import sys, os
sys.path.insert(0, os.path.dirname(__file__))

from dpll import is_sat, entails
from kb import KB, pit_var, wumpus_var, n_lit, p_lit, neighbors_of, GRID_SIZE

# ---- DPLL basic tests ----

def test_empty_cnf_is_sat():
    assert is_sat([]) is True
    print("PASS  is_sat([]) => True")

def test_single_pos_clause():
    assert is_sat([[1]]) is True
    print("PASS  is_sat([[1]]) => True")

def test_contradiction():
    # x=1 AND x=False: [[1], [-1]] is UNSAT
    assert is_sat([[1], [-1]]) is False
    print("PASS  is_sat([[1],[-1]]) => False (contradiction)")

def test_unit_propagation():
    # [1] forces var1=True; then [−1, 2] becomes [2]; then [−2] fails
    # So [[1],[-1,2],[-2]] UNSAT
    assert is_sat([[1], [-1, 2], [-2]]) is False
    print("PASS  unit propagation conflict => UNSAT")

def test_entails_known_fact():
    # KB: ¬pit(0,0)  →  entails ¬pit(0,0)
    kb = [[n_lit(pit_var(0, 0))]]
    assert entails(kb, n_lit(pit_var(0, 0))) is True
    print("PASS  entails: KB |= not-Pit(0,0)")

def test_does_not_entail():
    # empty KB cannot prove anything
    assert entails([], n_lit(pit_var(1, 1))) is False
    print("PASS  entails: {} |/= not-Pit(1,1)  (correct - no info)")

# ---- KB tests ----

def test_start_cell_safe():
    kb = KB()
    assert kb.is_safe(0, 0) is True
    print("PASS  KB.is_safe(0,0) => True after init")

def test_no_breeze_no_stench_neighbors_safe():
    kb = KB()
    kb.add_visit_observation(0, 0, stench=False, breeze=False)
    for nx, ny in neighbors_of(0, 0):
        assert kb.is_safe(nx, ny), f"Expected ({nx},{ny}) safe"
    print("PASS  No breeze/stench at (0,0) => all neighbors safe")

def test_breeze_means_neighbor_pit_possible():
    kb = KB()
    kb.add_visit_observation(0, 0, stench=False, breeze=True)
    # (0,0) safe; we cannot prove any specific neighbor has NO pit
    assert kb.is_safe(0, 1) is False
    assert kb.is_safe(1, 0) is False
    print("PASS  Breeze at (0,0) => neighbours NOT provably safe")

def test_kill_wumpus():
    kb = KB()
    kb.add_visit_observation(0, 0, stench=True, breeze=False)
    # Before kill: (0,1) has stench origin – possibly Wumpus there
    # After kill: wumpus gone → (0,1) safe from wumpus
    kb.kill_wumpus()
    # Wumpus is dead, check no wumpus entailed for any cell
    for x in range(GRID_SIZE):
        for y in range(GRID_SIZE):
            assert entails(kb.clauses, n_lit(wumpus_var(x, y))), \
                f"Expected ¬Wumpus({x},{y}) after kill"
    print("PASS  kill_wumpus() => not-W(x,y) for all cells")

def test_neighbors_of():
    n = neighbors_of(0, 0)
    assert set(n) == {(1, 0), (0, 1)}, f"Got {n}"
    n = neighbors_of(1, 1)
    assert set(n) == {(0, 1), (2, 1), (1, 0), (1, 2)}, f"Got {n}"
    print("PASS  neighbors_of() correct")

def test_confirmed_wumpus_pinned():
    """After ruling out all cells except one, KB should pin the Wumpus."""
    kb = KB()
    # Mark every cell safe except (2, 2) and (0, 0)
    for x in range(GRID_SIZE):
        for y in range(GRID_SIZE):
            if (x, y) not in ((2, 2), (0, 0)):
                # Assert ¬Wumpus there
                kb.clauses.append([n_lit(wumpus_var(x, y))])
    wx, wy, found = kb.has_confirmed_wumpus()
    assert found is True, "Expected confirmed Wumpus"
    assert (wx, wy) == (2, 2), f"Expected (2,2) got ({wx},{wy})"
    print("PASS  has_confirmed_wumpus() pinpoints (2,2)")

# ---- Agent smoke test (no server needed) ----

def test_agent_smoke():
    from agent import Agent
    a = Agent("test-game-id")
    # Simulate initial perception: nothing
    p = {"stench": False, "breeze": False, "glitter": False,
         "bump": False, "scream": False, "score": 0, "gameOver": False}
    a.update_knowledge(p)
    action = a.decide_action()
    assert action in ("Forward", "TurnLeft", "TurnRight", "Grab", "Shoot", "Climb"), \
        f"Unexpected action: {action}"
    print(f"PASS  Agent first action: {action}")

# ---- Run all tests ----

if __name__ == "__main__":
    tests = [
        test_empty_cnf_is_sat,
        test_single_pos_clause,
        test_contradiction,
        test_unit_propagation,
        test_entails_known_fact,
        test_does_not_entail,
        test_start_cell_safe,
        test_no_breeze_no_stench_neighbors_safe,
        test_breeze_means_neighbor_pit_possible,
        test_kill_wumpus,
        test_neighbors_of,
        test_confirmed_wumpus_pinned,
        test_agent_smoke,
    ]
    passed = 0
    failed = 0
    for t in tests:
        try:
            t()
            passed += 1
        except Exception as e:
            print(f"FAIL  {t.__name__}: {e}")
            failed += 1
    print(f"\n{'='*40}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'='*40}")
    sys.exit(0 if failed == 0 else 1)
