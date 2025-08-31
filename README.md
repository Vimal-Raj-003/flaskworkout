# Lovable Fitness Flask API

Flask API that exposes workout planning, tracking, and voice coaching endpoints. Ready for Lovable frontends.

## Quickstart

```bash
python -m venv .venv
# Windows
. ./.venv/Scripts/Activate.ps1
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
cp .env.example .env   # fill keys if you have them
python app.py
```

API base (local): `http://127.0.0.1:8000`

### Health
`GET /api/health`

### Workout
- `GET /api/bodyparts`
- `GET /api/exercises?bodypart=upper arms&offset=0&limit=10`
- `POST /api/workout/plan` (JSON body: `{ "bodyparts": ["upper arms"], "limit_per_part": 4, "level": "beginner" }`)
- `POST /api/workout/session/start`
- `POST /api/workout/session/<id>/complete-set`
- `POST /api/workout/session/<id>/finish`
- `GET /api/progress/summary?period=week|month|year`

### Voice
- `POST /api/voice/coach`
- `GET /api/voice/audio/<token>`
- `POST /api/voice/transcribe` (multipart form-data: `file`)

## Lovable fetch examples

```js
// Plan
await fetch("http://127.0.0.1:8000/api/workout/plan", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ bodyparts: ["upper arms","back"], limit_per_part: 3, level: "beginner" })
}).then(r => r.json());

// Start session
await fetch("http://127.0.0.1:8000/api/workout/session/start", {
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify({ title: "Evening Workout", exercises: [{ name:"Push Ups", sets:3, reps:12, rest:60 }] })
}).then(r => r.json());
```

## Deploy
Use `gunicorn` with a platform like Render/Railway/Fly.io. Start command:
```
gunicorn -w 2 -b 0.0.0.0:$PORT app:app
```
