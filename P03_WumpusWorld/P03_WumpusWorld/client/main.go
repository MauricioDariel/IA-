// main.go
//
// HTTP client and game loop for the DPLL-based Wumpus World agent. This
// program speaks to the server defined by server.go / game.go over the
// following JSON endpoints:
//
//	POST /game/new                   → { "gameId": "...", "perception": {...} }
//	POST /game/{gameId}/action       ← { "action": "Forward|TurnLeft|TurnRight|Shoot|Grab|Climb" }
//	                                → Perception JSON
//
// Five commands are supported from the command line, matching the actions
// requested by the assignment:
//
//	Move straight     → "Forward"
//	Turn left         → "TurnLeft"
//	Turn right        → "TurnRight"
//	Launch arrow      → "Shoot"
//	Start a new game  → POST /game/new
//
// The default behaviour (no flags) is to run a full autonomous DPLL agent
// that plays `-games` complete matches end-to-end.
package main

import (
	"bytes"
	"encoding/json"
	"flag"
	"fmt"
	"io"
	"log"
	"net/http"
	"os"
	"strings"
	"time"
)

// Perception mirrors the JSON shape returned by the server.
type Perception struct {
	Stench   bool   `json:"stench"`
	Breeze   bool   `json:"breeze"`
	Glitter  bool   `json:"glitter"`
	Bump     bool   `json:"bump"`
	Scream   bool   `json:"scream"`
	Score    int    `json:"score"`
	GameOver bool   `json:"gameOver"`
	Message  string `json:"message"`
}

// NewGameResponse mirrors the response body of POST /game/new.
type NewGameResponse struct {
	GameID     string     `json:"gameId"`
	Perception Perception `json:"perception"`
}

// actionRequest is the body of POST /game/{id}/action.
type actionRequest struct {
	Action string `json:"action"`
}

// Transport centralises the HTTP calls to the server.
type Transport struct {
	BaseURL string
	HTTP    *http.Client
}

// NewTransport returns a Transport with sensible defaults.
func NewTransport(baseURL string) *Transport {
	return &Transport{
		BaseURL: strings.TrimRight(baseURL, "/"),
		HTTP:    &http.Client{Timeout: 10 * time.Second},
	}
}

// StartNewGame requests a fresh game from the server and returns its id
// together with the initial perception.
func (t *Transport) StartNewGame() (string, Perception, error) {
	resp, err := t.HTTP.Post(t.BaseURL+"/game/new", "application/json", nil)
	if err != nil {
		return "", Perception{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated && resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return "", Perception{}, fmt.Errorf("server returned %s: %s", resp.Status, string(body))
	}
	var ng NewGameResponse
	if err := json.NewDecoder(resp.Body).Decode(&ng); err != nil {
		return "", Perception{}, fmt.Errorf("decoding new-game response: %w", err)
	}
	return ng.GameID, ng.Perception, nil
}

// SendAction submits an action for a given game and returns the resulting
// perception.
func (t *Transport) SendAction(gameID, action string) (Perception, error) {
	payload, err := json.Marshal(actionRequest{Action: action})
	if err != nil {
		return Perception{}, err
	}
	url := fmt.Sprintf("%s/game/%s/action", t.BaseURL, gameID)
	resp, err := t.HTTP.Post(url, "application/json", bytes.NewReader(payload))
	if err != nil {
		return Perception{}, err
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusOK {
		body, _ := io.ReadAll(resp.Body)
		return Perception{}, fmt.Errorf("server returned %s: %s", resp.Status, string(body))
	}
	var p Perception
	if err := json.NewDecoder(resp.Body).Decode(&p); err != nil {
		return Perception{}, fmt.Errorf("decoding action response: %w", err)
	}
	return p, nil
}

// describePerception returns a compact human-readable rendering of p.
func describePerception(p Perception) string {
	flags := make([]string, 0, 5)
	if p.Stench {
		flags = append(flags, "stench")
	}
	if p.Breeze {
		flags = append(flags, "breeze")
	}
	if p.Glitter {
		flags = append(flags, "glitter")
	}
	if p.Bump {
		flags = append(flags, "bump")
	}
	if p.Scream {
		flags = append(flags, "scream")
	}
	if len(flags) == 0 {
		flags = append(flags, "(nothing)")
	}
	return fmt.Sprintf("score=%d sensors=[%s]", p.Score, strings.Join(flags, ","))
}

// playOne runs one complete game end-to-end using the DPLL agent. It
// returns the final perception.
func playOne(t *Transport) (Perception, error) {
	gameID, perception, err := t.StartNewGame()
	if err != nil {
		return Perception{}, err
	}
	log.Printf("=== New game %s ===", gameID)
	log.Printf("  initial: %s", describePerception(perception))

	agent := NewAgent(gameID)
	agent.UpdateKnowledge(perception)

	const maxSteps = 400 // safety valve
	for step := 1; step <= maxSteps && !perception.GameOver; step++ {
		action := agent.DecideAction()
		log.Printf("[step %3d] at (%d,%d) facing %s → %s",
			step, agent.x, agent.y, dirName(agent.dir), action)

		perception, err = t.SendAction(gameID, action)
		if err != nil {
			return perception, fmt.Errorf("step %d (%s): %w", step, action, err)
		}
		agent.UpdateState(action, perception)
		agent.UpdateKnowledge(perception)
		log.Printf("           → %s%s",
			describePerception(perception),
			gameOverSuffix(perception))
	}
	log.Printf("=== Game %s finished: %s (score %d) ===",
		gameID, perception.Message, perception.Score)
	return perception, nil
}

func gameOverSuffix(p Perception) string {
	if !p.GameOver {
		return ""
	}
	return fmt.Sprintf(" [GAME OVER: %s]", p.Message)
}

// runOneShot is an interactive helper: it starts a fresh game and executes
// a single action so that the five "manual" commands from the assignment
// can be exercised from the command line.
func runOneShot(t *Transport, action string) {
	gameID, perception, err := t.StartNewGame()
	if err != nil {
		log.Fatalf("start game: %v", err)
	}
	fmt.Printf("Started game %s.\nInitial perception: %s\n",
		gameID, describePerception(perception))

	if action == "" {
		return
	}
	p, err := t.SendAction(gameID, action)
	if err != nil {
		log.Fatalf("action %s: %v", action, err)
	}
	fmt.Printf("After %s: %s%s\n", action, describePerception(p), gameOverSuffix(p))
}

func main() {
	log.SetFlags(log.Ltime | log.Lmicroseconds)

	baseURL := flag.String("server", "http://localhost:8080", "Wumpus World server base URL")
	games := flag.Int("games", 1, "Number of games to play autonomously")
	command := flag.String("cmd", "", "Run a single command and exit: new | forward | left | right | shoot")
	flag.Usage = func() {
		fmt.Fprintln(os.Stderr, `Wumpus World DPLL client.

Usage:
  wumpus-client [flags]

Flags:`)
		flag.PrintDefaults()
		fmt.Fprintln(os.Stderr, `
One-shot commands (via -cmd):
  new      Start a new game and print the initial perception.
  forward  Start a new game then send "Move straight" once.
  left     Start a new game then send "Turn left" once.
  right    Start a new game then send "Turn right" once.
  shoot    Start a new game then send "Launch arrow" once.

Without -cmd the client plays -games complete games driven by the DPLL agent.`)
	}
	flag.Parse()

	t := NewTransport(*baseURL)

	if *command != "" {
		switch strings.ToLower(*command) {
		case "new":
			runOneShot(t, "")
		case "forward", "move", "straight":
			runOneShot(t, "Forward")
		case "left", "turnleft":
			runOneShot(t, "TurnLeft")
		case "right", "turnright":
			runOneShot(t, "TurnRight")
		case "shoot", "arrow":
			runOneShot(t, "Shoot")
		default:
			log.Fatalf("unknown -cmd %q (see -h)", *command)
		}
		return
	}

	var wins, losses int
	totalScore := 0
	for i := 1; i <= *games; i++ {
		p, err := playOne(t)
		if err != nil {
			log.Fatalf("game %d failed: %v", i, err)
		}
		totalScore += p.Score
		if strings.Contains(strings.ToLower(p.Message), "victory") {
			wins++
		} else {
			losses++
		}
	}
	log.Printf("Summary: %d games, %d won, %d lost, average score %.1f",
		*games, wins, losses, float64(totalScore)/float64(*games))
}
