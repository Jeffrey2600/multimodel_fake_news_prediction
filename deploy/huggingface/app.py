"""Hugging Face Space entry point.

Downloads the latest TruthLens code from GitHub on every start (so "Restart this Space"
deploys new commits) and serves the API plus the pre-built web app on port 7860.
The Gemini key comes from the Space secret GEMINI_API_KEY.
"""
import io
import os
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

try:  # free Gradio Spaces run on ZeroGPU, which requires one declared GPU function at start-up
    import spaces

    @spaces.GPU(duration=1)
    def _zerogpu_placeholder():
        """Never called: TruthLens does not use the GPU."""
        return None
except ImportError:  # running outside Hugging Face
    pass

REPO_ZIP = "https://github.com/Jeffrey2600/multimodel_fake_news_prediction/archive/refs/heads/main.zip"
WORK = Path("/tmp/truthlens")


def fetch_code() -> Path:
    shutil.rmtree(WORK, ignore_errors=True)
    WORK.mkdir(parents=True)
    data = urllib.request.urlopen(REPO_ZIP, timeout=120).read()
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        z.extractall(WORK)
    return next(p for p in WORK.iterdir() if p.is_dir())


root = fetch_code()
os.environ.setdefault("TRUTHLENS_DB", "/tmp/truthlens-data/truthlens.db")
os.environ.setdefault("HF_HOME", "/tmp/hf")
backend = root / "backend"
sys.path.insert(0, str(backend))
os.chdir(backend)

import uvicorn  # noqa: E402

print(f"TruthLens starting from {root}", flush=True)
uvicorn.run("app.main:app", host="0.0.0.0", port=int(os.getenv("PORT", 7860)),
            proxy_headers=True, forwarded_allow_ips="*")
