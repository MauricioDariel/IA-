// dpll.go
//
// DPLL (Davis–Putnam–Logemann–Loveland) satisfiability solver used as the
// inference engine for the Wumpus World agent. The solver operates on a
// formula in Conjunctive Normal Form (CNF) and is used by the knowledge
// base (kb.go) to answer entailment queries of the form KB ⊨ φ via proof
// by refutation: KB ⊨ φ  iff  KB ∧ ¬φ is UNSAT.
package main

// Literal encodes a propositional literal as a signed integer.
//   +v  → variable v is asserted TRUE
//   -v  → variable v is asserted FALSE
// Variable identifiers must be strictly positive.
type Literal int

// Var returns the underlying variable identifier (always positive).
func (l Literal) Var() int {
	if l < 0 {
		return int(-l)
	}
	return int(l)
}

// IsPos reports whether the literal is a positive (un-negated) variable.
func (l Literal) IsPos() bool { return l > 0 }

// Clause is a disjunction (logical OR) of literals.
type Clause []Literal

// CNF is a conjunction (logical AND) of clauses.
type CNF []Clause

// simplify evaluates every clause against the current partial assignment:
//   - if the clause already contains a literal satisfied by the assignment,
//     the clause is removed (it is already true);
//   - any literal falsified by the assignment is dropped;
//   - a clause reduced to the empty clause signals a contradiction.
//
// It returns the simplified CNF and a boolean flag that is false when an
// empty clause appears (i.e. the formula became UNSAT under this partial
// assignment).
func simplify(clauses CNF, assignment map[int]bool) (CNF, bool) {
	result := make(CNF, 0, len(clauses))
	for _, clause := range clauses {
		satisfied := false
		remaining := make(Clause, 0, len(clause))
		for _, lit := range clause {
			v := lit.Var()
			if val, assigned := assignment[v]; assigned {
				if lit.IsPos() == val {
					satisfied = true
					break
				}
				// literal is false under the assignment – drop it
			} else {
				remaining = append(remaining, lit)
			}
		}
		if satisfied {
			continue
		}
		if len(remaining) == 0 {
			return nil, false // empty clause → UNSAT
		}
		result = append(result, remaining)
	}
	return result, true
}

// chooseBranchVar returns the first unassigned variable appearing in the
// clauses, or 0 if no such variable exists.
func chooseBranchVar(clauses CNF, assignment map[int]bool) int {
	for _, clause := range clauses {
		for _, lit := range clause {
			v := lit.Var()
			if _, assigned := assignment[v]; !assigned {
				return v
			}
		}
	}
	return 0
}

// copyAssignment returns a shallow copy of the assignment map.
func copyAssignment(a map[int]bool) map[int]bool {
	c := make(map[int]bool, len(a))
	for k, v := range a {
		c[k] = v
	}
	return c
}

// dpll is the recursive core of the DPLL algorithm. It returns true if the
// given CNF is satisfiable under an extension of the provided partial
// assignment. The algorithm applies unit propagation, then branches on an
// unassigned variable (trying true first, then false).
func dpll(clauses CNF, assignment map[int]bool) bool {
	// Base case: all clauses satisfied.
	if len(clauses) == 0 {
		return true
	}

	// Unit propagation loop. Whenever a clause has a single literal, that
	// literal must be true; assign it and re-simplify.
	for {
		unitFound := false
		for _, clause := range clauses {
			if len(clause) != 1 {
				continue
			}
			lit := clause[0]
			v := lit.Var()
			val := lit.IsPos()
			if cur, exists := assignment[v]; exists {
				if cur != val {
					return false // conflict between two unit clauses
				}
				continue
			}
			assignment[v] = val
			var ok bool
			clauses, ok = simplify(clauses, map[int]bool{v: val})
			if !ok {
				return false
			}
			if len(clauses) == 0 {
				return true
			}
			unitFound = true
			break // restart the scan with the simplified clauses
		}
		if !unitFound {
			break
		}
	}

	// Branching heuristic: pick the first unassigned variable.
	v := chooseBranchVar(clauses, assignment)
	if v == 0 {
		return true // every remaining clause was satisfied
	}

	// Try v = true.
	asgnTrue := copyAssignment(assignment)
	asgnTrue[v] = true
	if sub, ok := simplify(clauses, map[int]bool{v: true}); ok && dpll(sub, asgnTrue) {
		return true
	}

	// Try v = false.
	asgnFalse := copyAssignment(assignment)
	asgnFalse[v] = false
	sub, ok := simplify(clauses, map[int]bool{v: false})
	return ok && dpll(sub, asgnFalse)
}

// IsSAT reports whether the given CNF is satisfiable.
func IsSAT(clauses CNF) bool {
	cp := make(CNF, len(clauses))
	copy(cp, clauses)
	return dpll(cp, make(map[int]bool))
}

// Entails reports whether the knowledge base entails the single literal
// query, implemented as proof by refutation:
//
//	KB ⊨ query  ⇔  KB ∧ ¬query  is UNSAT.
func Entails(kb CNF, query Literal) bool {
	negated := Literal(-query) // flip the sign of the query literal
	test := make(CNF, len(kb)+1)
	copy(test, kb)
	test[len(kb)] = Clause{negated}
	return !dpll(test, make(map[int]bool))
}
