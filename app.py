import os
import io
import math
import base64
import datetime as dt
import json
from typing import List, Optional

from flask import Flask, request, jsonify, send_file, abort
from flask_cors import CORS
from dotenv import load_dotenv
import requests
from sqlalchemy import create_engine, Column, Integer, String, DateTime, ForeignKey, Boolean
from sqlalchemy.orm import sessionmaker, declarative_base, relationship
from pydantic import BaseModel, Field

# ---- Load env ----
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
ELEVENLABS_API_KEY = os.getenv("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID = os.getenv("ELEVENLABS_VOICE_ID", "21m00Tcm4TlvDq8ikWAM")
EXERCISEDB_BASE = os.getenv("EXERCISEDB_BASE", "https://www.exercisedb.dev/api/v1")
SQLITE_PATH = os.getenv("SQLITE_PATH", "fitness.db")
ALLOWED_ORIGINS = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,https://preview--adapti-fit-voice.lovable.app").split(",")]

# ---- Flask ----
app = Flask(__name__)
#CORS(app, resources={r"/api/*": {"origins": ALLOWED_ORIGINS}})
CORS(app)
# ---- DB ----
engine = create_engine(f"sqlite:///{SQLITE_PATH}", echo=False, future=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
Base = declarative_base()

class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    id = Column(Integer, primary_key=True)
    user_id = Column(String, nullable=True)
    title = Column(String, nullable=False)
    start_time = Column(DateTime, default=dt.datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    status = Column(String, default="active")  # active|finished
    total_sets = Column(Integer, default=0)
    completed_sets = Column(Integer, default=0)
    exercises = relationship("SessionExercise", back_populates="session", cascade="all, delete")

class SessionExercise(Base):
    __tablename__ = "session_exercises"
    id = Column(Integer, primary_key=True)
    session_id = Column(Integer, ForeignKey("workout_sessions.id"))
    order_index = Column(Integer, default=0)
    name = Column(String, nullable=False)
    sets = Column(Integer, default=1)
    reps = Column(Integer, default=10)
    rest = Column(Integer, default=60)
    completed_sets = Column(Integer, default=0)
    session = relationship("WorkoutSession", back_populates="exercises")

Base.metadata.create_all(bind=engine)

# ---- DTOs ----
class PlanRequest(BaseModel):
    bodyparts: List[str] = Field(default_factory=lambda: ["upper arms"])
    limit_per_part: int = 4
    level: str = "beginner"

class VoiceCoachRequest(BaseModel):
    exercise: str
    sets: int = 3
    reps: int = 12
    rest: int = 60
    tempo_sec_per_rep: int = 3
    level: str = "intermediate"

# ---- Helpers ----
def http_json(url: str, params=None, headers=None, timeout=20):
    r = requests.get(url, params=params, headers=headers, timeout=timeout)
    r.raise_for_status()
    return r.json()

def fetch_bodyparts():
    return http_json(f"{EXERCISEDB_BASE}/bodyparts")

def fetch_exercises(bodypart: str, offset: int = 0, limit: int = 10):
    params = {"offset": offset, "limit": limit}
    return http_json(f"{EXERCISEDB_BASE}/bodyparts/{bodypart}/exercises", params=params)

def openai_complete_json(system_prompt: str, user_prompt: str):
    """Generate JSON from OpenAI (robust to missing key)."""
    if not OPENAI_API_KEY:
        # Fallback if key not set
        return {
            "coach_script": f"Let's do {user_prompt}. Keep your core tight and breathe steady.",
            "segments": [{"say": "Start now", "duration_secs": 5}]
        }
    try:
        # OpenAI Python SDK v1
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role":"system","content":system_prompt},
                {"role":"user","content":user_prompt}
            ],
            temperature=0.6,
        )
        content = resp.choices[0].message.content
        return json.loads(content)
    except Exception as e:
        # Minimal fallback
        return {
            "coach_script": f"Start your exercise: {user_prompt}.",
            "segments": [{"say":"Start now", "duration_secs": 5}]
        }

def elevenlabs_tts_mp3(text: str) -> bytes:
    if not ELEVENLABS_API_KEY:
        # Return a tiny silent mp3 if no key present
        return b""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{ELEVENLABS_VOICE_ID}"
    headers = {
        "xi-api-key": ELEVENLABS_API_KEY,
        "accept": "audio/mpeg",
        "content-type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_multilingual_v2",
        "voice_settings": {"stability": 0.5, "similarity_boost": 0.7}
    }
    r = requests.post(url, headers=headers, json=payload, timeout=60)
    r.raise_for_status()
    return r.content

def fetch_muscles():
    return http_json(f"{EXERCISEDB_BASE}/muscles")

def fetch_equipments():
    return http_json(f"{EXERCISEDB_BASE}/equipments")

# ---- Routes ----
@app.get("/api/muscles")
def api_muscles():
    try:
        return jsonify(fetch_muscles())
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.get("/api/equipments")
def api_equipments():
    try:
        return jsonify(fetch_equipments())
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    
@app.get("/api/health")
def health():
    return {"status":"ok","time": dt.datetime.utcnow().isoformat()}

# ExerciseDB proxy
@app.get("/api/bodyparts")
def api_bodyparts():
    try:
        return jsonify(fetch_bodyparts())
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.get("/api/exercises")
def api_exercises():
    bodypart = request.args.get("bodypart", "upper arms")
    offset = int(request.args.get("offset", 0))
    limit = int(request.args.get("limit", 3))
    try:
        data = fetch_exercises(bodypart, offset, limit)
        return jsonify(data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# Workout plan generation
@app.post("/api/workout/plan")
def api_plan():
    payload = PlanRequest(**request.json) if request.is_json else PlanRequest()
    # Fetch exercises for each bodypart
    catalog = {}
    for bp in payload.bodyparts:
        try:
            catalog[bp] = fetch_exercises(bp, 0, payload.limit_per_part)
        except Exception:
            catalog[bp] = []

    system = "You are a certified strength coach. Create a balanced 7-day plan in JSON."
    user = json.dumps({
        "level": payload.level,
        "catalog_sample": catalog,
        "instructions": [
            "Use only exercises from the provided catalog list when possible.",
            "Return JSON with keys: week_plan (list of 7 days), total_estimated_time_mins.",
            "Each day: title, exercises[{name, sets, reps, rest}], estimatedTime, difficulty."
        ]
    })
    plan = openai_complete_json(system, user)
    if "week_plan" not in plan:
        # Simple fallback: rotate through catalog
        days = []
        bps = list(catalog.keys()) or ["upper arms"]
        for i in range(7):
            bp = bps[i % len(bps)]
            exercises = [
                {"name": ex.get("name","Push-ups"), "sets": 3, "reps": 12, "rest": 60}
                for ex in (catalog.get(bp) or [])[:payload.limit_per_part]
            ] or [{"name":"Bodyweight Squat","sets":3,"reps":15,"rest":60}]
            days.append({
                "title": f"{bp.title()} Focus",
                "exercises": exercises,
                "estimatedTime": 25,
                "difficulty": "Intermediate"
            })
        plan = {"week_plan": days, "total_estimated_time_mins": sum(d["estimatedTime"] for d in days)}
    return jsonify(plan)

# Tracker endpoints
@app.post("/api/workout/session/start")
def api_session_start():
    data = request.get_json(force=True)
    title = data.get("title","Workout Session")
    exercises = data.get("exercises", [])
    db = SessionLocal()
    try:
        sess = WorkoutSession(title=title, status="active")
        total_sets = 0
        db.add(sess)
        db.flush()  # get sess.id
        for i, ex in enumerate(exercises):
            sets = int(ex.get("sets",1))
            reps = int(ex.get("reps",10))
            rest = int(ex.get("rest",60))
            total_sets += sets
            db.add(SessionExercise(
                session_id=sess.id,
                order_index=i,
                name=ex.get("name","Exercise"),
                sets=sets, reps=reps, rest=rest,
                completed_sets=0
            ))
        sess.total_sets = total_sets
        db.commit()
        return jsonify({"session_id": sess.id, "total_sets": total_sets})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.post("/api/workout/session/<int:sess_id>/complete-set")
def api_session_complete_set(sess_id: int):
    data = request.get_json(force=True)
    ex_idx = int(data.get("exercise_index", 0))
    db = SessionLocal()
    try:
        sess = db.get(WorkoutSession, sess_id)
        if not sess or sess.status != "active":
            return jsonify({"error":"session not found/active"}), 404
        ex = db.query(SessionExercise).filter_by(session_id=sess_id, order_index=ex_idx).first()
        if not ex:
            return jsonify({"error":"exercise not found"}), 404
        if ex.completed_sets < ex.sets:
            ex.completed_sets += 1
            sess.completed_sets += 1
        db.commit()
        finished = sess.completed_sets >= sess.total_sets
        return jsonify({
            "session_id": sess.id,
            "exercise_index": ex_idx,
            "exercise_completed_sets": ex.completed_sets,
            "session_completed_sets": sess.completed_sets,
            "session_total_sets": sess.total_sets,
            "workout_finished": finished
        })
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.post("/api/workout/session/<int:sess_id>/finish")
def api_session_finish(sess_id: int):
    db = SessionLocal()
    try:
        sess = db.get(WorkoutSession, sess_id)
        if not sess:
            return jsonify({"error":"not found"}), 404
        sess.status = "finished"
        sess.end_time = dt.datetime.utcnow()
        db.commit()
        return jsonify({"ok": True})
    except Exception as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        db.close()

@app.get("/api/progress/summary")
def api_progress_summary():
    period = request.args.get("period","week")
    db = SessionLocal()
    try:
        now = dt.datetime.utcnow()
        if period == "month":
            since = now - dt.timedelta(days=30)
        elif period == "year":
            since = now - dt.timedelta(days=365)
        else:
            since = now - dt.timedelta(days=7)

        q = db.query(WorkoutSession).filter(WorkoutSession.start_time >= since)
        sessions = q.all()
        workouts = len(sessions)
        total_time = 0
        xp = 0
        for s in sessions:
            # rough estimates: 3 min per set, 10 XP per set
            total_time += (s.completed_sets * 3)
            xp += (s.completed_sets * 10)
        # streak: naive calc (days with any workout in the last N days)
        days = set([s.start_time.date() for s in sessions])
        streak = len(days)
        return jsonify({"workouts": workouts, "totalTime": total_time, "xpGained": xp, "streak": streak})
    finally:
        db.close()

# Voice coaching
@app.post("/api/voice/coach")
def api_voice_coach():
    payload = VoiceCoachRequest(**request.get_json(force=True))
    tempo = max(1, payload.tempo_sec_per_rep)
    est_set_secs = max(10, payload.reps * tempo)
    segments = [
        {"say": f"Get ready for {payload.exercise}. {payload.reps} reps. Keep good form.", "duration_secs": 5},
    ]
    # build per-set cues
    for s in range(1, payload.sets+1):
        segments.append({"say": f"Set {s} begin. Count each rep with steady breathing.", "duration_secs": 3})
        segments.append({"say": "Work.", "duration_secs": est_set_secs})
        if s < payload.sets:
            segments.append({"say": f"Rest {payload.rest} seconds. Shake out tension.", "duration_secs": payload.rest})
    segments.append({"say": "Great job. Hydrate and prepare for the next exercise.", "duration_secs": 5})

    system = "You are a concise, motivating fitness coach. Output JSON with 'coach_script' and 'segments'."
    user = f"""
    Exercise: {payload.exercise}
    Sets: {payload.sets}, Reps: {payload.reps}, Rest: {payload.rest}s, Level: {payload.level}
    Produce a short energetic coach_script (<= 120 words). Use plain language, no emojis.
    """
    ai = openai_complete_json(system, user)
    coach_script = ai.get("coach_script") or "Let's go! Keep your core tight and breathe steadily."

    # Merge AI intro with timeline segments
    timeline = ai.get("segments") or segments
    # If AI timeline missing durations, fall back to our computed timeline
    for seg in timeline:
        if "duration_secs" not in seg:
            seg["duration_secs"] = 3

    # Create TTS mp3
    try:
        audio_bytes = elevenlabs_tts_mp3(coach_script)
    except Exception as e:
        audio_bytes = b""

    # Save audio to a temp in-memory file and expose via /api/voice/audio/<token>
    import base64, os
    token = base64.urlsafe_b64encode(os.urandom(8)).decode().rstrip("=")
    cache_dir = os.path.join(os.path.dirname(__file__), "cache_audio")
    os.makedirs(cache_dir, exist_ok=True)
    audio_path = os.path.join(cache_dir, f"{token}.mp3")
    with open(audio_path, "wb") as f:
        f.write(audio_bytes)

    return jsonify({
        "script": coach_script,
        "timeline": timeline,
        "audio_url": f"/api/voice/audio/{token}"
    })

@app.get("/api/voice/audio/<token>")
def api_voice_audio(token: str):
    cache_dir = os.path.join(os.path.dirname(__file__), "cache_audio")
    path = os.path.join(cache_dir, f"{token}.mp3")
    if not os.path.exists(path):
        abort(404)
    return send_file(path, mimetype="audio/mpeg", as_attachment=False, download_name="coach.mp3")

# Voice transcription (Whisper)
@app.post("/api/voice/transcribe")
def api_transcribe():
    if "file" not in request.files:
        return jsonify({"error":"file field required"}), 400
    file = request.files["file"]
    try:
        if not OPENAI_API_KEY:
            # Fallback: not available
            return jsonify({"text": "(transcription unavailable: missing OPENAI_API_KEY)"})
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY)
        transcript = client.audio.transcriptions.create(
            model="gpt-4o-transcribe",  # or "whisper-1" if your account has access
            file=file
        )
        # transcript.text for gpt-4o-transcribe, or transcript["text"] for whisper-1
        text = getattr(transcript, "text", None) or getattr(transcript, "text", "")
        if not text:
            # older SDKs might return dict
            try:
                text = transcript["text"]
            except Exception:
                text = ""
        # Optional: parse into structured JSON using a small completion
        system = "You extract workout logs from text into JSON array of {exercise, reps}."
        user = f"Text: {text}"
        parsed = openai_complete_json(system, user)
        return jsonify({"text": text, "parsed": parsed})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port, debug=True)
