"""Start TruthLens: serves the API and the built web app on one port, then opens the browser.

    python run.py            (port from .env PORT, default 8000)
    python run.py --no-browser
"""
import os
import sys
import threading
import webbrowser
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
load_dotenv(HERE / ".env")


def main():
    port = int(os.getenv("PORT") or 8000)
    host = os.getenv("HOST") or "127.0.0.1"
    url = f"http://localhost:{port}"

    if not (HERE.parent / "frontend" / "dist" / "index.html").exists():
        print("! The web app hasn't been built yet. Run setup first (setup.bat on Windows, ./setup.sh on Mac/Linux).")
    if not os.getenv("GEMINI_API_KEY"):
        print("! GEMINI_API_KEY is empty in backend/.env — checks will run on the much weaker offline engine.")

    print(f"\n  TruthLens is starting on {url}\n  Press Ctrl+C to stop.\n")
    if "--no-browser" not in sys.argv:
        threading.Timer(2.0, lambda: webbrowser.open(url)).start()
    uvicorn.run("app.main:app", host=host, port=port, app_dir=str(HERE), log_level="info")


if __name__ == "__main__":
    main()
