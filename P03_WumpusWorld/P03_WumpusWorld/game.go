
// game.go
package main

import (
	"math/rand"
	"time"
)

type Direction int

const (
	GridSize = 4
	PitProb  = 0.2
)
const (
	East Direction = iota
	North
	West
	South
)

type Square struct {
	HasPit    bool
	HasWumpus bool
	HasGold   bool
	HasStench bool
	HasBreeze bool
}

type Agent struct {
	X, Y      int
	Direction Direction
	HasArrow  bool
	HasGold   bool
}

type GameState struct {
	World       [GridSize][GridSize]Square
	Agent       Agent
	Score       int
	GameOver    bool
	WumpusAlive bool
	LastBump    bool
	LastScream  bool
}

type CellMeta struct {
	X         int  `json:"x"`
	Y         int  `json:"y"`
	HasWumpus bool `json:"hasWumpus"`
	HasPit    bool `json:"hasPit"`
	HasGold   bool `json:"hasGold"`
}

// The agent's perception of the current square
type Perception struct {
	Stench    bool       `json:"stench"`
	Breeze    bool       `json:"breeze"`
	Glitter   bool       `json:"glitter"`
	Bump      bool       `json:"bump"`
	Scream    bool       `json:"scream"`
	Score     int        `json:"score"`
	GameOver  bool       `json:"gameOver"`
	Message   string     `json:"message"`
	FullBoard []CellMeta `json:"fullBoard,omitempty"`
}

func newGame() *GameState {
	rand.New(rand.NewSource(time.Now().UnixNano()))

	gs := &GameState{
		Agent: Agent{
			X: 0, Y: 0,
			Direction: East,
			HasArrow:  true,
			HasGold:   false,
		},
		WumpusAlive: true,
	}

	// Build the world
	wx, wy := randPos(0, 0)
	gs.World[wx][wy].HasWumpus = true
	gx, gy := randPos(wx, wy)
	gs.World[gx][gy].HasGold = true

	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			if (x == 0 && y == 0) || (x == wx && y == wy) || (x == gx && y == gy) {
				continue
			}
			if rand.Float64() < PitProb {
				gs.World[x][y].HasPit = true
			}
		}
	}

	for x := 0; x < GridSize; x++ {
		for y := 0; y < GridSize; y++ {
			if gs.World[x][y].HasWumpus {
				addPerceptionToAdjacent(gs, x, y, "stench") // Stench is adjacent to wumpus
			}
			if gs.World[x][y].HasPit {
				addPerceptionToAdjacent(gs, x, y, "breeze") // Breeze is adjacent to a pit
			}
		}
	}
	return gs
}

func (gs *GameState) processAction(action string) {
	if gs.GameOver {
		return
	}
	gs.LastBump, gs.LastScream = false, false
	gs.Score-- // -1 for each action taken

	switch action {
	case "Forward":
		gs.moveForward()
	case "TurnLeft":
		gs.Agent.Direction = (gs.Agent.Direction + 1) % 4
	case "TurnRight":
		gs.Agent.Direction = (gs.Agent.Direction - 1 + 4) % 4
	case "Grab":
		if gs.World[gs.Agent.X][gs.Agent.Y].HasGold {
			gs.Agent.HasGold = true
			gs.World[gs.Agent.X][gs.Agent.Y].HasGold = false
		}
	case "Shoot":
		if gs.Agent.HasArrow {
			gs.Agent.HasArrow = false
			gs.Score -= 10
			gs.shootArrow()
		}
	case "Climb":
		if gs.Agent.X == 0 && gs.Agent.Y == 0 {
			gs.GameOver = true
			if gs.Agent.HasGold {
				gs.Score += 1000
			}
		}
	}

	if !gs.GameOver {
		gs.checkHazards()
	}
}

// getPerception generates the agent's perception in the current square
func (gs *GameState) getPerception() Perception {
	sq := gs.World[gs.Agent.X][gs.Agent.Y]
	msg := ""
	var fullBoard []CellMeta
	if gs.GameOver {
		if gs.Agent.HasGold && gs.Agent.X == 0 && gs.Agent.Y == 0 {
			msg = "You climbed out with the gold! VICTORY!"
		} else if sq.HasPit || (sq.HasWumpus && gs.WumpusAlive) {
			msg = "You Died. GAME OVER."
		} else {
			msg = "You climbed out empty-handed. GAME OVER."
		}

		fullBoard = make([]CellMeta, 0, GridSize*GridSize)
		for x := 0; x < GridSize; x++ {
			for y := 0; y < GridSize; y++ {
				cell := gs.World[x][y]
				fullBoard = append(fullBoard, CellMeta{
					X:         x,
					Y:         y,
					HasWumpus: cell.HasWumpus, // whether original or alive, we show it
					HasPit:    cell.HasPit,
					HasGold:   cell.HasGold,
				})
			}
		}
	}

	return Perception{
		Stench:    sq.HasStench || (sq.HasWumpus && gs.WumpusAlive),
		Breeze:    sq.HasBreeze,
		Glitter:   sq.HasGold,
		Bump:      gs.LastBump,
		Scream:    gs.LastScream,
		Score:     gs.Score,
		GameOver:  gs.GameOver,
		Message:   msg,
		FullBoard: fullBoard,
	}
}

// --- Helper Functions ---

func (gs *GameState) moveForward() {
	x, y := gs.Agent.X, gs.Agent.Y
	switch gs.Agent.Direction {
	case East:
		x++
	case North:
		y++
	case West:
		x--
	case South:
		y--
	}
	if x < 0 || x >= GridSize || y < 0 || y >= GridSize {
		gs.LastBump = true
	} else {
		gs.Agent.X, gs.Agent.Y = x, y
	}
}

func (gs *GameState) shootArrow() {
	x, y := gs.Agent.X, gs.Agent.Y
	switch gs.Agent.Direction {
	case East:
		for i := x; i < GridSize; i++ {
			if gs.World[i][y].HasWumpus {
				gs.killWumpus(i, y)
				return
			}
		}
	case North:
		for i := y; i < GridSize; i++ {
			if gs.World[x][i].HasWumpus {
				gs.killWumpus(x, i)
				return
			}
		}
	case West:
		for i := x; i >= 0; i-- {
			if gs.World[i][y].HasWumpus {
				gs.killWumpus(i, y)
				return
			}
		}
	case South:
		for i := y; i >= 0; i-- {
			if gs.World[x][i].HasWumpus {
				gs.killWumpus(x, i)
				return
			}
		}
	}
}

func (gs *GameState) killWumpus(x, y int) {
	gs.WumpusAlive = false
	gs.World[x][y].HasWumpus = false
	gs.LastScream = true
}

func (gs *GameState) checkHazards() {
	sq := gs.World[gs.Agent.X][gs.Agent.Y]
	if sq.HasPit || (sq.HasWumpus && gs.WumpusAlive) {
		gs.Score -= 1000
		gs.GameOver = true
	}
}

func randPos(ex, ey int) (int, int) {
	for {
		x, y := rand.Intn(GridSize), rand.Intn(GridSize)
		if (x != 0 || y != 0) && (x != ex || y != ey) {
			return x, y
		}
	}
}

func addPerceptionToAdjacent(gs *GameState, x, y int, pType string) {
	neighbors := [][2]int{{x - 1, y}, {x + 1, y}, {x, y - 1}, {x, y + 1}}
	for _, n := range neighbors {
		nx, ny := n[0], n[1]
		if nx >= 0 && nx < GridSize && ny >= 0 && ny < GridSize {
			if pType == "stench" {
				gs.World[nx][ny].HasStench = true
			} else if pType == "breeze" {
				gs.World[nx][ny].HasBreeze = true
			}
		}
	}
}
