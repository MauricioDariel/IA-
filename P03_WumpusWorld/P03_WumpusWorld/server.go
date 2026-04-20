// server.go
package main

import (
	"crypto/rand"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"strings"
	"sync"
)

// GameStore holds all active games, protected by a mutex for concurrent access
type GameStore struct {
	sync.Mutex
	games map[string]*GameState
}

// ActionRequest is the expected JSON body for an action POST request
type ActionRequest struct {
	Action  string `json:"action"`
	DPLLLog string `json:"dpll_log,omitempty"`
}

// NewGameResponse is the JSON response when a new game is created
type NewGameResponse struct {
	GameID     string     `json:"gameId"`
	Perception Perception `json:"perception"`
}

var store = GameStore{
	games: make(map[string]*GameState),
}

// generateUUID creates a simple UUID using crypto/rand
func generateUUID() string {
	bytes := make([]byte, 16)
	rand.Read(bytes)
	return hex.EncodeToString(bytes)
}

// extractGameID extracts gameId from URL path like /game/{gameId}/action
func extractGameID(path string) (string, error) {
	parts := strings.Split(path, "/")
	if len(parts) >= 4 && parts[1] == "game" && parts[3] == "action" {
		return parts[2], nil
	}
	return "", fmt.Errorf("invalid path format")
}

// pretty-print minimal del mundo para debugging
func printGameState(gs *GameState) {
	var b strings.Builder
	b.WriteString("=== Wumpus World ===\n")
	// imprimimos filas desde arriba para que se vea como un mapa
	for y := GridSize - 1; y >= 0; y-- {
		for x := 0; x < GridSize; x++ {
			ch := '.'
			sq := gs.World[x][y]
			// Prioridad: agente > wumpus (si vivo) > gold > pit
			if gs.Agent.X == x && gs.Agent.Y == y {
				switch gs.Agent.Direction {
				case East:
					ch = '>'
				case North:
					ch = '^'
				case West:
					ch = '<'
				case South:
					ch = 'v'
				default:
					ch = 'A'
				}
			} else if sq.HasWumpus && gs.WumpusAlive {
				ch = 'W'
			} else if sq.HasGold {
				ch = 'G'
			} else if sq.HasPit {
				ch = 'O'
			}
			b.WriteString(fmt.Sprintf(" %c", ch))
		}
		b.WriteString("\n")
	}
	b.WriteString(fmt.Sprintf("Agent=(%d,%d) Dir=%d Arrow=%v Gold=%v Score=%d GameOver=%v WumpusAlive=%v\n",
		gs.Agent.X, gs.Agent.Y, gs.Agent.Direction, gs.Agent.HasArrow, gs.Agent.HasGold, gs.Score, gs.GameOver, gs.WumpusAlive))
	b.WriteString("====================\n")
	log.Print(b.String())
}

func serveReadmeHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodGet {
		http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
		return
	}

	http.ServeFile(w, r, "README.md")
}

func main() {
	http.HandleFunc("/", serveReadmeHandler)
	http.HandleFunc("/game/new", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}
		newGameHandler(w, r)
	})

	http.HandleFunc("/game/", func(w http.ResponseWriter, r *http.Request) {
		if r.Method != http.MethodPost {
			http.Error(w, "Method not allowed", http.StatusMethodNotAllowed)
			return
		}

		if !strings.HasSuffix(r.URL.Path, "/action") {
			http.NotFound(w, r)
			return
		}

		actionHandler(w, r)
	})

	log.Println("Wumpus World server starting on http://localhost:8080")
	log.Fatal(http.ListenAndServe(":8080", nil))
}

func newGameHandler(w http.ResponseWriter, r *http.Request) {
	store.Lock()
	defer store.Unlock()

	gameID := generateUUID()
	gs := newGame()
	store.games[gameID] = gs

	resp := NewGameResponse{
		GameID:     gameID,
		Perception: gs.getPerception(),
	}

	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusCreated)
	json.NewEncoder(w).Encode(resp)
	log.Println("New game created with ID:", gameID)

	// imprimir estado del mundo para debugging
	printGameState(gs)
}

// actionHandler processes a player's action for a specific game
func actionHandler(w http.ResponseWriter, r *http.Request) {
	gameID, err := extractGameID(r.URL.Path)
	if err != nil {
		http.Error(w, "Invalid game ID in path", http.StatusBadRequest)
		return
	}

	store.Lock()
	defer store.Unlock()

	gs, ok := store.games[gameID]
	if !ok {
		http.Error(w, "Game not found", http.StatusNotFound)
		return
	}

	var req ActionRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, "Invalid request body", http.StatusBadRequest)
		return
	}

	gs.processAction(req.Action)
	log.Println("Processed action for game ID:", gameID, "Action:", req.Action)

	// --- Live DPLL Brain Log ---
	if req.DPLLLog != "" {
		log.Println("┌─── 🧠 DPLL Agent Reasoning ───────────────────────────────")
		log.Println("│ ", req.DPLLLog)
		log.Println("└────────────────────────────────────────────────────────────")
	}

	// imprimir estado del mundo tras la acción
	printGameState(gs)

	// Clean up finished games from memory
	if gs.GameOver {
		defer delete(store.games, gameID)
		log.Println("Game over. Cleaning up game ID:", gameID)
	}

	w.Header().Set("Content-Type", "application/json")
	json.NewEncoder(w).Encode(gs.getPerception())
}
