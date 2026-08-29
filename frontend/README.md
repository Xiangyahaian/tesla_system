# Cabin HMI

Vite + React + TypeScript + Zustand cockpit UI, served by the Cabin Runtime.

## Routes

| Path | Page |
|------|------|
| `/` | Drive: chat, vehicle HUD, map |
| `/apps` | In-car apps |
| `/agent` | Turn timeline and model I/O |
| `/settings` | Model, speech, tool registry |

## Develop

```bash
# terminal 1 — API + static host
conda activate tesla && python run.py

# terminal 2 — Vite HMR
cd frontend
npm install
npm run dev   # http://127.0.0.1:5173 → proxies API to :6006
```

## Production build

```bash
cd frontend && npm run build
python run.py
# http://127.0.0.1:6006  (serves frontend/dist)
```
