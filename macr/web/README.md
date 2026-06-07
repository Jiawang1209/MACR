# MACR Run Viewer (V2 sub-project 1)

Read-only web viewer for `.macr/runs/`.

## Run

```bash
# 1. build the SPA once
cd frontend && npm install && npm run build && cd ..
# 2. serve API + SPA
macr web --runs-dir .macr/runs --port 8000
# open http://127.0.0.1:8000
```

Dev mode (hot reload): `cd frontend && npm run dev` (proxies /api to :8000).
