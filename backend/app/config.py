import os
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / ".env")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
NEWSAPI_KEY = os.getenv("NEWSAPI_KEY", "").strip()

# Tried in order; anything the key can't see is skipped at startup.
GEMINI_MODELS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_MODELS",
        "gemini-3.8-flash,gemini-3.7-flash,gemini-3.6-flash,gemini-3.5-flash,gemini-flash-latest,gemini-3-flash-preview,"
        "gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3.1-flash-lite",
    ).split(",")
    if m.strip()
]
# Cheap model for bookkeeping work (claim splitting).
GEMINI_LIGHT_MODELS = [
    m.strip()
    for m in os.getenv(
        "GEMINI_LIGHT_MODELS", "gemini-3.5-flash-lite,gemini-flash-lite-latest,gemini-3.1-flash-lite"
    ).split(",")
    if m.strip()
]

DB_PATH = Path(os.getenv("TRUTHLENS_DB", BASE_DIR / "data" / "truthlens.db"))
UPLOAD_DIR = BASE_DIR / "data" / "uploads"
JWT_SECRET = os.getenv("JWT_SECRET", "")

MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "40"))
MAX_TEXT_CHARS = 20000
MAX_CLAIMS = 5
RATE_LIMIT_PER_MIN = int(os.getenv("RATE_LIMIT_PER_MIN", "12"))

WHISPER_MODEL = os.getenv("WHISPER_MODEL", "base")
GEMINI_TRANSCRIBE_MODEL = os.getenv("GEMINI_TRANSCRIBE_MODEL", "gemini-3.5-transcribe")
# Offline fallback NLI model (ONNX). With ~250 MB spare, "Xenova/DeBERTa-v3-base-mnli-fever-anli" is stronger.
NLI_MODEL = os.getenv("NLI_MODEL", "Xenova/nli-deberta-v3-xsmall")
NLI_ONNX_FILE = os.getenv("NLI_ONNX_FILE", "onnx/model_int8.onnx")

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

if not JWT_SECRET:  # generate once and keep it, so sign-ins survive restarts
    _secret_file = DB_PATH.parent / ".jwt_secret"
    if not _secret_file.exists():
        import secrets

        _secret_file.write_text(secrets.token_urlsafe(48))
    JWT_SECRET = _secret_file.read_text().strip()
