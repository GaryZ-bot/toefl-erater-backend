# backend1.py
import os
import sys
import json
import re
import logging
from flask import Flask, request, jsonify, send_from_directory, render_template
from flask_cors import CORS
from openai import OpenAI

# ---------------- UTF-8 & logging hardening ----------------
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

class SafeStreamHandler(logging.StreamHandler):
    """A logging handler that guarantees ASCII-safe output."""
    def emit(self, record):
        try:
            msg = self.format(record)
        except Exception:
            msg = record.getMessage()
        try:
            self.stream.write(msg + self.terminator)
        except UnicodeEncodeError:
            safe = msg.encode("ascii", "backslashreplace").decode("ascii")
            self.stream.write(safe + self.terminator)
        self.flush()

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

for h in list(logging.root.handlers):
    logging.root.removeHandler(h)

safe_handler = SafeStreamHandler(stream=sys.stderr)
safe_handler.setLevel(logging.INFO)
safe_handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
logging.root.addHandler(safe_handler)

werk = logging.getLogger("werkzeug")
werk.setLevel(logging.WARNING)
for h in list(werk.handlers):
    werk.removeHandler(h)

# ---------------- OpenAI client ----------------
api_key = os.environ.get("OPENAI_API_KEY")
if not api_key:
    logger.error("OPENAI_API_KEY environment variable not set")
    raise RuntimeError("Missing OPENAI_API_KEY")

client = OpenAI(api_key=api_key)

# ---------------- Flask app ----------------
app = Flask(__name__)
CORS(app, resources={r"/api/*": {"origins": ["https://toefl-erater-frontend.pages.dev"]}})

RUBRIC = (
    "You are a strict TOEFL Writing grader.\n"
    "Rate on 5 dimensions from 1-5: task_response, organization, language_use, development, mechanics.\n"
    "Compute overall_score (1-5) as the rounded average.\n"
    "Return ONLY a compact JSON object with keys:\n"
    "task_response, organization, language_use, development, mechanics, overall_score, concise_rationale.\n"
    "concise_rationale must be 1-2 sentences, actionable.\n"
    "Be consistent across essays of varying length; do not reward length alone.\n"
)

def ascii_safe_preview(s: str, limit: int = 120) -> str:
    s = s or ""
    preview = s[:limit] + ("..." if len(s) > limit else "")
    return preview.encode("ascii", "backslashreplace").decode("ascii")

@app.get("/")
def index():
    return send_from_directory(".", "index.html")

@app.post("/api/grade")
def grade():
    try:
        data = request.get_json(force=True, silent=True) or {}
        essay = (data.get("essay") or "").strip()
        if not essay:
            logger.info("Empty essay input")
            return jsonify({"error": "Essay text required"}), 400

        logger.info("Received essay length: %d; preview: %s", len(essay), ascii_safe_preview(essay))

        user_prompt = (
            'Essay:\n' +
            f'"""{essay}"""\n\n' +
            'Respond with ONLY JSON, no extra text.\n'
        )

        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": RUBRIC},
                {"role": "user",   "content": user_prompt},
            ],
        )

        text = (resp.choices[0].message.content or "").strip()
        logger.info("Model output received; preview: %s", ascii_safe_preview(text))

        try:
            result = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.S)
            if not match:
                logger.error("Model returned non-JSON; preview: %s", ascii_safe_preview(text))
                return jsonify({"error": "Model returned non-JSON response", "raw": text}), 502
            result = json.loads(match.group(0))

        required = {
            "task_response", "organization", "language_use",
            "development", "mechanics", "overall_score", "concise_rationale"
        }
        if not required.issubset(result.keys()):
            logger.error("Missing keys in model output: %s", list(result.keys()))
            return jsonify({"error": "Missing keys in model output", "raw": result}), 502

        return jsonify(result), 200

    except Exception as e:
        logger.exception("Unexpected error during grading: %s", ascii_safe_preview(str(e)))
        return jsonify({"error": str(e)}), 500

if __name__ == "__main__":
    logger.info("Starting server on http://0.0.0.0:8080")
    app.run(host="0.0.0.0", port=8080, debug=True)