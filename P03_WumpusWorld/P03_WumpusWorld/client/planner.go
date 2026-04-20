// planner.go
//
// Decision making and path planning for the Wumpus World agent. The agent
// combines DPLL-based inference (kb.go) with a breadth-first search on the
// space of (x, y, direction) triples to turn high-level intentions (e.g.
// "reach cell (2, 3)") into concrete action sequences understood by the
// server (Forward, TurnLeft, TurnRight, Shoot, Grab, Climb).
package main

import (
	"fmt"
	"log"
)

// Directions match the server's encoding in game.go.
const (
	East  = 0
	North = 1
	West  = 2
	South = 3
)

// dirName returns a human-readable label for a direction.
func dirName(d int) string {
	switch d {
	case East:
		return "East"
	case North:
		return "North"
	case West:
		return "West"
	case South:
		return "South"
	}
	return fmt.Sprintf("dir(%d)", d)
}

// state captures the complete pose of the agent for BFS search.
type state struct {
	x, y, dir int
}

// applyAction returns the pose obtained by executing action in state s.
// Forward that would walk out of the grid leaves the pose unchanged.
func applyAction(s state, action string) state {
	switch action {
	case "Forward":
		nx, ny := s.x, s.y
		switch s.dir {
		case East:
			nx++
		case North:
			ny++
		case West:
			nx--
		case South:
			ny--
		}
		if nx < 0 || nx >= GridSize || ny < 0 || ny >= GridSize {
			return s // bump, no movement
		}
		return state{nx, ny, s.dir}
	case "TurnLeft":
		return state{s.x, s.y, (s.dir + 1) % 4}
	case "TurnRight":
		return state{s.x, s.y, (s.dir - 1 + 4) % 4}
	}
	return s
}

// findPath returns the shortest action sequence that takes the agent from
// pose `from` to any pose sitting on (toX, toY), constrained to walk only
// through cells in `safe`. Nil is returned when no such path exists.
func findPath(from state, toX, toY int, safe map[[2]int]bool) []string {
	type node struct {
		s       state
		actions []string
	}
	if from.x == toX && from.y == toY {
		return []string{}
	}
	// Ensure the starting cell is considered walkable even if it wasn't
	// explicitly added by the caller.
	safeSet := make(map[[2]int]bool, len(safe)+1)
	for k, v := range safe {
		safeSet[k] = v
	}
	safeSet[[2]int{from.x, from.y}] = true

	visited := map[state]bool{from: true}
	queue := []node{{s: from, actions: []string{}}}

	for len(queue) > 0 {
		cur := queue[0]
		queue = queue[1:]

		for _, action := range []string{"Forward", "TurnLeft", "TurnRight"} {
			ns := applyAction(cur.s, action)
			if action == "Forward" {
				// Reject moves that bump (ns == cur.s with same dir) or
				// that step into an unknown / unsafe cell.
				if ns == cur.s {
					continue
				}
				if !safeSet[[2]int{ns.x, ns.y}] {
					continue
				}
			}
			if visited[ns] {
				continue
			}
			visited[ns] = true
			newActions := make([]string, len(cur.actions)+1)
			copy(newActions, cur.actions)
			newActions[len(cur.actions)] = action
			if ns.x == toX && ns.y == toY {
				return newActions
			}
			queue = append(queue, node{s: ns, actions: newActions})
		}
	}
	return nil
}

// turnsTo returns the shorter sequence of TurnLeft / TurnRight actions that
// rotates the agent from heading `from` to heading `to`.
func turnsTo(from, to int) []string {
	if from == to {
		return nil
	}
	leftSteps := (to - from + 4) % 4  // TurnLeft increases direction
	rightSteps := (from - to + 4) % 4 // TurnRight decreases direction
	if leftSteps <= rightSteps {
		out := make([]string, leftSteps)
		for i := range out {
			out[i] = "TurnLeft"
		}
		return out
	}
	out := make([]string, rightSteps)
	for i := range out {
		out[i] = "TurnRight"
	}
	return out
}

// Agent is the DPLL-powered Wumpus World player. It maintains the current
// pose, inventory, knowledge base and a queue of actions to execute.
type Agent struct {
	x, y         int
	dir          int
	hasArrow     bool
	hasGold      bool
	wumpusKilled bool

	visited   map[[2]int]bool // cells we have personally stood on
	safeKnown map[[2]int]bool // cells we can prove are safe (incl. visited)

	kb          *KB
	actionQueue []string

	lastP  Perception
	gameID string
}

// NewAgent creates a fresh agent sitting at (0, 0) facing East with its
// arrow.
func NewAgent(gameID string) *Agent {
	a := &Agent{
		x: 0, y: 0, dir: East,
		hasArrow:  true,
		visited:   make(map[[2]int]bool),
		safeKnown: make(map[[2]int]bool),
		kb:        NewKB(),
		gameID:    gameID,
	}
	// The start cell is trivially safe by construction of the KB.
	a.safeKnown[[2]int{0, 0}] = true
	return a
}

// UpdateState adjusts the pose and inventory after executing `action` and
// receiving `p` from the server.
func (a *Agent) UpdateState(action string, p Perception) {
	switch action {
	case "Forward":
		if p.Bump {
			// Any planned path is now invalid; discard it.
			a.actionQueue = nil
		} else {
			switch a.dir {
			case East:
				a.x++
			case North:
				a.y++
			case West:
				a.x--
			case South:
				a.y--
			}
		}
	case "TurnLeft":
		a.dir = (a.dir + 1) % 4
	case "TurnRight":
		a.dir = (a.dir - 1 + 4) % 4
	case "Grab":
		a.hasGold = true
	case "Shoot":
		a.hasArrow = false
	}
}

// UpdateKnowledge integrates a new perception into the knowledge base and
// re-evaluates which cells are provably safe.
func (a *Agent) UpdateKnowledge(p Perception) {
	a.lastP = p

	if p.Scream && !a.wumpusKilled {
		a.wumpusKilled = true
		a.kb.KillWumpus()
		log.Printf("[KB] Scream heard → Wumpus killed, cleaning W(·,·) from KB")
	}

	pos := [2]int{a.x, a.y}
	if !a.visited[pos] {
		a.visited[pos] = true
		a.safeKnown[pos] = true
		a.kb.AddVisitObservation(a.x, a.y, p.Stench, p.Breeze)
	}

	a.updateSafeKnown()
}

// updateSafeKnown queries DPLL for every cell that is not yet known safe,
// promoting any cell that the KB can prove free of pits and Wumpus.
func (a *Agent) updateSafeKnown() {
	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			cell := [2]int{x, y}
			if a.safeKnown[cell] {
				continue
			}
			if a.kb.IsSafe(x, y) {
				a.safeKnown[cell] = true
				log.Printf("[DPLL] proved safe: (%d,%d)", x, y)
			}
		}
	}
}

// DecideAction returns the next action the agent wants to execute. The
// order of checks implements the overall strategy:
//  1. Grab if glitter is visible and we do not yet hold the gold.
//  2. Climb once we are back at (0, 0) with the gold.
//  3. Consume the current plan queue if non-empty.
//  4. Build a new plan via plan().
func (a *Agent) DecideAction() string {
	if a.lastP.Glitter && !a.hasGold {
		a.actionQueue = nil // drop any stale plan – we found the gold
		return "Grab"
	}
	if a.hasGold && a.x == 0 && a.y == 0 {
		a.actionQueue = nil
		return "Climb"
	}
	if len(a.actionQueue) > 0 {
		next := a.actionQueue[0]
		a.actionQueue = a.actionQueue[1:]
		return next
	}
	return a.plan()
}

// plan builds a new action sequence according to the priority list:
//   - gold in hand  → walk back to (0,0) and Climb;
//   - explore      → go to the nearest provably safe unvisited cell;
//   - shoot        → if the Wumpus location is pinned down, plan to shoot;
//   - retreat      → otherwise walk back to (0,0) and Climb.
//
// Plan returns the first action of the newly enqueued sequence.
func (a *Agent) plan() string {
	start := state{a.x, a.y, a.dir}

	// Snapshot of walkable cells for BFS (safeKnown always includes visited).
	safe := make(map[[2]int]bool, len(a.safeKnown))
	for k := range a.safeKnown {
		safe[k] = true
	}

	// 1. If we already have the gold, head home.
	if a.hasGold {
		if path := findPath(start, 0, 0, safe); path != nil {
			a.actionQueue = append(path, "Climb")
			return a.popQueue("return-home-with-gold")
		}
	}

	// 2. Explore the nearest provably safe unvisited cell.
	var bestPath []string
	var bestTarget [2]int
	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			cell := [2]int{x, y}
			if !a.safeKnown[cell] || a.visited[cell] {
				continue
			}
			p := findPath(start, x, y, safe)
			if p != nil && (bestPath == nil || len(p) < len(bestPath)) {
				bestPath = p
				bestTarget = cell
			}
		}
	}
	if bestPath != nil {
		log.Printf("[plan] explore new safe cell %v (%d moves)", bestTarget, len(bestPath))
		a.actionQueue = bestPath
		return a.popQueue("explore")
	}

	// 3. Try to shoot a confirmed Wumpus.
	if a.hasArrow && !a.wumpusKilled {
		if wx, wy, ok := a.kb.HasConfirmedWumpus(); ok {
			if plan := a.planShoot(wx, wy, safe); plan != nil {
				log.Printf("[plan] attack Wumpus at (%d,%d) via %d actions", wx, wy, len(plan))
				a.actionQueue = plan
				return a.popQueue("shoot")
			}
		}
	}

	// 4. Give up: walk home and Climb.
	if path := findPath(start, 0, 0, safe); path != nil {
		log.Printf("[plan] no safe frontier – returning home")
		a.actionQueue = append(path, "Climb")
		return a.popQueue("retreat")
	}

	// Absolute last resort: climb in place (scoreless but terminates).
	log.Printf("[plan] trapped – climbing in place")
	return "Climb"
}

// popQueue removes and returns the first queued action, logging the reason.
func (a *Agent) popQueue(reason string) string {
	if len(a.actionQueue) == 0 {
		return "Climb"
	}
	next := a.actionQueue[0]
	a.actionQueue = a.actionQueue[1:]
	log.Printf("[queue:%s] → %s (%d remaining)", reason, next, len(a.actionQueue))
	return next
}

// planShoot attempts to build an action sequence that ends with a Shoot
// arrow reaching the Wumpus at (wx, wy). The agent must line up on the same
// row or column as the Wumpus, through a safe corridor.
func (a *Agent) planShoot(wx, wy int, safe map[[2]int]bool) []string {
	type candidate struct {
		x, y, shootDir int
	}
	var cands []candidate

	// Same row: fire East from x < wx or West from x > wx.
	for x := 0; x < GridSize; x++ {
		if x == wx {
			continue
		}
		cell := [2]int{x, wy}
		if !safe[cell] {
			continue
		}
		d := East
		if x > wx {
			d = West
		}
		cands = append(cands, candidate{x, wy, d})
	}

	// Same column: fire North from y < wy or South from y > wy.
	for y := 0; y < GridSize; y++ {
		if y == wy {
			continue
		}
		cell := [2]int{wx, y}
		if !safe[cell] {
			continue
		}
		d := North
		if y > wy {
			d = South
		}
		cands = append(cands, candidate{wx, y, d})
	}

	var best []string
	for _, c := range cands {
		path := findPath(state{a.x, a.y, a.dir}, c.x, c.y, safe)
		if path == nil {
			continue
		}
		// Compute the direction we end up facing after following path.
		s := state{a.x, a.y, a.dir}
		for _, act := range path {
			s = applyAction(s, act)
		}
		full := make([]string, 0, len(path)+4)
		full = append(full, path...)
		full = append(full, turnsTo(s.dir, c.shootDir)...)
		full = append(full, "Shoot")
		if best == nil || len(full) < len(best) {
			best = full
		}
	}
	return best
}
