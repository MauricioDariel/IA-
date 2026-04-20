# Wumpus World — Python DPLL Client

Cliente en Python que juega el **Wumpus World** de forma autónoma usando el
algoritmo **DPLL** (Davis–Putnam–Logemann–Loveland) como motor de inferencia.

Se conecta al servidor Go (`server.go` / `game.go`) mediante HTTP/JSON.

---

## Estructura de archivos

```
python_client/
  dpll.py          -- Motor DPLL: is_sat() y entails()
  kb.py            -- Base de conocimiento en CNF (Wumpus World)
  agent.py         -- Agente: planificacion BFS + DPLL
  main.py          -- Cliente HTTP + bucle de juego + CLI
  requirements.txt -- Solo necesita: requests
  test_dpll_kb.py  -- Tests unitarios (no necesitan el servidor)
```

---

## Requisitos

- Python 3.8 o superior
- La libreria `requests`:

```bash
python -m pip install requests
```

---

## Como ejecutar

### 1. Primero, iniciar el servidor Go (en otra terminal, en la carpeta raiz)

```bash
go run server.go game.go
# El servidor queda escuchando en http://localhost:8080
```

### 2. Ejecutar el cliente Python (dentro de python_client/)

**Jugar 1 partida autonoma completa:**
```bash
python main.py
```

**Jugar 5 partidas y ver resumen:**
```bash
python main.py --games 5
```

**Comandos manuales requeridos por el profesor:**
```bash
python main.py --cmd new        # Iniciar nueva partida
python main.py --cmd forward    # Mover recto (Forward)
python main.py --cmd left       # Girar izquierda (TurnLeft)
python main.py --cmd right      # Girar derecha (TurnRight)
python main.py --cmd shoot      # Lanzar flecha (Shoot)
```

**Con log detallado:**
```bash
python main.py --debug --games 3
```

---

## Como funciona el algoritmo DPLL

### Variables proposicionales (cuadricula 4x4)

| Variable      | Significado                        | Rango de IDs |
|---------------|------------------------------------|--------------|
| `Pit(x,y)`    | Hay un pozo en la celda (x,y)     | 1 ... 16     |
| `Wumpus(x,y)` | El Wumpus esta en la celda (x,y)  | 17 ... 32    |

### Axiomas iniciales en la KB

- `¬Pit(0,0)` y `¬Wumpus(0,0)` — el agente empieza ahi vivo.
- `¬W(i) ∨ ¬W(j)` para todo par `i ≠ j` — hay exactamente un Wumpus.
- `W(0,0) ∨ W(0,1) ∨ ... ∨ W(3,3)` — existe al menos un Wumpus.

### Observaciones por celda visitada

| Percepcion  | Clausulas que se agregan a la KB           |
|-------------|--------------------------------------------|
| No brisa    | `¬Pit(n)` para cada vecino `n`            |
| Brisa       | `Pit(n1) ∨ Pit(n2) ∨ ...` (vecinos)      |
| No hedor    | `¬Wumpus(n)` para cada vecino `n`         |
| Hedor       | `Wumpus(n1) ∨ Wumpus(n2) ∨ ...`          |
| Grito       | `¬Wumpus(x,y)` para toda celda           |

### Consultas de seguridad

Una celda `(x,y)` es segura si y solo si:

```
KB ∧ Pit(x,y)    es INSATISFACIBLE   (DPLL refutacion)
KB ∧ Wumpus(x,y) es INSATISFACIBLE   (DPLL refutacion)
```

### Estrategia del agente

1. **Grab** — si hay brillo y no tiene el oro.
2. **Climb** — si tiene el oro y esta en (0,0).
3. **Explorar** — BFS hacia la celda segura no visitada de menor costo.
4. **Disparar** — si el Wumpus esta confirmado, planea posicion y dispara.
5. **Retirarse** — si no hay frontera segura, vuelve a (0,0) y escala.

---

## Ejecutar los tests unitarios

No necesitan el servidor Go activo:

```bash
python test_dpll_kb.py
```

Salida esperada:
```
PASS  is_sat([]) => True
PASS  is_sat([[1]]) => True
...
Results: 13 passed, 0 failed
```
