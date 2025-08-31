import os
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from user_logic import run, run_file

load_dotenv()
ALLOWED = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "http://localhost:3000,https://preview--adapti-fit-voice.lovable.app/").split(",")]
PORT = int(os.getenv("PORT", "8000"))

app = Flask(__name__)
CORS(app)

# Basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("flaskify")

@app.get("/api/ping")
def ping():
    return {"status": "ok"}

@app.post("/api/run")
def api_run():
    try:
        payload = request.get_json(force=True, silent=False)
    except Exception:
        return jsonify({"error": "Invalid JSON"}), 400
    try:
        result = run(payload or {})
        return jsonify(result)
    except Exception as e:
        logger.exception("run() failed")
        return jsonify({"error": str(e)}), 500

@app.post("/api/run-file")
def api_run_file():
    file = request.files.get("file")
    try:
        result = run_file(file)
        return jsonify(result)
    except Exception as e:
        logger.exception("run_file() failed")
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=PORT, debug=True)
