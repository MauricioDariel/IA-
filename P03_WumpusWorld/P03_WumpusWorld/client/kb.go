// kb.go
//
// Knowledge base for the Wumpus World expressed as CNF clauses. The
// knowledge base is queried through the DPLL engine defined in dpll.go to
// decide whether a given cell is safe (i.e. free of both pits and the
// Wumpus) and, when possible, to pinpoint the Wumpus location.
//
// Propositional variables.
//   Pit(x, y)     : there is a pit at (x, y)
//   Wumpus(x, y)  : the Wumpus is at (x, y)
//
// Variable identifiers are assigned as follows for a 4×4 grid:
//   Pit(x, y)     = y*GridSize + x + 1           (range 1 … 16)
//   Wumpus(x, y)  = GridSize*GridSize + y*GridSize + x + 1   (range 17 … 32)
package main

// GridSize is the side length of the square Wumpus World grid. This must
// match the value used by the server (see game.go).
const GridSize = 4

// pitVar returns the variable id representing "there is a pit at (x, y)".
func pitVar(x, y int) int {
	return y*GridSize + x + 1
}

// wumpusVar returns the variable id representing "the Wumpus is at (x, y)".
func wumpusVar(x, y int) int {
	return GridSize*GridSize + y*GridSize + x + 1
}

// pLit builds a positive literal for variable v.
func pLit(v int) Literal { return Literal(v) }

// nLit builds a negative literal for variable v.
func nLit(v int) Literal { return Literal(-v) }

// neighborsOf returns the valid orthogonal neighbors of (x, y).
func neighborsOf(x, y int) [][2]int {
	deltas := [4][2]int{{-1, 0}, {1, 0}, {0, -1}, {0, 1}}
	result := make([][2]int, 0, 4)
	for _, d := range deltas {
		nx, ny := x+d[0], y+d[1]
		if nx >= 0 && nx < GridSize && ny >= 0 && ny < GridSize {
			result = append(result, [2]int{nx, ny})
		}
	}
	return result
}

// KB is the propositional knowledge base. It stores CNF clauses that encode
// everything the agent currently knows about the world.
type KB struct {
	clauses CNF
}

// NewKB constructs a fresh knowledge base seeded with:
//   - the starting cell (0,0) is free of pits and the Wumpus;
//   - at most one Wumpus exists on the grid.
//
// The "at most one Wumpus" constraint is what enables DPLL to locate the
// Wumpus by elimination, which in turn unlocks shooting plans.
func NewKB() *KB {
	kb := &KB{}

	// The agent starts at (0, 0) and is alive, so the start cell is safe.
	kb.clauses = append(kb.clauses, Clause{nLit(pitVar(0, 0))})
	kb.clauses = append(kb.clauses, Clause{nLit(wumpusVar(0, 0))})

	// At most one Wumpus: for each pair of cells (i, j), ¬W(i) ∨ ¬W(j).
	total := GridSize * GridSize
	for i := 0; i < total; i++ {
		wi := GridSize*GridSize + i + 1
		for j := i + 1; j < total; j++ {
			wj := GridSize*GridSize + j + 1
			kb.clauses = append(kb.clauses, Clause{nLit(wi), nLit(wj)})
		}
	}

	// At least one Wumpus somewhere on the board. Strictly speaking, the
	// game always spawns a Wumpus, so we add this to help DPLL pin down its
	// location once enough stench/no-stench evidence has been gathered.
	var wLits Clause
	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			wLits = append(wLits, pLit(wumpusVar(x, y)))
		}
	}
	kb.clauses = append(kb.clauses, wLits)

	return kb
}

// AddVisitObservation records that the agent entered (x, y) and survived
// (so no pit and no live Wumpus there) and reports perceiving the given
// stench / breeze flags at that cell.
func (kb *KB) AddVisitObservation(x, y int, stench, breeze bool) {
	// The current cell is safe because the agent is alive on it.
	kb.clauses = append(kb.clauses, Clause{nLit(pitVar(x, y))})
	kb.clauses = append(kb.clauses, Clause{nLit(wumpusVar(x, y))})

	nb := neighborsOf(x, y)

	// Stench ↔ some neighbor has the Wumpus.
	if stench {
		// Stench: at least one neighbor has the Wumpus.
		disj := make(Clause, 0, len(nb))
		for _, n := range nb {
			disj = append(disj, pLit(wumpusVar(n[0], n[1])))
		}
		if len(disj) > 0 {
			kb.clauses = append(kb.clauses, disj)
		}
	} else {
		// No stench: no neighbor has the Wumpus.
		for _, n := range nb {
			kb.clauses = append(kb.clauses, Clause{nLit(wumpusVar(n[0], n[1]))})
		}
	}

	// Breeze ↔ some neighbor has a pit.
	if breeze {
		disj := make(Clause, 0, len(nb))
		for _, n := range nb {
			disj = append(disj, pLit(pitVar(n[0], n[1])))
		}
		if len(disj) > 0 {
			kb.clauses = append(kb.clauses, disj)
		}
	} else {
		for _, n := range nb {
			kb.clauses = append(kb.clauses, Clause{nLit(pitVar(n[0], n[1]))})
		}
	}
}

// KillWumpus registers that the Wumpus has been killed (a scream was
// heard): for every cell (x, y) we assert ¬Wumpus(x, y). Any cell that was
// previously unsafe only because of the Wumpus can now be deduced safe.
func (kb *KB) KillWumpus() {
	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			kb.clauses = append(kb.clauses, Clause{nLit(wumpusVar(x, y))})
		}
	}
}

// IsSafe returns true when the knowledge base can prove that (x, y)
// contains neither a pit nor a live Wumpus.
func (kb *KB) IsSafe(x, y int) bool {
	safeFromPit := Entails(kb.clauses, nLit(pitVar(x, y)))
	if !safeFromPit {
		return false
	}
	return Entails(kb.clauses, nLit(wumpusVar(x, y)))
}

// HasConfirmedWumpus returns (x, y, true) if DPLL proves the Wumpus must
// live at a single specific cell. Otherwise (0, 0, false) is returned.
func (kb *KB) HasConfirmedWumpus() (int, int, bool) {
	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			if Entails(kb.clauses, pLit(wumpusVar(x, y))) {
				return x, y, true
			}
		}
	}
	return 0, 0, false
}

// MaybePit reports whether it is consistent with the KB that (x, y) holds a
// pit. Useful for ordering risky moves when no provably safe move exists.
func (kb *KB) MaybePit(x, y int) bool {
	// It is possible that (x, y) has a pit iff KB ∧ Pit(x, y) is SAT.
	test := make(CNF, len(kb.clauses)+1)
	copy(test, kb.clauses)
	test[len(kb.clauses)] = Clause{pLit(pitVar(x, y))}
	return IsSAT(test)
}
