# Run AIJewel QA on another device

## Requirements

- Docker Desktop (recommended), **or**
- Python 3.11+, Node.js 18+, and Chromium via Playwright

## Quick start (Docker)

1. Unzip this archive.
2. Open a terminal in the unzipped folder (the one that contains `docker-compose.yml`).
3. Run:

```bash
docker compose up --build
```

4. Open:
   - Dashboard: http://localhost:3000
   - API: http://localhost:8000
   - OpenAPI: http://localhost:8000/docs

MediaPipe face/hand models download during the backend Docker image build. Captures and SQLite live under `data/`.

Optional: copy `.env.example` to `.env` before starting if you need custom thresholds.

## Without Docker

### Backend

```bash
cd backend
python -m venv .venv
# Windows: .\.venv\Scripts\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python scripts/download_model.py
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### Frontend

```bash
cd frontend
npm install
# Windows PowerShell:
# $env:NEXT_PUBLIC_API_URL="http://localhost:8000"
# macOS/Linux:
# export NEXT_PUBLIC_API_URL=http://localhost:8000
npm run dev
```

Open http://localhost:3000 (or the port Next.js prints).

## Notes

- Do not commit or copy local `data/results` or secrets. This package is source + Docker config only.
- On Windows, keep the project path short if Docker bind mounts fail (for example `C:\aijewel-earring-qa`).
