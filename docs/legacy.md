# Legacy entry points

The following paths belong to the V1 demo stack and are **not** the default runtime:

- `run.py`（原 V1 入口）
- `infer.py`
- `context/`
- local `skills/` / `webui/` (gitignored, not published)

Use the Cabin Runtime instead:

```bash
python -m app
```

Current architecture lives under `app/` (API, NLU, agent loop, gateway, RAG, speech, sessions). The React HMI lives under `frontend/`.
