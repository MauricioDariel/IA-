# 🗺️ Wumpus World - Enterprise AI Dashboard

This project is a modern, full-stack implementation of the classic artificial intelligence scenario **"Wumpus World"**. It features a robust Client-Server architecture with a custom logical inference engine (DPLL) and a stunning "Enterprise Dark Mode" visual dashboard.

---

## 🏗️ Architecture

The project consists of three main components working simultaneously:

1. **Go Server (`game.go` & `server.go`)**: Acts as the authoritative Environment. It randomly generates the 4x4 grid (placing the Wumpus, Pits, and Gold), enforces the strict game rules, and processes agent actions to return localized sensory perceptions.
2. **Python Logic Agent (`agent.py` & `kb.py`)**: An autonomous AI agent relying on the Davis-Putnam-Logemann-Loveland (DPLL) propositional logic algorithm. It stores sensory data in a Knowledge Base (KB) to deduce safe vs. dangerous paths dynamically.
3. **JS/Python Visualizer (`visualizer.py`)**: A premium web dashboard rendered via HTML, Tailwind CSS, and Vanilla Javascript. It serves an HTTP API that acts as a proxy between the front-end user and the Go Server while synchronously displaying the logical state of the AI Agent.

---

## 🎮 How the Game Works

The Wumpus World is a dark cave represented by a `4x4` grid.

- **The Agent** always starts at `(0,0)` facing **East** and holds exactly `1 Arrow`.
- **The Wumpus**: A deadly beast that eats anyone who enters its room. It emits a **Stench** in adjacent squares. It can be permanently killed by shooting the arrow into its room.
- **Pits**: Bottomless holes. Entering a pit results in instant death. They emit a **Breeze** in adjacent squares.
- **Gold**: The winning objective. It emits a **Glitter** in its current square.
- **Goal**: Find the gold, grab it, safely traverse back to `(0,0)`, and execute the `Climb` action.

### Sensory "Percepts"

The agent never sees the full board layout. Instead, every time it moves or acts, the environment replies with an array of binary sensors depending entirely on the *current cell*: `[Stench, Breeze, Glitter, Bump, Scream]`.

---

## 🔄 How the Board Obtains Data from the Go Server

Our architecture is strictly decoupled. The Go server **does not hand out the map** to the user or the AI during active gameplay. All grid and agent logic rendered in the dashboard depends heavily on the HTTP request cycle:

### 1. Game Initialization

When the visualizer launches a new game, it sends an initial API request:
`POST http://localhost:8080/game/new`
**Response:**

```json
{
  "gameId": "xyz-123",
  "perception": {
    "stench": false, 
    "breeze": false, 
    "glitter": false, 
    "bump": false, 
    "scream": false
  }
}
```

The Python intermediate server (`visualizer.py`) stores this and launches an empty `Agent`.

### 2. Action & Polling Loop

When the AI (or a manual user) decides to take an action (e.g., `Forward`), the Python client pings the Go server:
`POST http://localhost:8080/game/{gameId}/action`
with the Body Payload: `{"action": "Forward"}`

The `visualizer.py` script then **merges** the Go Server's perception response with the internal memory metrics of the Python `agent.py`. The browser frontend executes an asynchronous `poll()` loop every 300ms, hitting our Python middleware at `GET http://localhost:5050/state`.

**The resulting unified payload tells the frontend everything it needs to dynamically paint the UI:**

- **Agent Coordinates:** Extrapolated by the Python handler based on successful non-bumping movements.
- **Cell Status:** The agent emits two lists: `visited` cells and `safe_known` cells (mathematically proven safe by DPLL). The Javascript paints these cells in solid colors. The rest of the undiscovered map remains covered in the "Fog of war".
- **Real-Time Perceptions:** The JSON tells Javascript whether to render a breeze or stench aura animation directly under the Agent icon.

### 3. Game Over (The Reveal)

When the Agent eventually dies or wins, the Go server evaluates the final score and flips a `gameOver: true` boolean.
**Exclusively at this stage**, the Go Server adds a special `FullBoard` array object to the JSON payload.

The Javascript detects the `FullBoard` array—containing the true coordinates of all Pits, the Wumpus, and the Gold. The front-end clears the fog and triggers a `cell-revealed` CSS animation that renders the remaining map layout at a 40% opacity so the user can analyze what was hidden in the darkness.

---

## 🚀 How to Run

1. Open your terminal in the project's root folder.
2. Initialize the automated orchestrator (It will compile the Go server and launch the Web Dashboard autonomously):
   ```bash
   python launcher.py --visual --games 5 --delay 3
   ```
3. Open `http://localhost:5050` in any modern web browser.
4. Enjoy switching between Manual and AI modes, altering execution speed, or restarting the AI batch seamlessly from the UI!
