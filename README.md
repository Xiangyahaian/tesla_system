# Tesla System

Intelligent cabin agent for vehicle Q&A and control: multi-intent NLU, tool-calling gateway, handbook RAG, and a React cockpit HMI.

Repository: [Xiangyahaian/tesla_system](https://github.com/Xiangyahaian/tesla_system)

---

## Features

| Area | What it does |
|------|----------------|
| Multi-intent orchestration | Rule fast-path + structured NLU; complex utterances use a bounded ReAct loop (≤ 5 steps) |
| Vehicle tools | Climate / seats / cabin / media / navigation / ADAS via JSON Schema tools and a Gateway |
| Handbook RAG | PDF parse → MongoDB / Milvus; dense + sparse + BM25 recall with rerank |
| Memory & safety | Per-user persona / memories / preferences; Policy gate for high-risk actions |
| Cabin HMI | Vite + React: Drive, Apps, Agent trace, Settings; optional ASR / TTS |

---

## Architecture

```text
Voice / text
    │
    ▼
FastAPI  (python run.py · default :6006)
    │
    ├─ NLU / Agent Loop ──► Tool Registry ──► Vehicle Gateway
    │                              └─► per-user vehicle state
    ├─ RAG (handbook retrieval + citations)
    ├─ Profile memory (persona / memories / preferences)
    └─ Static hosting of frontend/dist
```

| Path | Role |
|------|------|
| `app/` | Backend runtime: API, orchestration, NLU, tools, gateway, RAG, speech, sessions |
| `frontend/` | Cabin HMI (React + TypeScript + Zustand) |
| `src/` | Retrieval / ranking / PDF pipeline used by RAG |
| `data/` | Handbook & evaluation corpora (local indexes are gitignored) |
| `tests/` | Unit tests |
| `test/` | Integration / stress fixtures and runners |
| `docs/` | Product, design, demo, and architecture notes |
| `scripts/` | Offline evaluation utilities |
| `state/` | Runtime state (local only; do not commit secrets / session DBs) |

---

## Requirements

- Python 3.10+ (conda env `tesla` recommended)
- Node.js 18+ (frontend build)
- Optional: MongoDB, Milvus (Lite), local vLLM or cloud LLM keys

```bash
conda activate tesla
pip install -r requirements.txt
cp .env.example .env   # fill LLM / map keys
```

### Key environment variables

| Variable | Purpose |
|----------|---------|
| `BAILIAN_*` | Bailian chat / speech (remote) |
| `VLLM_*` | Local vLLM endpoint and model name |
| `AMAP_MAPS_API_KEY` / `AMAP_JS_KEY` | Amap routing and frontend map |
| `APP_PORT` | Server port (default `6006`) |

Never commit `.env`, private keys, or personal API tokens.

---

## Quick start

```bash
cd frontend && npm install && npm run build && cd ..
python run.py
```

Open <http://127.0.0.1:6006>

| Route | Page |
|-------|------|
| `/` | Drive: chat + vehicle / map |
| `/apps` | In-car apps |
| `/agent` | Agent trace and model I/O |
| `/settings` | Model, speech, tool registry |

Frontend hot reload:

```bash
python run.py                 # terminal 1
cd frontend && npm run dev    # terminal 2 (:5173)
```

---

## Design highlights

1. **Dual intent path** — short commands stay on the code fast-path; long / multi-domain utterances go to the LLM.
2. **Plan after observe** — independent tools may run in parallel; dependent steps use tool results; bad args can be corrected.
3. **Per-user vehicle isolation** — one user, one car under `state/sessions/<user_id>/`.
4. **Three-file profile** — persona / memories / preferences rewritten on disk after turns without blocking speech reply.
5. **Safety gate** — speed / gear / tool risk drive reject-or-confirm.

More detail: [docs/product.md](docs/product.md), [docs/design.md](docs/design.md), [docs/demo.md](docs/demo.md).

---

## Tests

```bash
python -m unittest discover -s tests -v
```

Stress / profile runners live under `test/` (require a configured model endpoint).

---

## License

For learning and demonstration unless stated otherwise. Third-party components (including `RAG-Retrieval`) keep their own licenses.
