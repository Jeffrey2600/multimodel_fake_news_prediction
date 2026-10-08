# TruthLens — Multimodal Fake News Detection

TruthLens checks whether news is real. Paste a forwarded message, drop a news link, upload a screenshot,
PDF or Word file, record your voice or upload a video — TruthLens pulls out every factual claim, searches news
sites, fact-checkers, official pages and Wikipedia for evidence, and gives a plain-language answer for each claim:

| Verdict | Meaning |
|---|---|
| ✓ **Checks out** | Reliable sources back this up |
| ◐ **Half true** | Part of it is right, part is wrong or missing context |
| ✕ **Fake** | Reliable sources show this isn't true |
| ? **Can't confirm** | Not enough reliable information yet to say either way |

Every report shows how sure the system is, the sources that back the claim and the ones that contradict it,
and "things to watch out for" — missing context, slanted language and details that were left out.

---

## Quick start

### 1. Install the prerequisites (once)

| Tool | Version | Download |
|---|---|---|
| Python | 3.10, 3.11 or 3.12 | https://www.python.org/downloads/ — on Windows tick **"Add python.exe to PATH"** |
| Node.js | 20 or newer | https://nodejs.org/ |
| Git | any | https://git-scm.com/downloads |

You also need a free **Google Gemini API key**: https://aistudio.google.com/apikey

### 2. Download and set up

```bash
git clone https://github.com/Jeffrey2600/multimodel_fake_news_prediction.git
cd multimodel_fake_news_prediction
```

**Windows:** double-click `setup.bat` (or run it in a terminal)
**macOS / Linux:** `chmod +x setup.sh run.sh && ./setup.sh`

Setup creates a Python environment, installs everything, builds the web app and creates `backend/.env`.
It takes 3–10 minutes the first time. About 1.5 GB of free disk space is needed.

### 3. Add your API key

Open `backend/.env` in any text editor and paste your key:

```
GEMINI_API_KEY=your-key-here
```

### 4. Run

**Windows:** double-click `run.bat`  **macOS / Linux:** `./run.sh`

Your browser opens at **http://localhost:8000**. Press `Ctrl+C` in the terminal to stop.

---

## What it can check

| Input | How it's read |
|---|---|
| **Text** — messages, headlines, whole articles | Split into separate claims |
| **News link** | Article, headline, publisher and date extracted from the page |
| **Image or file** — screenshots, posters, PDF, Word, text | Text read with OCR (scanned PDFs too) |
| **Voice** — record in the browser or upload MP3/WAV/M4A/OGG/WebM | Converted to text with speech recognition |
| **Video** — MP4/MOV/MKV/WebM | Speech transcribed, frames sampled for on-screen text |

Other features: claim-by-claim breakdown with a truth meter, supporting vs. contradicting sources with quotes,
source quality labels, context and bias analysis, check history (per browser, or across devices when signed in),
optional accounts, share links, PDF download (via print), dark / light mode, phone-friendly layout, and a
Methodology page explaining how verdicts are reached.

## How it works

```
input ─► read (OCR / speech-to-text / article extraction)
      ─► split into claims (Gemini)
      ─► gather evidence (web + news search, Wikipedia, NewsAPI, full-article passages)
      ─► judge each source: backs it / says it's wrong / background (Gemini)
      ─► verification engine: weights by source quality, relevance and independence, calibrates confidence
      ─► report
```

If the AI service is busy or out of quota, TruthLens automatically falls back through several Gemini models and,
as a last resort, a small offline model. Reports made by backup models carry a visible notice.

## Configuration (`backend/.env`)

| Setting | Required | What it does |
|---|---|---|
| `GEMINI_API_KEY` | yes | Google Gemini key used for claim splitting, judging evidence, OCR and speech-to-text |
| `NEWSAPI_KEY` | no | Adds NewsAPI (https://newsapi.org) articles as extra evidence |
| `PORT` | no | Port to run on (default 8000) |
| `MAX_UPLOAD_MB` | no | Largest file accepted (default 40) |
| `RATE_LIMIT_PER_MIN` | no | Checks allowed per minute per visitor (default 12) |
| `JWT_SECRET` | no | Login session secret; auto-generated if empty |

### About the free Gemini tier

The free tier allows only a limited number of requests **per model per day**, and doesn't include Google Search
grounding. TruthLens is built around this (it runs its own web search and rotates models), but busy use can exhaust
the daily allowance; the limit resets at midnight Pacific time. For regular or multi-user use, enable billing on the
Google AI Studio project — a check costs a fraction of a cent.

## Project structure

```
├── setup.bat / setup.sh        one-time install
├── run.bat / run.sh            start the app
├── backend/                    Python · FastAPI
│   ├── run.py                  entry point (serves API + web app on one port)
│   ├── .env.example            configuration template
│   ├── requirements.txt
│   ├── app/
│   │   ├── main.py             API routes, streaming progress, accounts, history
│   │   ├── preprocess.py       text, URL, OCR, documents, speech-to-text, video
│   │   ├── claims.py           claim extraction
│   │   ├── retrieval.py        evidence search and passage extraction
│   │   ├── analysis.py         evidence judging + verification engine
│   │   ├── credibility.py      source quality tiers
│   │   ├── llm.py              Gemini client with model fallback
│   │   ├── security.py         file validation, safe URL fetching, rate limiting
│   │   └── db.py               SQLite storage
│   ├── tests/test_api.py       functional tests
│   └── bench/                  accuracy benchmarks
└── frontend/                   React · TypeScript · Vite
    └── src/
        ├── pages/              Home, Report, History, Methodology, Account
        └── components/         input panel, progress, report view
```

Data (history, accounts) is stored in `backend/data/truthlens.db` (SQLite) and created automatically.
Uploaded files are processed in memory or a temporary folder and deleted straight away.

## Testing and accuracy

```bash
# Windows: backend\.venv\Scripts\python   macOS/Linux: backend/.venv/bin/python
cd backend
python tests/test_api.py                    # functional tests — no API quota used
python -m bench.run_bench curated            # 45 hand-labelled claims
python -m bench.run_bench averitec --n 60    # AVeriTeC real-world fact-checks (downloads the dataset)
python -m bench.url_bench                    # article extraction from live news links
python -m bench.stt_bench                    # speech-to-text word error rate
python -m bench.run_bench report             # print claim-verification metrics
```

Measured during development: **97.8 %** on the 45-claim hand-labelled set (100 % on clear true/false claims,
no true claim called fake or vice versa) and correct article extraction on roughly 80 % of news pages that allow
automated reading (paywalled sites ask the user to paste the text instead).

## Development mode

Run the backend and the web app separately with live reload:

```bash
cd backend && .venv/Scripts/python -m uvicorn app.main:app --reload --port 8000     # macOS/Linux: .venv/bin/python
cd frontend && npm run dev                                                          # http://localhost:5173
```

## Troubleshooting

| Problem | Fix |
|---|---|
| `setup.bat` says Python isn't found | Install Python 3.12 with "Add python.exe to PATH" ticked, open a new terminal |
| Reports say a "lighter backup model" was used | The daily Gemini quota is used up — try later or enable billing |
| "The site refused the request" for a link | The site blocks automated readers or has a paywall — paste the article text instead |
| Voice check says speech recognition is unavailable | The speech model is out of quota and the offline Whisper model couldn't download — check internet / disk space |
| Port 8000 already in use | Set `PORT=8010` in `backend/.env` |

## Tech stack

React 19 · TypeScript · Vite · FastAPI · Google Gemini · DuckDuckGo search · Trafilatura · PyMuPDF ·
RapidOCR · faster-whisper · ONNX Runtime (DeBERTa NLI) · SQLite
