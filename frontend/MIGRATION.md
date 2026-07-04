# APEX-7 — Migration Dash → React + FastAPI

## Architecture

```
apex7-trader/
├── api/                    ← NEW: FastAPI backend (non-invasif)
│   ├── main.py             ← App FastAPI + lifespan (démarre le controller)
│   ├── broadcaster.py      ← WebSocket hub + polling de _state toutes les 500ms
│   ├── serializers.py      ← Portfolio → JSON
│   └── routes/
│       ├── ws.py           ← GET /ws  (WebSocket)
│       ├── portfolio.py    ← GET /api/portfolio, /trades, /analytics
│       ├── market.py       ← GET /api/market/macro|watchlist|sectors|correlation
│       └── control.py      ← POST /api/control/mode|pause|resume|watchlist/*
├── frontend/               ← NEW: React 18 + Vite + TypeScript
│   ├── package.json
│   ├── vite.config.ts      ← proxy /api et /ws → localhost:8000
│   ├── src/
│   │   ├── App.tsx         ← Shell + routing des onglets
│   │   ├── types/          ← TypeScript types (Snapshot, Position, etc.)
│   │   ├── hooks/
│   │   │   ├── useWebSocket.ts   ← WS avec reconnexion automatique
│   │   │   └── useApex.ts        ← REST hooks (watchlist, macro, analytics…)
│   │   ├── styles/
│   │   │   └── globals.css       ← Design tokens CSS variables
│   │   └── components/
│   │       ├── layout/Topbar.tsx
│   │       ├── live/
│   │       │   ├── LiveTab.tsx
│   │       │   ├── EquityChart.tsx
│   │       │   └── ActivityLog.tsx
│   │       ├── terminal/TerminalTab.tsx
│   │       └── analytics/AnalyticsTab.tsx
├── agents/                 ← INCHANGÉ
├── core/                   ← INCHANGÉ
├── market_data/            ← INCHANGÉ
└── dashboard/              ← Peut rester (Dash) ou être supprimé
```

## Démarrage

### 1. Dépendances backend

```bash
uv add fastapi uvicorn[standard]
```

### 2. Lancer le backend FastAPI

```bash
uvicorn api.main:app --reload --port 8000
```

Le backend démarre `start_controller()` automatiquement (agent loop + postmortem thread).

### 3. Lancer le frontend

```bash
cd frontend
npm install
npm run dev          # → http://localhost:5173
```

Vite proxy `/api` et `/ws` vers `localhost:8000` — pas de CORS à configurer.

### 4. Build de production

```bash
cd frontend
npm run build        # → frontend/dist/
```

Servir `dist/` avec nginx ou via FastAPI StaticFiles :

```python
from fastapi.staticfiles import StaticFiles
app.mount("/", StaticFiles(directory="frontend/dist", html=True), name="static")
```

## Flux de données

```
Portfolio._lock  ←→  _state / _ctrl (controller.py)
                              ↓
                    api/broadcaster.py (poll 500ms)
                              ↓
                    WebSocket /ws  →  React useWebSocket
                              ↓
                    Snapshot → LiveTab / TerminalTab / AnalyticsTab
```

## Flux WebSocket

Chaque message est un objet `{ type, data }` :

| type | description |
|------|-------------|
| `snapshot` | État complet : portfolio, positions, votes, log (toutes les 500ms) |
| `agent_votes` | Votes détaillés quand le cycle change |

## Compatibilité Dash

`dashboard/` reste intact. Tu peux faire tourner les deux en parallèle :
- **Dash** : `uv run python main.py` (port 8050)
- **React** : `uvicorn api.main:app` + `npm run dev` (ports 8000/5173)

Une fois React validé en production, tu peux supprimer `dashboard/`.

## Variables d'environnement

Identiques à l'existant (`.env.example`). Aucune variable supplémentaire requise.

## Branche Git recommandée

```bash
git checkout -b feat/react-frontend
git add api/ frontend/
git commit -m "feat: migrate dashboard to FastAPI + React"
```
