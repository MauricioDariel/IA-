"""
visualizer.py  v3 — Enterprise UI with Mode Toggle
====================================================
Dashboard premium con:
  - Toggle "Manual / IA" con paneles dinámicos
  - Enterprise Dark Mode (glassmorphism, paleta slate)
  - Grid ampliado con iconos de fog/percepción/agente
  - Log color-coded (movimiento / percepción / DPLL)
  - Control de velocidad de IA en tiempo real + Pause/Resume
"""

from __future__ import annotations

import argparse
import json
import logging
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any, Dict, Optional
from urllib.parse import urlparse

import requests

from agent import Agent

logging.basicConfig(level=logging.WARNING)

# ── Globals ───────────────────────────────────────────────────────────────────

_lock               = threading.Lock()
_manual_agent: Optional[Agent] = None
_server_url         = "http://localhost:8080"
_ai_paused          = False
_ai_delay_current   = 1.0      # seconds; set from args.delay in main()

MAX_LOG = 30

_state: Dict[str, Any] = {
    "step": 0, "agentX": 0, "agentY": 0, "agentDir": 0,
    "hasGold": False, "hasArrow": True, "wumpusKilled": False,
    "score": 0, "gameOver": False, "message": "", "action": "",
    "perception": {}, "safe": [], "visited": [],
    "gameId": "", "gameNum": 0, "totalGames": 1,
    "wins": 0, "losses": 0, "log": [],
    "running": False, "finished": False,
    "aiPaused": False, "aiDelay": 1.0,
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _push_log(msg: str) -> None:
    with _lock:
        _push_log_nolock(msg)


def _push_log_nolock(msg: str) -> None:
    _state["log"].append(msg)
    if len(_state["log"]) > MAX_LOG:
        _state["log"].pop(0)


def _update_state(**kw) -> None:
    with _lock:
        _state.update(kw)


def _describe_perc(p: dict) -> str:
    flags = [k for k in ("stench", "breeze", "glitter", "bump", "scream") if p.get(k)]
    return ", ".join(flags) if flags else ""


def _sync_agent(agent: Agent, perc: dict, act: str, step: int = 0) -> None:
    global _manual_agent
    _manual_agent = agent
    _state.update(
        step=step, agentX=agent.x, agentY=agent.y, agentDir=agent.dir,
        hasGold=agent.has_gold, hasArrow=agent.has_arrow,
        wumpusKilled=agent.wumpus_killed,
        score=perc.get("score", 0), gameOver=perc.get("gameOver", False),
        message=perc.get("message", ""), action=act, perception=perc,
        safe=[list(c) for c in agent.safe_known],
        visited=[list(c) for c in agent.visited],
    )


# ── GameRunner ────────────────────────────────────────────────────────────────

class GameRunner(threading.Thread):
    def __init__(self, n_games: int, delay: float) -> None:
        super().__init__(daemon=True)
        self.n_games = n_games
        self.session = requests.Session()

    def _new_game(self):
        r = self.session.post(f"{_server_url}/game/new", timeout=10)
        r.raise_for_status()
        d = r.json()
        return d["gameId"], d["perception"]

    def _action(self, gid: str, act: str) -> dict:
        r = self.session.post(
            f"{_server_url}/game/{gid}/action",
            json={"action": act},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()

    def _play_one(self, game_num: int) -> dict:
        global _ai_delay_current
        game_id, perc = self._new_game()
        agent = Agent(game_id)
        agent.update_knowledge(perc)

        with _lock:
            _state.update(
                gameId=game_id, gameNum=game_num, totalGames=self.n_games,
                step=0, running=True, finished=False,
            )
            _sync_agent(agent, perc, "START")
            _push_log_nolock(f"-- Game {game_num}/{self.n_games}  [{game_id[:8]}...]")
            snsr = _describe_perc(perc)
            if snsr:
                _push_log_nolock(f"   [PERCEP] {snsr}")

        step = 0
        while step < 400 and not perc.get("gameOver"):
            # Honour pause
            while _ai_paused and not perc.get("gameOver"):
                time.sleep(0.1)

            step += 1
            act = agent.decide_action()
            try:
                perc = self._action(game_id, act)
            except Exception:
                break

            agent.update_state(act, perc)
            agent.update_knowledge(perc)

            with _lock:
                _sync_agent(agent, perc, act, step)
                snsr = _describe_perc(perc)
                line = f"[{step:3d}] ({agent.x},{agent.y}) => {act}  score={perc.get('score', 0)}"
                if snsr:
                    line += f"  [PERCEP:{snsr}]"
                _push_log_nolock(line)

            time.sleep(_ai_delay_current)

        return perc

    def run(self) -> None:
        wins = losses = 0
        try:
            for i in range(1, self.n_games + 1):
                final = self._play_one(i)
                if "victory" in final.get("message", "").lower():
                    wins += 1
                    _push_log(f"[WIN] VICTORY!  score={final.get('score')}")
                else:
                    losses += 1
                    _push_log(f"[LOSS] Game Over.  score={final.get('score')}")
                with _lock:
                    _state.update(wins=wins, losses=losses)
                if i < self.n_games:
                    time.sleep(1.0)
        except Exception as e:
            _push_log(f"[ERROR] {e}")
        finally:
            _update_state(running=False, finished=True)
            _push_log(f"-- Summary: {wins} wins / {losses} losses out of {self.n_games}")


# ── HTTP Handler ──────────────────────────────────────────────────────────────

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args): pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/state":
            with _lock:
                body = json.dumps(_state).encode()
            self._send(200, "application/json", body)
        elif path == "/":
            self._send(200, "text/html; charset=utf-8", HTML.encode())
        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        data = json.loads(self.rfile.read(length) if length else b"{}")

        if   path == "/action":     self._handle_action(data)
        elif path == "/newgame":    self._handle_newgame()
        elif path == "/ai-control": self._handle_ai_control(data)
        elif path == "/ai-restart": self._handle_ai_restart()
        else:                       self._json(404, {"error": "Not found"})

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    # ── action ───────────────────────────────────────────────────────────────

    def _handle_action(self, data: dict) -> None:
        with _lock:
            game_id  = _state.get("gameId", "")
            game_over = _state.get("gameOver", False)

        if not game_id:
            return self._json(400, {"error": "No active game."})
        if game_over:
            return self._json(400, {"error": "Game Over. Please start a new game."})

        action = data.get("action", "")
        if action not in {"Forward", "TurnLeft", "TurnRight", "Shoot", "Grab", "Climb"}:
            return self._json(400, {"error": f"Invalid action: {action}"})

        try:
            r = requests.post(
                f"{_server_url}/game/{game_id}/action",
                json={"action": action}, timeout=5,
            )
            r.raise_for_status()
            perc = r.json()
        except requests.exceptions.ConnectionError:
            return self._json(503, {"error": "Cannot connect to Go server."})
        except Exception as e:
            return self._json(500, {"error": str(e)})

        with _lock:
            agent = _manual_agent
            if agent:
                agent.update_state(action, perc)
                agent.update_knowledge(perc)
                step = _state.get("step", 0) + 1
                _sync_agent(agent, perc, action, step)
            else:
                x, y, d = _state["agentX"], _state["agentY"], _state["agentDir"]
                step = _state.get("step", 0) + 1
                if action == "Forward" and not perc.get("bump"):
                    offsets = {0:(1,0),1:(0,1),2:(-1,0),3:(0,-1)}
                    dx, dy = offsets.get(d, (0,0))
                    _state["agentX"] = max(0,min(3,x+dx))
                    _state["agentY"] = max(0,min(3,y+dy))
                elif action == "TurnLeft":  _state["agentDir"] = (d+1)%4
                elif action == "TurnRight": _state["agentDir"] = (d-1+4)%4
                elif action == "Grab":      _state["hasGold"] = True
                elif action == "Shoot":
                    _state["hasArrow"] = False
                    if perc.get("scream"): _state["wumpusKilled"] = True
                _state.update(
                    step=step, score=perc.get("score",0),
                    gameOver=perc.get("gameOver",False),
                    message=perc.get("message",""), action=action, perception=perc,
                )
            snsr = _describe_perc(perc)
            line = f"[{_state['step']:3d}] Manual: {action}  score={perc.get('score',0)}"
            if snsr: line += f"  [PERCEP:{snsr}]"
            _push_log_nolock(line)

        self._json(200, {"ok": True, "perception": perc})

    # ── new game ──────────────────────────────────────────────────────────────

    def _handle_newgame(self) -> None:
        try:
            r = requests.post(f"{_server_url}/game/new", timeout=5)
            r.raise_for_status()
            d = r.json()
            game_id, perc = d["gameId"], d["perception"]
        except requests.exceptions.ConnectionError:
            return self._json(503, {"error": "Cannot connect to Go server."})
        except Exception as e:
            return self._json(500, {"error": str(e)})

        new_agent = Agent(game_id)
        new_agent.update_knowledge(perc)
        with _lock:
            game_num = _state.get("gameNum", 0) + 1
            _state.update(gameNum=game_num)
            _sync_agent(new_agent, perc, "START", 0)
            _state.update(gameId=game_id, gameOver=False, message="", running=False)
            _push_log_nolock(f"-- New game [{game_id[:8]}...]")
            snsr = _describe_perc(perc)
            if snsr: _push_log_nolock(f"   [PERCEP] {snsr}")

        self._json(200, {"ok": True, "gameId": game_id, "perception": perc})

    # ── AI control ────────────────────────────────────────────────────────────

    def _handle_ai_control(self, data: dict) -> None:
        global _ai_paused, _ai_delay_current
        if "paused" in data:
            _ai_paused = bool(data["paused"])
        if "delay" in data:
            _ai_delay_current = max(0.1, float(data["delay"]))
        with _lock:
            _state.update(aiPaused=_ai_paused, aiDelay=_ai_delay_current)
        self._json(200, {"ok": True, "paused": _ai_paused, "delay": _ai_delay_current})

    def _handle_ai_restart(self) -> None:
        global _args_games, _ai_delay_current
        # Start a new runner
        with _lock:
            _state.update(running=True, finished=False)
        runner = GameRunner(_args_games, _ai_delay_current)
        runner.start()
        self._json(200, {"ok": True})

    # ── transport ─────────────────────────────────────────────────────────────

    def _send(self, code: int, ct: str, body: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", ct)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _json(self, code: int, data: dict) -> None:
        self._send(code, "application/json", json.dumps(data).encode())


# ── HTML ──────────────────────────────────────────────────────────────────────

HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Wumpus World - Enterprise AI Dashboard</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=JetBrains+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<style>
/* ══ Tokens ══════════════════════════════════════════════════════════════════ */
:root{
  --bg:       #0c0618;
  --surface:  #160930;
  --card:     rgba(18,8,38,.88);
  --glass:    rgba(255,255,255,.03);
  --border:   rgba(168,85,247,.13);
  --b2:       rgba(232,121,249,.45);
  --accent:   #e879f9;
  --accent2:  #22d3ee;
  --green:    #34d399;
  --red:      #f87171;
  --yellow:   #fbbf24;
  --purple:   #c084fc;
  --orange:   #fb923c;
  --text:     #f5f0ff;
  --text2:    #9d8ec0;
  --text3:    #4d3778;
  --r:        14px;
  --r2:       8px;
  --sh:       0 4px 24px rgba(0,0,0,.6);
  --sh2:      0 8px 48px rgba(0,0,0,.75);
  --t:        .22s ease;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
html,body{height:100%;overflow:hidden}
body{
  background:var(--bg);
  background-image:
    radial-gradient(ellipse 80% 55% at 50% -10%,rgba(168,85,247,.12),transparent),
    radial-gradient(ellipse 55% 45% at 90% 90%,rgba(34,211,238,.06),transparent),
    radial-gradient(ellipse 40% 30% at 10% 60%,rgba(232,121,249,.05),transparent);
  color:var(--text);
  font-family:'Inter',sans-serif;
  display:flex;flex-direction:column;
}
::-webkit-scrollbar{width:4px}
::-webkit-scrollbar-track{background:transparent}
::-webkit-scrollbar-thumb{background:rgba(255,255,255,.1);border-radius:4px}

/* ══ Header ══════════════════════════════════════════════════════════════════ */
.hdr{
  flex-shrink:0;display:flex;align-items:center;justify-content:space-between;
  padding:0 24px;height:62px;
  background:rgba(10,4,22,.95);
  border-bottom:1px solid rgba(168,85,247,.18);
  backdrop-filter:blur(20px);
  box-shadow:0 1px 30px rgba(168,85,247,.08);
  z-index:100;
}
.logo{display:flex;align-items:center;gap:12px}
.logo-icon{font-size:1.75rem;filter:drop-shadow(0 0 12px rgba(232,121,249,.7))}
.logo-title{font-size:1.1rem;font-weight:700;
  background:linear-gradient(135deg,var(--accent),var(--accent2));
  -webkit-background-clip:text;-webkit-text-fill-color:transparent;
  letter-spacing:-.3px}
.logo-sub{font-size:.65rem;color:var(--text2);font-family:'JetBrains Mono',monospace;margin-top:1px}

.hdr-right{display:flex;align-items:center;gap:12px}

/* Mode Toggle */
.mode-toggle{
  display:flex;align-items:center;gap:10px;
  background:rgba(255,255,255,.03);
  border:1px solid var(--border);
  border-radius:30px;padding:6px 16px;}
.mode-lbl{font-size:.72rem;font-weight:600;color:var(--text2);transition:color var(--t)}
.mode-lbl.active{color:var(--text)}
.toggle-pill{
  width:50px;height:26px;border-radius:13px;
  background:rgba(255,255,255,.08);
  border:1px solid rgba(255,255,255,.1);
  position:relative;cursor:pointer;
  transition:background var(--t),border-color var(--t);}
.toggle-pill.manual{
  background:rgba(232,121,249,.22);
  border-color:rgba(232,121,249,.5);
  box-shadow:0 0 12px rgba(232,121,249,.2);}
.toggle-knob{
  position:absolute;top:3px;left:3px;
  width:18px;height:18px;border-radius:50%;
  background:#7c6e9a;
  transition:transform .3s cubic-bezier(.34,1.56,.64,1),background var(--t);}
.toggle-pill.manual .toggle-knob{
  transform:translateX(24px);background:var(--accent);
  box-shadow:0 0 8px rgba(232,121,249,.6);}

.status-badge{
  display:flex;align-items:center;gap:6px;
  padding:4px 12px;border-radius:20px;
  font-size:.7rem;font-weight:600;
  font-family:'JetBrains Mono',monospace;
  background:rgba(255,255,255,.04);
  border:1px solid var(--border);color:var(--text2);}
.s-dot{width:7px;height:7px;border-radius:50%;background:var(--text3);transition:all var(--t)}
.s-dot.online{background:var(--green);box-shadow:0 0 6px var(--green)}
.s-dot.err{background:var(--red);box-shadow:0 0 6px var(--red)}

/* ══ Main ════════════════════════════════════════════════════════════════════ */
.main{
  flex:1;display:flex;flex-direction:row;
  overflow:hidden;
}

/* ══ Board Section ════════════════════════════════════════════════════════════ */
.board-sec{
  flex: 3;
  display:flex;flex-direction:column;gap:14px;
  padding:24px;
  overflow-y:auto;
  border-right:1px solid rgba(168,85,247,.18);
  align-items: center; justify-content: center;
}
.board-card{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:var(--r);
  padding:18px;
  backdrop-filter:blur(12px);
  box-shadow:var(--sh2);
}
.board-card-hdr{
  display:flex;justify-content:space-between;align-items:center;margin-bottom:14px}
.board-card-title{
  font-size:.68rem;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:var(--text2)}
.gid-chip{
  font-family:'JetBrains Mono',monospace;font-size:.6rem;
  color:var(--text3);background:rgba(255,255,255,.04);
  padding:2px 8px;border-radius:4px;border:1px solid var(--border)}

/* Grid labels */
.col-lbl{
  display:grid;grid-template-columns:repeat(4,100px);gap:10px;
  margin-left:28px;margin-bottom:6px;}
.col-lbl span{
  font-family:'JetBrains Mono',monospace;font-size:.58rem;
  color:var(--text3);text-align:center}
/* Grid container */
.board-wrapper {
  display: flex; flex-direction: row; align-items: stretch; width: 100%;
}
.row-lbl{
  display:flex;flex-direction:column;justify-content:space-around;
  width: 36px; padding: 12px 0;
}
.row-lbl span{ 
  flex:1; display:flex; align-items:center; justify-content:flex-end; padding-right:8px;
  font-family:'JetBrains Mono',monospace;font-size:.58rem;color:var(--text3);
}

.grid-wrap{
  flex:1; max-width: 70vh; aspect-ratio:1/1;
  position:relative;
  border-radius:var(--r);overflow:hidden;
  box-shadow:var(--sh2),inset 0 0 60px rgba(0,0,0,.4),0 0 40px rgba(168,85,247,.08);
  background:
    linear-gradient(135deg,rgba(232,121,249,.04) 0%,transparent 55%),
    radial-gradient(ellipse at 80% 20%,rgba(34,211,238,.03),transparent 50%),
    radial-gradient(ellipse at 50% 50%,#1a0a30,#0c0618);
  border:1px solid rgba(168,85,247,.2);
}
.grid{
  position:absolute; inset: 12px;
  display:grid;
  grid-template-columns:repeat(4, 1fr);
  grid-template-rows:repeat(4, 1fr);
  gap:8px;
}

/* Cells */
.cell{
  border-radius:10px;
  border:1px solid transparent;
  position:relative;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:4px;overflow:hidden;
  transition:background var(--t),border-color var(--t),box-shadow var(--t);
}
.cell-coord{
  position:absolute;top:5px;left:7px;
  font-family:'JetBrains Mono',monospace;
  font-size:.65rem;color:rgba(255,255,255,.2);
  pointer-events:none}
.cell-icons{font-size:2.4rem;display:flex;gap:4px;pointer-events:none}
.cell-status{position:absolute; bottom:5px; font-size:.6rem;color:rgba(255,255,255,.25);font-family:'JetBrains Mono',monospace;pointer-events:none;letter-spacing:1px}

/* Unknown / fog */
.cell-fog{
  background:
    linear-gradient(135deg,#1a0830 0%,#0c0518 100%);
  border-color:rgba(139,92,246,.08);
}
.cell-fog::before{
  content:'';position:absolute;inset:0;
  background:radial-gradient(circle at 30% 30%,rgba(168,85,247,.04),transparent 65%);
}
.fog-icon{font-size:2rem;opacity:.3}

/* Safe */
.cell-safe{
  background:linear-gradient(135deg,#071825,#040f1a);
  border-color:rgba(34,211,238,.2);
  box-shadow:inset 0 0 12px rgba(34,211,238,.04);
}

/* Visited */
.cell-visited{
  background:linear-gradient(135deg,#200e3a,#160828);
  border-color:rgba(192,132,252,.18);
}

/* Revealed at Game Over */
.cell-revealed{
  background:linear-gradient(135deg,rgba(32,14,58,0.4),rgba(22,8,40,0.4));
  border-color:rgba(192,132,252,0.1);
  opacity: 0.4;
}

/* Agent */
.cell-agent{
  background:linear-gradient(135deg,#2a0e4a,#1e0838);
  border-color:rgba(232,121,249,.5);
  box-shadow:0 0 22px rgba(232,121,249,.18),inset 0 0 22px rgba(232,121,249,.07);
}

/* Stench/breeze aura on agent cell */
@keyframes stenchAura{0%,100%{box-shadow:0 0 22px rgba(232,121,249,.25),inset 0 0 20px rgba(232,121,249,.1)}50%{box-shadow:0 0 38px rgba(232,121,249,.5),inset 0 0 32px rgba(232,121,249,.2)}}
@keyframes breezeAura{0%,100%{box-shadow:0 0 22px rgba(34,211,238,.2),inset 0 0 20px rgba(34,211,238,.08)}50%{box-shadow:0 0 38px rgba(34,211,238,.4),inset 0 0 32px rgba(34,211,238,.15)}}
.cell-has-stench{animation:stenchAura 2.5s ease-in-out infinite}
.cell-has-breeze{animation:breezeAura 2.5s ease-in-out infinite}

/* Cell reveal */
@keyframes reveal{0%{opacity:0;transform:scale(.8)}65%{transform:scale(1.04)}100%{opacity:1;transform:scale(1)}}
.revealing{animation:reveal .4s cubic-bezier(.34,1.56,.64,1) forwards}

/* Agent overlay */
#agent{
  position:absolute;
  z-index:20;pointer-events:none;
  display:flex;align-items:center;justify-content:center;
  transition:left .45s cubic-bezier(.4,0,.2,1),top .45s cubic-bezier(.4,0,.2,1);
}
#agent-inner{
  width:70%;height:70%;
  border-radius:50%;
  background:rgba(34,211,238,.12);
  border:2.5px solid rgba(34,211,238,.9);
  box-shadow:0 0 24px rgba(34,211,238,.6),0 0 48px rgba(34,211,238,.25),0 0 0 4px rgba(34,211,238,.08);
  display:flex;align-items:center;justify-content:center;
  transition:transform .35s cubic-bezier(.34,1.56,.64,1);
  font-size:1.6rem;color:#22d3ee;
  filter:drop-shadow(0 0 10px rgba(34,211,238,1));
}
/* Agent direction icons set via JS data-dir attribute */
#agent[data-dir='0'] #agent-inner::after{content:'▶';color:#22d3ee}
#agent[data-dir='1'] #agent-inner::after{content:'▲';color:#22d3ee}
#agent[data-dir='2'] #agent-inner::after{content:'◀';color:#22d3ee}
#agent[data-dir='3'] #agent-inner::after{content:'▼';color:#22d3ee}

@keyframes bumpFl{0%,100%{border-color:rgba(34,211,238,.9);box-shadow:0 0 24px rgba(34,211,238,.6)}40%{border-color:rgba(248,113,113,.9);box-shadow:0 0 28px rgba(248,113,113,.7)}}
#agent.bumping #agent-inner{animation:bumpFl .35s ease}
@keyframes deathPuls{0%,100%{border-color:rgba(248,113,113,.8)}50%{border-color:rgba(251,191,36,.9);box-shadow:0 0 44px rgba(251,191,36,.8)}}
#agent.dying #agent-inner{animation:deathPuls .5s ease 3}

/* Legend */
.legend{display:flex;gap:10px;flex-wrap:wrap;margin-top:12px}
.leg{display:flex;align-items:center;gap:5px;font-size:.66rem;color:var(--text2)}
.leg-dot{width:10px;height:10px;border-radius:3px;flex-shrink:0}

/* Banner */
.banner{
  border-radius:var(--r);padding:12px 18px;
  font-weight:600;font-size:.88rem;text-align:center;
  display:none;border:1px solid transparent;
  backdrop-filter:blur(8px);}
.banner.show{display:block}
.banner.vic{background:rgba(5,30,20,.8);border-color:var(--green);color:var(--green)}
.banner.def{background:rgba(30,5,10,.8);border-color:var(--red);color:var(--red)}

/* ══ Panels ══════════════════════════════════════════════════════════════════ */
.panels{
  flex: 1;
  min-width: 320px;
  max-width: 380px;
  display:flex;flex-direction:column;gap:10px;
  padding:16px 20px 16px 12px;overflow-y:auto}

.card{
  background:var(--card);
  border:1px solid var(--border);
  border-radius:var(--r);padding:14px 16px;
  box-shadow:var(--sh);
  backdrop-filter:blur(12px);
  flex-shrink:0}
.card-hdr{display:flex;align-items:center;justify-content:space-between;margin-bottom:12px}
.card-hdr h3{
  font-size:.66rem;font-weight:600;letter-spacing:.1em;
  text-transform:uppercase;color:var(--text2)}

/* ── Manual Control Panel ── */
.ctrl-card{
  background:linear-gradient(135deg,rgba(30,10,55,.92),rgba(18,8,38,.92));
  border-color:rgba(232,121,249,.14);}

.dpad-wrap{display:flex;flex-direction:column;align-items:center;gap:6px}

.dpad{display:flex;flex-direction:column;align-items:center;gap:4px;width:100%}
.dpad-row{display:flex;gap:4px;justify-content:center}

.db{
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:0;height:42px;border-radius:var(--r2);
  border:1px solid rgba(168,85,247,.18);
  background:rgba(168,85,247,.06);
  color:var(--text);cursor:pointer;
  font-family:'Inter',sans-serif;
  font-size:.7rem;font-weight:500;
  transition:background var(--t),border-color var(--t),transform .1s,box-shadow var(--t);
  user-select:none}
.db.wide{width:120px}.db.sq{width:50px}
.db-icon{font-size:1.1rem}
.db:hover:not(:disabled){
  background:rgba(232,121,249,.14);
  border-color:rgba(232,121,249,.6);color:var(--accent);
  box-shadow:0 0 16px rgba(232,121,249,.3),0 0 4px rgba(232,121,249,.1) inset}
.db:active:not(:disabled){transform:scale(.93)}
.db:disabled{opacity:.25;cursor:not-allowed}

.act-row{display:grid;grid-template-columns:1fr 1fr;gap:4px;width:100%}
.ab{
  display:flex;align-items:center;justify-content:center;gap:6px;
  height:34px;border-radius:var(--r2);
  border:1px solid rgba(168,85,247,.18);
  background:rgba(168,85,247,.06);
  color:var(--text);cursor:pointer;font-size:.75rem;font-weight:500;
  font-family:'Inter',sans-serif;
  transition:background var(--t),border-color var(--t),transform .1s,box-shadow var(--t);
  user-select:none}
.ab:hover:not(:disabled){
  background:rgba(232,121,249,.12);border-color:rgba(232,121,249,.55);color:var(--accent);
  box-shadow:0 0 14px rgba(232,121,249,.25)}
.ab:active:not(:disabled){transform:scale(.95)}
.ab:disabled{opacity:.25;cursor:not-allowed}
.ab-shoot:hover:not(:disabled){background:rgba(248,113,113,.12)!important;border-color:rgba(248,113,113,.5)!important;color:var(--red)!important;box-shadow:0 0 14px rgba(248,113,113,.25)!important}
.ab-ng:hover:not(:disabled){background:rgba(52,211,153,.08)!important;border-color:rgba(52,211,153,.35)!important;color:var(--green)!important;box-shadow:0 0 12px rgba(52,211,153,.2)!important}

.proc-dot{
  width:8px;height:8px;border-radius:50%;
  border:2px solid rgba(255,255,255,.15);border-top-color:var(--accent);
  animation:spin .65s linear infinite}
@keyframes spin{to{transform:rotate(360deg)}}

/* ── AI Control Panel ── */
.ai-card{
  background:linear-gradient(135deg,rgba(22,8,48,.92),rgba(14,6,32,.92));
  border-color:rgba(34,211,238,.14);}

.ai-pause-btn{
  width:100%;height:44px;border-radius:var(--r2);
  border:1px solid rgba(34,211,238,.3);
  background:rgba(34,211,238,.08);color:var(--accent2);
  font-size:.85rem;font-weight:600;cursor:pointer;
  display:flex;align-items:center;justify-content:center;gap:8px;
  transition:all var(--t);margin-bottom:12px}
.ai-pause-btn:hover{background:rgba(34,211,238,.16);border-color:rgba(34,211,238,.6);box-shadow:0 0 18px rgba(34,211,238,.28)}
.ai-pause-btn.paused{
  background:rgba(232,121,249,.1);border-color:rgba(232,121,249,.35);color:var(--accent)}
.ai-pause-btn.paused:hover{background:rgba(232,121,249,.18);box-shadow:0 0 18px rgba(232,121,249,.25)}

.speed-lbl-row{display:flex;justify-content:space-between;align-items:center;margin-bottom:8px}
.speed-title{font-size:.72rem;color:var(--text2)}
.speed-val{font-family:'JetBrains Mono',monospace;font-size:.8rem;color:var(--accent2);font-weight:600}

.speed-sl{
  -webkit-appearance:none;width:100%;height:4px;border-radius:2px;
  background:rgba(168,85,247,.15);outline:none;cursor:pointer;margin-bottom:6px}
.speed-sl::-webkit-slider-thumb{
  -webkit-appearance:none;width:16px;height:16px;border-radius:50%;
  background:var(--accent2);
  box-shadow:0 0 10px rgba(34,211,238,.6);cursor:pointer}
.speed-hints{display:flex;justify-content:space-between;font-size:.6rem;color:var(--text3)}

.ai-status{
  display:inline-flex;align-items:center;gap:4px;
  padding:2px 8px;border-radius:10px;font-size:.62rem;font-weight:600;
  font-family:'JetBrains Mono',monospace}
.ai-status.run{background:rgba(52,211,153,.1);border:1px solid rgba(52,211,153,.3);color:var(--green)}
.ai-status.pause{background:rgba(251,191,36,.1);border:1px solid rgba(251,191,36,.3);color:var(--yellow)}
.ai-status.done{background:rgba(255,255,255,.05);border:1px solid var(--border);color:var(--text3)}

/* ── Status card ── */
.score-row{display:flex;align-items:baseline;gap:6px;margin-bottom:6px}
.score-num{
  font-size:1.8rem;font-weight:700;
  font-family:'JetBrains Mono',monospace;line-height:1;
  transition:color var(--t)}
.score-unit{font-size:.65rem;color:var(--text2)}
.s-pos{color:var(--green)}.s-neg{color:var(--red)}.s-zero{color:var(--text2)}

.stats{display:grid;grid-template-columns:1fr 1fr;gap:2px 12px;background:rgba(0,0,0,.2);padding:6px 10px;border-radius:var(--r2)}
.stat{display:flex;justify-content:space-between;align-items:center;padding:2px 0}
.s-lbl{font-size:.65rem;color:var(--text2)}
.s-val{font-size:.68rem;font-weight:600;font-family:'JetBrains Mono',monospace;color:var(--text)}

/* ── Merged Perceptions/Inventory ── */
.pills{display:flex;flex-wrap:wrap;gap:4px}
.pill{
  padding:2px 8px;border-radius:20px;
  font-family:'JetBrains Mono',monospace;font-size:.62rem;font-weight:600;
  border:1px solid transparent;transition:all var(--t)}
.pill-off{background:rgba(255,255,255,.03);border-color:rgba(255,255,255,.05);color:var(--text3)}
.pill-stench.on{background:rgba(167,139,250,.12);border-color:rgba(167,139,250,.4);color:var(--purple)}
.pill-breeze.on{background:rgba(56,189,248,.1);border-color:rgba(56,189,248,.35);color:var(--accent)}
.pill-glitter.on{background:rgba(251,191,36,.1);border-color:rgba(251,191,36,.35);color:var(--yellow)}
.pill-bump.on{background:rgba(248,113,113,.1);border-color:rgba(248,113,113,.35);color:var(--red)}
.pill-scream.on{background:rgba(52,211,153,.1);border-color:rgba(52,211,153,.35);color:var(--green)}

/* ── Inventory ── */
.inv{display:grid;grid-template-columns:1fr 1fr;gap:4px;margin-top:6px}
.inv-it{
  display:flex;align-items:center;justify-content:center;gap:6px;
  padding:4px;border-radius:var(--r2);border:1px solid var(--border);
  font-size:.6rem;font-weight:500;transition:all var(--t)}
.inv-icon{font-size:.9rem}
.inv-on{background:rgba(52,211,153,.06);border-color:rgba(52,211,153,.25);color:var(--green)}
.inv-off{background:rgba(255,255,255,.02);color:var(--text3)}

/* ── Standings ── */
.stands{display:grid;grid-template-columns:1fr 1fr;gap:8px}
.stand{text-align:center;padding:10px;border-radius:var(--r2);border:1px solid var(--border)}
.stand-n{font-size:1.75rem;font-weight:700;font-family:'JetBrains Mono',monospace}
.stand-l{font-size:.63rem;color:var(--text2);margin-top:2px}
.stand-win{border-color:rgba(52,211,153,.15)}.stand-win .stand-n{color:var(--green)}
.stand-loss{border-color:rgba(248,113,113,.15)}.stand-loss .stand-n{color:var(--red)}

/* ══ Log Section ══════════════════════════════════════════════════════════════ */
.log-sec{
  flex-shrink:0;padding:0 20px 14px;
  border-top:1px solid var(--border);}
.log-sec .card{border-top-left-radius:0;border-top-right-radius:0;border-top:none}

.log-box{
  background:rgba(8,3,18,.9);
  border:1px solid rgba(168,85,247,.12);
  border-radius:var(--r2);padding:8px 12px;
  height:92px;overflow-y:auto;
  font-family:'JetBrains Mono',monospace;font-size:.67rem;
  line-height:1.78;scroll-behavior:smooth}

/* Log line colors */
.lm{color:#5a4a78}         /* movement */
.lp{color:#d97706}         /* perception - amber */
.ld{color:#22d3ee}         /* DPLL / special - cyan */
.ln{color:#e879f9;font-weight:600}  /* new game - magenta */
.lw{color:#34d399;font-weight:700}  /* victory - green */
.ll{color:#f87171;font-weight:700}  /* loss - red */
.le{color:#f87171}          /* error */
.l-act{color:#facc15;font-weight:700;text-shadow:0 0 8px rgba(250,204,21,.5)} /* grab/shoot action */

/* ══ Overlays ════════════════════════════════════════════════════════════════ */
#flash{position:fixed;inset:0;pointer-events:none;z-index:500;opacity:0}
@keyframes fl{0%{opacity:0}15%{opacity:1}100%{opacity:0}}
.do-fl{animation:fl .7s ease forwards}

#toasts{position:fixed;top:72px;right:20px;z-index:9999;display:flex;flex-direction:column;gap:8px;pointer-events:none}
.toast{
  padding:10px 16px;border-radius:var(--r2);font-size:.76rem;font-weight:500;
  max-width:340px;border:1px solid transparent;
  opacity:0;transform:translateX(16px);
  transition:opacity .25s,transform .25s;pointer-events:none}
.toast.show{opacity:1;transform:translateX(0)}
.t-err{background:#1a0410;border-color:var(--red);color:#fca5a5}
.t-ok{background:#05150e;border-color:var(--green);color:#6ee7b7}
.t-info{background:#120525;border-color:var(--accent);color:#f0abfc}
.t-warn{background:#1a0e04;border-color:var(--yellow);color:var(--yellow)}

#gold-toast {
  position:fixed;top:50%;left:50%;transform:translate(-50%,-50%) scale(0.5);
  background:rgba(251,191,36,.1);border:2px solid #fbbf24;color:#fde68a;
  padding:20px 40px;font-size:1.5rem;font-weight:bold;font-family:'Inter',sans-serif;
  border-radius:12px;box-shadow:0 0 40px rgba(251,191,36,.4);
  opacity:0;pointer-events:none;transition:all 0.4s cubic-bezier(0.34,1.56,0.64,1);
  z-index:10000;text-align:center;backdrop-filter:blur(8px);
}
#gold-toast.show{transform:translate(-50%,-50%) scale(1);opacity:1;}
</style>
</head>
<body>

<div id="flash"></div>
<div id="toasts"></div>
<div id="gold-toast">GOLD FOUND! Escaping to base...</div>

<!-- ══ Header ═════════════════════════════════════════════════════════════════ -->
<header class="hdr">
  <div class="logo">
    <span class="logo-icon">🐍</span>
    <div>
      <div class="logo-title">Wumpus World</div>
      <div class="logo-sub">Enterprise AI Dashboard · DPLL Logic Engine</div>
    </div>
  </div>
  <div class="hdr-right">
    <!-- Mode toggle -->
    <div class="mode-toggle">
      <span class="mode-lbl" id="lbl-ai">🤖 AI</span>
      <div class="toggle-pill" id="mode-pill" onclick="toggleMode()">
        <div class="toggle-knob"></div>
      </div>
      <span class="mode-lbl active" id="lbl-manual">👤 Manual</span>
    </div>
    <!-- Status -->
    <div class="status-badge">
      <span class="s-dot" id="s-dot"></span>
      <span id="s-txt">Connecting...</span>
    </div>
    <div class="status-badge" id="game-badges">Game -</div>
  </div>
</header>

<!-- ══ Main ═══════════════════════════════════════════════════════════════════ -->
<main class="main">

  <!-- ── Left: Board ────────────────────────────────────────────────────── -->
  <div class="board-sec">
    <div class="board-card">
      <div class="board-card-hdr">
        <span class="board-card-title">🗺 4×4 GAME BOARD</span>
        <span class="gid-chip" id="gid-chip">—</span>
      </div>

      <!-- Grid container -->
      <div class="board-wrapper">
        <!-- Row labels -->
        <div class="row-lbl" id="row-lbl"></div>
        <!-- Grid + agent -->
        <div class="grid-wrap" id="grid-wrap">
          <div class="grid" id="grid"></div>
          <div id="agent" data-dir="0">
            <div id="agent-inner"></div>
          </div>
        </div>
      </div>

      <!-- Legend -->
      <div class="legend">
        <div class="leg"><div class="leg-dot" style="background:#200e3a;border:1px solid rgba(192,132,252,.2)"></div>Visited</div>
        <div class="leg"><div class="leg-dot" style="background:#071825;border:1px solid rgba(34,211,238,.22)"></div>Safe (DPLL)</div>
        <div class="leg"><div class="leg-dot" style="background:#1a0830;border:1px solid rgba(139,92,246,.1)"></div>Unknown</div>
        <div class="leg"><div class="leg-dot" style="background:rgba(34,211,238,.15);border:1px solid rgba(34,211,238,.5)"></div>Agent</div>
      </div>
    </div>

    <!-- Banner -->
    <div class="banner" id="banner"></div>
  </div>

  <!-- ── Right: Panels ──────────────────────────────────────────────────── -->
  <div class="panels">

    <!-- MANUAL CONTROL (hidden by default — starts in AI mode) -->
    <div class="card ctrl-card" id="manual-panel" style="display:none">
      <div class="card-hdr">
        <h3>🕹 MANUAL CONTROL</h3>
        <div class="proc-dot" id="proc-dot" style="display:none"></div>
      </div>
      <div class="dpad-wrap">
        <!-- D-pad -->
        <div class="dpad">
          <div class="dpad-row">
            <button class="db wide" id="btn-fwd" onclick="sendManual('Forward')">
              <span class="db-icon">▲</span><span>Forward</span>
            </button>
          </div>
          <div class="dpad-row">
            <button class="db sq" id="btn-left" onclick="sendManual('TurnLeft')">
              <span class="db-icon">◀</span><span>Left</span>
            </button>
            <button class="db sq" id="btn-right" onclick="sendManual('TurnRight')">
              <span class="db-icon">▶</span><span>Right</span>
            </button>
          </div>
        </div>
        <!-- Action buttons -->
        <div class="act-row">
          <button class="ab ab-shoot" id="btn-shoot" onclick="sendManual('Shoot')">🏹 Shoot</button>
          <button class="ab" id="btn-grab"  onclick="sendManual('Grab')">💎 Grab</button>
          <button class="ab" id="btn-climb" onclick="sendManual('Climb')">🪜 Climb</button>
          <button class="ab ab-ng" id="btn-ng" onclick="startNewGame()">🔄 New Game</button>
        </div>
      </div>
    </div>

    <!-- AI CONTROL (shown by default) -->
    <div class="card ai-card" id="ai-panel">
      <div class="card-hdr">
        <h3>🤖 AI CONTROL</h3>
        <span class="ai-status run" id="ai-status-badge">RUNNING</span>
      </div>
      <div style="display:flex;gap:6px;margin-bottom:12px;">
        <button class="ai-pause-btn" style="flex:1;margin-bottom:0;" id="ai-pause-btn" onclick="toggleAIPause()">
          <span id="ai-btn-ico">⏸</span>
          <span id="ai-btn-txt">Pause AI</span>
        </button>
        <button class="ai-pause-btn" style="flex:1;margin-bottom:0;" id="ai-restart-btn" onclick="restartAIGames()" disabled>
          <span id="ai-btn-ico-rst">🔄</span>
          <span>Restart AI</span>
        </button>
      </div>
      <div>
        <div class="speed-lbl-row">
          <span class="speed-title">Execution Speed</span>
          <span class="speed-val" id="speed-val">3.0s / step</span>
        </div>
        <input type="range" class="speed-sl" id="speed-sl"
               min="0.2" max="5" step="0.2" value="3"
               oninput="onSpeedChange(this.value)">
        <div class="speed-hints"><span>Fast (0.2s)</span><span>Slow (5s)</span></div>
      </div>
    </div>

    <!-- Game Status -->
    <div class="card">
      <div class="card-hdr"><h3>📊 GAME STATE</h3></div>
      <div class="score-row">
        <div class="score-num s-zero" id="score-big">0</div>
        <div class="score-unit">Score</div>
      </div>
      <div class="stats">
        <div class="stat"><span class="s-lbl">Step</span><span class="s-val" id="st-step">0</span></div>
        <div class="stat"><span class="s-lbl">Game</span><span class="s-val" id="st-game">-</span></div>
        <div class="stat"><span class="s-lbl">Position</span><span class="s-val" id="st-pos">(0,0)</span></div>
        <div class="stat"><span class="s-lbl">Direction</span><span class="s-val" id="st-dir">East</span></div>
      </div>
    </div>

    <!-- Perceptions & Inventory (Merged) -->
    <div class="card">
      <div class="card-hdr" style="margin-bottom:6px"><h3>👁 PERCEPTIONS & 🎒 INVENTORY</h3></div>
      <div class="pills" id="pills"></div>
      <div class="inv" id="inv"></div>
    </div>

    <!-- Standings -->
    <div class="card">
      <div class="card-hdr"><h3>🏆 SCOREBOARD</h3></div>
      <div class="stands">
        <div class="stand stand-win"><div class="stand-n" id="st-wins">0</div><div class="stand-l">Wins</div></div>
        <div class="stand stand-loss"><div class="stand-n" id="st-losses">0</div><div class="stand-l">Losses</div></div>
      </div>
    </div>

  </div><!-- end panels -->
</main>

<!-- ══ Log ════════════════════════════════════════════════════════════════════ -->
<div class="log-sec">
  <div class="card" style="padding-top:10px">
    <div class="card-hdr" style="margin-bottom:8px">
      <h3>📋 Agent Log <span style="font-size:.6rem;color:var(--text3);font-weight:400;margin-left:4px">gray=mov · amber=percep · cyan=DPLL</span></h3>
      <div class="proc-dot" id="log-spin" style="display:none"></div>
    </div>
    <div class="log-box" id="log-box"></div>
  </div>
</div>

<!-- ══ JavaScript ══════════════════════════════════════════════════════════════ -->
<script>
'use strict';

/* ── Constants ──────────────────────────────────────────────────────────── */
const CELL = 100, GAP = 10, PAD = 16, STEP = CELL + GAP;
const GRID_N = 4;
const DIR_NAMES = ['East','North','West','South'];
const DIR_CHARS = ['\u25B6','\u25B2','\u25C0','\u25BC'];  // ▶▲◀▼

/* ── Global State ────────────────────────────────────────────────────────── */
let prev = {};
let isBusy = false;
let isManual = false;      // starts in AI mode
let aiPaused = false;
let aiDelay = 3.0;
const revealedCells = new Set();
const cellPercep = {};     // "x,y" -> {stench, breeze, glitter}

/* ── Build static DOM ────────────────────────────────────────────────────── */
(function buildDOM(){
  // Col labels
  const cl = document.getElementById('col-lbl');
  if (cl) {
    for(let x=0; x<GRID_N; x++){
      const s = document.createElement('span');
      s.textContent = `x=${x}`;
      Object.assign(s.style,{textAlign:'center',fontSize:'.58rem',color:'var(--text3)',fontFamily:"'JetBrains Mono',monospace"});
      cl.appendChild(s);
    }
  }
  // Row labels
  const rl = document.getElementById('row-lbl');
  for(let y=GRID_N-1; y>=0; y--){
    const s = document.createElement('span');
    s.textContent = `y=${y}`;
    rl.appendChild(s);
  }
  // Grid cells
  const g = document.getElementById('grid');
  for(let y=GRID_N-1; y>=0; y--){
    for(let x=0; x<GRID_N; x++){
      const c = document.createElement('div');
      c.id = `c${x}${y}`;
      c.className = 'cell cell-fog';
      c.innerHTML =
        `<span class="cell-coord">(${x},${y})</span>`+
        `<div class="cell-icons" id="ci${x}${y}"></div>`+
        `<div class="cell-status" id="cs${x}${y}"></div>`;
      g.appendChild(c);
    }
  }
})();

/* ── Agent ────────────────────────────────────────────────────────────────── */
const agentEl    = document.getElementById('agent');
const agentInner = document.getElementById('agent-inner');

function posAgent(x, y, dir){
  requestAnimationFrame(() => {
    const cell = document.getElementById(`c${x}${y}`);
    const gWrap = document.getElementById('grid-wrap');
    if(!cell || !gWrap) return;
    agentEl.style.width = cell.offsetWidth + 'px';
    agentEl.style.height = cell.offsetHeight + 'px';
    
    // Position safely regardless of CSS framework metrics using actual DOM rects.
    const cRect = cell.getBoundingClientRect();
    const wRect = gWrap.getBoundingClientRect();
    agentEl.style.left = (cRect.left - wRect.left) + 'px';
    agentEl.style.top  = (cRect.top - wRect.top) + 'px';
    agentEl.setAttribute('data-dir', dir);
  });
}
window.addEventListener('resize', () => {
  if (prev.agentX !== undefined) posAgent(prev.agentX, prev.agentY, prev.agentDir);
});

/* ── Grid rendering ────────────────────────────────────────────────────────── */
function updateCellPercep(s){
  const key = `${s.agentX},${s.agentY}`;
  const p = s.perception || {};
  if(s.step > 0){
    cellPercep[key] = {
      stench:  !!p.stench,
      breeze:  !!p.breeze,
      glitter: !!p.glitter && !s.hasGold
    };
  }
}

function updateGrid(s){
  const safe    = new Set((s.safe    || []).map(c=>`${c[0]},${c[1]}`));
  const visited = new Set((s.visited || []).map(c=>`${c[0]},${c[1]}`));
  const p = s.perception || {};
  const ax = s.agentX, ay = s.agentY;

  let shouldReveal = false;
  if(s.gameOver && s.message){
    shouldReveal = true;
  }

  for(let y=0; y<GRID_N; y++){
    for(let x=0; x<GRID_N; x++){
      const key   = `${x},${y}`;
      const cell  = document.getElementById(`c${x}${y}`);
      const icons = document.getElementById(`ci${x}${y}`);
      const stat  = document.getElementById(`cs${x}${y}`);
      const isAgt = (x===ax && y===ay);
      const isVis = visited.has(key);
      const isSafe= safe.has(key);
      
      let isRevealedEnd = false;
      let endCell = null;
      if(shouldReveal && p.fullBoard){
        endCell = p.fullBoard.find(c => c.x === x && c.y === y);
        if(endCell && !isVis) isRevealedEnd = true;
      }

      // Class
      let cls = 'cell ';
      if(isAgt)      cls += 'cell-agent';
      else if(isVis) cls += 'cell-visited';
      else if(isRevealedEnd) cls += 'cell-revealed';
      else if(isSafe)cls += 'cell-safe';
      else           cls += 'cell-fog';

      // Sensor aura on agent cell
      if(isAgt){
        if(p.stench) cls += ' cell-has-stench';
        if(p.breeze) cls += ' cell-has-breeze';
      }

      // Reveal animation
      if((isVis||isSafe||isRevealedEnd) && !revealedCells.has(key)){
        revealedCells.add(key);
        cls += ' revealing';
        const el = cell;
        setTimeout(()=>el.classList.remove('revealing'), 450);
      }
      cell.className = cls;

      // Icons
      let ic = '';
      if(isAgt){
        // agent overlay handles visual
        ic = '';
        stat.textContent = '';
      } else if(isVis){
        const cp = cellPercep[key] || {};
        if(cp.stench)  ic += '<span title="Stench">🦨</span>';
        if(cp.breeze)  ic += '<span title="Breeze">💨</span>';
        if(cp.glitter) ic += '<span title="Gold">✨</span>';
        stat.textContent = '';
      } else if(isRevealedEnd && endCell){
        if(endCell.hasWumpus) ic += '<span title="Wumpus">💀</span>';
        if(endCell.hasPit)    ic += '<span title="Pit">🕳️</span>';
        if(endCell.hasGold)   ic += '<span title="Gold">✨</span>';
        stat.textContent = 'REVEALED';
      } else if(isSafe){
        ic = '<span title="DPLL Safe">🛡</span>';
        stat.textContent = 'SAFE';
      } else {
        ic = '<span class="fog-icon">🌑</span>';
        stat.textContent = '';
      }
      icons.innerHTML = ic;
    }
  }
}

/* ── UI Panels ─────────────────────────────────────────────────────────────── */
function updateScore(s){
  const v = s.score||0;
  const el = document.getElementById('score-big');
  el.textContent = (v > 0 ? '+' : '') + v;
  el.className = 'score-num ' + (v>0?'s-pos':v<0?'s-neg':'s-zero');
}
function updateStats(s){
  document.getElementById('st-step').textContent = s.step||0;
  document.getElementById('st-game').textContent = s.totalGames>0 ? `${s.gameNum||'-'}/${s.totalGames}` : '-';
  document.getElementById('st-pos').textContent  = `(${s.agentX},${s.agentY})`;
  document.getElementById('st-dir').textContent  = DIR_NAMES[s.agentDir]||'?';
  document.getElementById('game-badges').textContent = `Game ${s.gameNum||'-'}`;
  const gid = s.gameId||'';
  document.getElementById('gid-chip').textContent = gid ? gid.substring(0,10)+'...' : '-';
}
function updatePerceptions(s){
  const p = s.perception||{};
  const SENSORS = [
    ['stench','pill-stench','🦨 Stench'],
    ['breeze','pill-breeze','💨 Breeze'],
    ['glitter','pill-glitter','✨ Glitter'],
    ['bump','pill-bump','🧱 Bump'],
    ['scream','pill-scream','😱 Scream'],
  ];
  document.getElementById('pills').innerHTML = SENSORS.map(([k,cls,lbl])=>{
    const on = !!p[k];
    return `<span class="pill ${cls} ${on?'on':'pill-off'}">${lbl}</span>`;
  }).join('');
}
function updateInventory(s){
  document.getElementById('inv').innerHTML = `
    <div class="inv-it ${s.hasArrow?'inv-on':'inv-off'}"><span class="inv-icon">🏹</span>Arrow</div>
    <div class="inv-it ${s.hasGold?'inv-on':'inv-off'}"><span class="inv-icon">💎</span>Gold</div>
    <div class="inv-it ${s.wumpusKilled?'inv-on':'inv-off'}"><span class="inv-icon">💀</span>Wumpus</div>`;
}
function updateStandings(s){
  document.getElementById('st-wins').textContent   = s.wins||0;
  document.getElementById('st-losses').textContent = s.losses||0;
}
function updateBanner(s){
  const b = document.getElementById('banner');
  if(s.gameOver && s.message){
    const vic = s.message.toLowerCase().includes('victory');
    b.className = 'banner show '+(vic?'vic':'def');
    b.textContent = vic ? '🏆 '+s.message : '💀 '+s.message;
  } else { b.className = 'banner'; }
}
function updateConn(ok){
  const d = document.getElementById('s-dot');
  const t = document.getElementById('s-txt');
  d.className = 's-dot '+(ok?'online':'err');
  t.textContent = ok ? 'Server online' : 'Disconnected';
}
function updateAIPanel(s){
  const badge = document.getElementById('ai-status-badge');
  const restartBtn = document.getElementById('ai-restart-btn');
  if(s.finished){ 
    badge.textContent='DONE'; badge.className='ai-status done'; 
    restartBtn.disabled = false;
  }
  else if(s.aiPaused||aiPaused){ 
    badge.textContent='PAUSED'; badge.className='ai-status pause'; 
    restartBtn.disabled = false;
  }
  else { 
    badge.textContent='RUNNING'; badge.className='ai-status run'; 
    restartBtn.disabled = true;
  }
  document.getElementById('log-spin').style.display = (s.running && !s.finished) ? 'block':'none';
}

/* ── Log ───────────────────────────────────────────────────────────────────── */
let prevLogLen = 0;
function updateLog(s){
  const lines = s.log||[];
  if(lines.length === prevLogLen) return;
  prevLogLen = lines.length;
  const box = document.getElementById('log-box');
  box.innerHTML = lines.map(classifyLine).join('');
  box.scrollTo({top: box.scrollHeight, behavior: 'smooth'});
}

function classifyLine(l){
  const ll = l.toLowerCase();
  let cls = 'lm';
  if(l.startsWith('[WIN]') || ll.includes('victory') || ll.includes('victoria')) cls = 'lw';
  else if(l.startsWith('[LOSS]') || ll.includes('end.')) cls = 'll';
  else if(l.startsWith('[ERROR]')) cls = 'le';
  else if(l.startsWith('--')) cls = 'ln';
  else if(ll.includes('=> grab') || ll.includes('=> shoot')) cls = 'l-act';
  else if(ll.includes('[percep') || ll.includes('stench') || ll.includes('breeze') ||
          ll.includes('glitter') || ll.includes('scream') || ll.includes('bump')) cls = 'lp';
  else if(ll.includes('dpll') || ll.includes('safe:') || ll.includes('[dpll]')) cls = 'ld';
  const escaped = l.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  return `<div class="${cls}">${escaped}</div>`;
}

/* ── Animations ─────────────────────────────────────────────────────────────── */
function screenFlash(color){
  const fl = document.getElementById('flash');
  fl.style.background = color;
  fl.classList.remove('do-fl');
  void fl.offsetWidth;
  fl.classList.add('do-fl');
  setTimeout(()=>fl.classList.remove('do-fl'), 750);
}
function triggerBump(){ agentEl.classList.add('bumping'); setTimeout(()=>agentEl.classList.remove('bumping'),380); }
function triggerDeath(){ agentEl.classList.add('dying'); screenFlash('rgba(248,113,113,.2)'); setTimeout(()=>agentEl.classList.remove('dying'),2000); }
function triggerVic(){ screenFlash('rgba(52,211,153,.2)'); showToast('🏆 VICTORY! Escaped with the gold.','ok'); }
function triggerArrow(){ screenFlash('rgba(248,113,113,.3)'); showToast('☠️ Wumpus eliminated! The scream echoes...','ok'); }

function showGoldToast() {
  const dt = document.getElementById('gold-toast');
  if(!dt) return;
  dt.className = 'show';
  setTimeout(() => dt.className = '', 3500);
}

function flashBorder(color){
  const wrap = document.getElementById('grid-wrap');
  if(!wrap) return;
  wrap.style.boxShadow = `var(--sh2), inset 0 0 60px rgba(0,0,0,.4), 0 0 80px ${color}`;
  wrap.style.borderColor = color;
  wrap.style.transition = 'none';
  setTimeout(() => {
    wrap.style.transition = 'all 1.2s ease';
    wrap.style.boxShadow = '';
    wrap.style.borderColor = '';
  }, 100);
}

/* ── Polling ────────────────────────────────────────────────────────────────── */
async function poll(){
  try{
    const r = await fetch('/state');
    if(!r.ok) throw 0;
    const s = await r.json();
    updateConn(true);

    // Events
    const act = s.action||'';
    if(act==='Forward' && s.agentX===prev.agentX && s.agentY===prev.agentY && s.step!==prev.step) triggerBump();
    if(!prev.wumpusKilled && s.wumpusKilled && act==='Shoot') triggerArrow();
    if(!prev.gameOver && s.gameOver){
      if(s.message&&s.message.toLowerCase().includes('victory')) triggerVic();
      else if(s.message&&(s.message.toLowerCase().includes('died')||s.message.toLowerCase().includes('eaten'))) triggerDeath();
    }
    if(act==='Grab' && s.perception && s.perception.glitter && !prev.hasGold){
      showGoldToast();
    }

    // Update agent perception history
    if(s.step !== prev.step) {
      updateCellPercep(s);
      // Perception subtle flash
      const p = s.perception || {};
      if(p.stench && !p.breeze) flashBorder('rgba(248, 113, 113, 0.5)'); // light red
      else if(!p.stench && p.breeze) flashBorder('rgba(34, 211, 238, 0.4)'); // light blue
      else if(p.stench && p.breeze) flashBorder('rgba(192, 132, 252, 0.5)'); // purple
    }

    // Updates
    posAgent(s.agentX, s.agentY, s.agentDir);
    updateGrid(s);
    updateScore(s);
    updateStats(s);
    updatePerceptions(s);
    updateInventory(s);
    updateStandings(s);
    updateBanner(s);
    updateLog(s);
    updateAIPanel(s);

    prev = s;
  }catch(_){ updateConn(false); }
  setTimeout(poll, 300);
}

/* ── Mode Toggle ────────────────────────────────────────────────────────────── */
function toggleMode(){
  isManual = !isManual;
  const pill = document.getElementById('mode-pill');
  pill.classList.toggle('manual', isManual);
  document.getElementById('lbl-manual').classList.toggle('active', isManual);
  document.getElementById('lbl-ai').classList.toggle('active', !isManual);
  document.getElementById('manual-panel').style.display = isManual ? 'block' : 'none';
  document.getElementById('ai-panel').style.display     = isManual ? 'none'  : 'block';
}
// Default: AI mode
document.getElementById('lbl-ai').classList.add('active');
document.getElementById('lbl-manual').classList.remove('active');

/* ── Button management ──────────────────────────────────────────────────────── */
const CTRL_IDS = ['btn-fwd','btn-left','btn-right','btn-shoot','btn-grab','btn-climb'];
function setBusy(b){
  isBusy = b;
  document.getElementById('proc-dot').style.display = b ? 'block':'none';
  CTRL_IDS.forEach(id=>{ const el=document.getElementById(id); if(el) el.disabled=b; });
}

/* ── Manual send ────────────────────────────────────────────────────────────── */
async function sendManual(action){
  if(isBusy) return;
  setBusy(true);
  try{
    const r = await fetch('/action',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({action})});
    const d = await r.json();
    if(!r.ok) showToast('Error: '+(d.error||'?'),'err');
  }catch(e){ showToast('Cannot connect to server.','err'); }
  finally{ setBusy(false); }
}

/* ── New game ────────────────────────────────────────────────────────────────── */
async function startNewGame(){
  try{
    const r = await fetch('/newgame',{method:'POST'});
    const d = await r.json();
    if(!r.ok) showToast('Error: '+(d.error||'?'),'err');
    else{
      revealedCells.clear();
      Object.keys(cellPercep).forEach(k=>delete cellPercep[k]);
      showToast('🎮 New game started!','info');
    }
  }catch(e){ showToast('Cannot connect.','err'); }
}

/* ── AI Controls ─────────────────────────────────────────────────────────────── */
async function toggleAIPause(){
  aiPaused = !aiPaused;
  const btn = document.getElementById('ai-pause-btn');
  document.getElementById('ai-btn-ico').textContent = aiPaused ? '\u25B6' : '\u23F8';
  document.getElementById('ai-btn-txt').textContent = aiPaused ? 'Resume AI' : 'Pause AI';
  btn.classList.toggle('paused', aiPaused);
  try{
    await fetch('/ai-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({paused:aiPaused})});
  }catch(_){}
}

async function onSpeedChange(val){
  aiDelay = parseFloat(val);
  document.getElementById('speed-val').textContent = aiDelay.toFixed(1)+'s / step';
  // Update slider gradient
  const sl = document.getElementById('speed-sl');
  const pct = ((aiDelay-0.2)/(5-0.2)*100).toFixed(1);
  sl.style.background = `linear-gradient(to right, var(--accent2) 0%, var(--accent2) ${pct}%, rgba(255,255,255,.1) ${pct}%, rgba(255,255,255,.1) 100%)`;
  try{
    await fetch('/ai-control',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({delay:aiDelay})});
  }catch(_){}
}

async function restartAIGames(){
  const btn = document.getElementById('ai-restart-btn');
  btn.disabled = true;
  try{ 
    await fetch('/ai-restart',{method:'POST'}); 
    revealedCells.clear();
    Object.keys(cellPercep).forEach(k=>delete cellPercep[k]);
    showToast('🚀 AI batch restarted!','info');
  } catch(e){}
}


/* ── Toast ───────────────────────────────────────────────────────────────────── */
function showToast(msg, type='info'){
  const c = document.getElementById('toasts');
  const t = document.createElement('div');
  const cls = {ok:'t-ok',err:'t-err',info:'t-info',warn:'t-warn'}[type]||'t-info';
  t.className = `toast ${cls}`;
  t.textContent = msg;
  c.appendChild(t);
  requestAnimationFrame(()=>t.classList.add('show'));
  setTimeout(()=>{ t.classList.remove('show'); setTimeout(()=>t.remove(),300); }, 4000);
}

/* ── Keyboard shortcuts ──────────────────────────────────────────────────────── */
document.addEventListener('keydown', e=>{
  if(!isManual || isBusy) return;
  const map = {'ArrowUp':'Forward','ArrowLeft':'TurnLeft','ArrowRight':'TurnRight','s':'Shoot','g':'Grab','c':'Climb'};
  const act = map[e.key];
  if(act){ e.preventDefault(); sendManual(act); }
  if(e.key==='n'){ e.preventDefault(); startNewGame(); }
  if(e.key==='p'){ e.preventDefault(); if(!isManual) toggleAIPause(); }
});

/* ── Init ────────────────────────────────────────────────────────────────────── */
onSpeedChange(3.0);
showToast('AI Mode active. Use the toggle to switch to Manual.','info');
poll();
</script>
</body>
</html>"""


# ── Entry point ───────────────────────────────────────────────────────────────

_args_games = 1

def main() -> None:
    global _server_url, _ai_delay_current, _args_games

    ap = argparse.ArgumentParser(description="Wumpus World — Dashboard v3")
    ap.add_argument("--server", default="http://localhost:8080")
    ap.add_argument("--games",  type=int,   default=1)
    ap.add_argument("--delay",  type=float, default=3.0)
    ap.add_argument("--port",   type=int,   default=5050)
    args = ap.parse_args()

    _server_url       = args.server
    _ai_delay_current = args.delay
    _args_games       = args.games

    try:
        requests.get(args.server, timeout=3)
    except Exception:
        print(f"\n[ERROR] Could not connect to {args.server}")
        print("  Make sure the Go server is running.")
        return

    runner = GameRunner(args.games, args.delay)
    runner.start()

    class _Server(HTTPServer):
        allow_reuse_address = True

    httpd = _Server(("localhost", args.port), Handler)
    url = f"http://localhost:{args.port}"
    print(f"\n[VIS] Dashboard Enterprise v3 at: {url}")
    print(f"      Games: {args.games}   Initial delay: {args.delay}s")
    print("      Press Ctrl+C to stop.\n")
    webbrowser.open(url)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n[VIS] Stopped.")


if __name__ == "__main__":
    main()
