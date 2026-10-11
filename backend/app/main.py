import asyncio
import json
import os
import logging
import time
from pathlib import Path

import bcrypt
import jwt
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, Field

from . import config, db, llm, pipeline, preprocess
from .security import InputError, classify_upload, verify_limiter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
log = logging.getLogger("truthlens")
for _noisy in ("primp", "httpx", "httpcore", "ddgs", "trafilatura", "google_genai"):
    logging.getLogger(_noisy).setLevel(logging.WARNING)

app = FastAPI(title="TruthLens API", version="1.0")


@app.on_event("startup")
async def _thread_pool():
    # Searches, page parsing and OCR run in threads. Python's default pool scales with CPU count
    # (about 6 threads on a 2-CPU host), which made multi-claim checks queue for minutes.
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    asyncio.get_running_loop().set_default_executor(ThreadPoolExecutor(max_workers=48))
# The website may be hosted separately (e.g. on Netlify) and call this API directly.
_extra_origins = [o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173", *_extra_origins],
    allow_origin_regex=r"https://([a-z0-9-]+--)?[a-z0-9-]+\.netlify\.app",
    allow_methods=["*"],
    allow_headers=["*"],
)
db.init()


# ------------------------------------------------------------------ identity
def identity(authorization: str | None = Header(None), x_client_id: str | None = Header(None)):
    uid = None
    if authorization and authorization.lower().startswith("bearer "):
        try:
            uid = jwt.decode(authorization[7:], config.JWT_SECRET, algorithms=["HS256"])["uid"]
        except jwt.PyJWTError:
            raise HTTPException(401, "Your session expired. Sign in again.")
    cid = (x_client_id or "")[:64] or None
    return uid, cid


class Register(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)


class Login(BaseModel):
    email: EmailStr
    password: str


def _token(uid: int) -> str:
    return jwt.encode({"uid": uid, "exp": int(time.time()) + 30 * 86400}, config.JWT_SECRET, algorithm="HS256")


@app.post("/api/auth/register")
def register(body: Register, who=Depends(identity)):
    if db.user_by_email(body.email):
        raise HTTPException(409, "An account with that email already exists. Sign in instead.")
    pw = bcrypt.hashpw(body.password.encode(), bcrypt.gensalt()).decode()
    uid = db.create_user(body.name.strip(), body.email, pw)
    if who[1]:
        db.adopt(who[1], uid)
    return {"token": _token(uid), "user": db.user_by_id(uid)}


@app.post("/api/auth/login")
def login(body: Login, who=Depends(identity)):
    u = db.user_by_email(body.email)
    if not u or not bcrypt.checkpw(body.password.encode(), u["password"].encode()):
        raise HTTPException(401, "Email or password is incorrect.")
    if who[1]:
        db.adopt(who[1], u["user_id"])
    return {"token": _token(u["user_id"]), "user": db.user_by_id(u["user_id"])}


@app.get("/api/auth/me")
def me(who=Depends(identity)):
    if not who[0]:
        raise HTTPException(401, "Not signed in.")
    return db.user_by_id(who[0])


# ------------------------------------------------------------------ status
@app.get("/api/status")
async def status():
    models = []
    if llm.enabled():
        try:
            models = await llm._chain(False)
        except Exception:
            models = []
    return {"grounding": bool(models), "models": models, "newsapi": bool(config.NEWSAPI_KEY),
            "whisper": config.WHISPER_MODEL, "nli": config.NLI_MODEL}


# ------------------------------------------------------------------ verify
MAX_CHECK_SECONDS = 330
@app.post("/api/verify", dependencies=[Depends(verify_limiter)])
async def verify(
    kind: str = Form(...),
    text: str | None = Form(None),
    url: str | None = Form(None),
    file: UploadFile | None = File(None),
    who=Depends(identity),
):
    """Streams newline-delimited JSON progress events, ending with the report (or an error)."""
    data, fname, mime, ftype = b"", "", "", ""
    try:
        if kind == "text":
            label = (text or "").strip()
        elif kind == "url":
            label = (url or "").strip()
        elif kind == "file":
            if not file:
                raise InputError("Choose a file to upload.")
            data = await file.read(config.MAX_UPLOAD_MB * 1024 * 1024 + 1)
            fname = Path(file.filename or "upload").name
            ftype, mime = classify_upload(fname, data[:16], len(data))
            label = fname
        else:
            raise InputError("Unknown input type.")
        if not label:
            raise InputError("Nothing to check yet — add a claim, link or file.")
    except InputError as e:
        raise HTTPException(400, str(e))

    uid, cid = who
    vid = db.create_verification(ftype or kind, label, uid, cid)

    async def work(out: asyncio.Queue):
        """Runs the check and puts each progress event on the queue (None marks the end)."""
        try:
            await out.put(pipeline.ev("read", "active", {
                "text": "Reading your text", "url": "Fetching the article",
                "image": "Reading text from the image (OCR)", "document": "Extracting the document text",
                "audio": "Transcribing the recording", "video": "Transcribing audio and sampling frames",
            }[ftype or kind]))
            if kind == "text":
                prep = preprocess.prepare_text(text)
            elif kind == "url":
                prep = await preprocess.prepare_url(url)
            elif ftype == "image":
                prep = await preprocess.prepare_image(data, mime, fname)
            elif ftype == "document":
                prep = await preprocess.prepare_document(data, mime, fname)
            elif ftype == "audio":
                prep = await preprocess.prepare_audio(data, fname)
            else:
                prep = await preprocess.prepare_video(data, fname, mime)
            # uploaded media lives only in memory / a temp dir that is deleted after extraction
            async for event in pipeline.run(prep):
                if event["type"] == "report":
                    rep = event["report"]
                    rep["id"] = vid
                    rep["created_at"] = db.now()
                    rep["input"]["label"] = label
                    db.save_report(vid, rep)
                await out.put(event)
        except InputError as e:
            db.fail_verification(vid)
            await out.put({"type": "error", "message": str(e)})
        except Exception as e:
            log.exception("verification %s failed", vid)
            db.fail_verification(vid)
            await out.put({"type": "error", "message": f"The check stopped unexpectedly ({type(e).__name__}). Try again in a minute."})
        finally:
            await out.put(None)

    async def stream():
        def line(o):
            return json.dumps(o) + "\n"

        yield line({"type": "start", "id": vid})
        out: asyncio.Queue = asyncio.Queue()
        task = asyncio.create_task(work(out))
        deadline = asyncio.get_running_loop().time() + MAX_CHECK_SECONDS
        try:
            while True:
                try:
                    event = await asyncio.wait_for(out.get(), 15)
                except asyncio.TimeoutError:
                    if asyncio.get_running_loop().time() > deadline:
                        task.cancel()
                        db.fail_verification(vid)
                        yield line({"type": "error", "message": "This check took too long — the AI service is very busy "
                                                                "right now. Please try again in a minute."})
                        return
                    # keep-alive: hosting proxies close connections that stay silent too long
                    yield line({"type": "ping"})
                    continue
                if event is None:
                    return
                yield line(event)
        finally:
            if not task.done():
                task.cancel()

    return StreamingResponse(stream(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ history
def _report(row):
    if not row or not row.get("report_json"):
        raise HTTPException(404, "That verification doesn't exist or was deleted.")
    return json.loads(row["report_json"]) | {"share_id": row.get("share_id")}


@app.get("/api/history")
def get_history(who=Depends(identity)):
    return db.history(*who)


@app.delete("/api/history")
def clear_history(who=Depends(identity)):
    return {"deleted": db.clear(*who)}


@app.get("/api/verifications/{vid}")
def get_verification(vid: str, who=Depends(identity)):
    return _report(db.get(vid, *who))


@app.delete("/api/verifications/{vid}")
def delete_verification(vid: str, who=Depends(identity)):
    if not db.delete(vid, *who):
        raise HTTPException(404, "That verification doesn't exist.")
    return {"ok": True}


@app.post("/api/verifications/{vid}/share")
def share_verification(vid: str, who=Depends(identity)):
    sid = db.share(vid, *who)
    if not sid:
        raise HTTPException(404, "Only completed checks can be shared.")
    return {"share_id": sid}


@app.get("/api/shared/{share_id}")
def shared(share_id: str):
    return _report(db.get_shared(share_id))


# ------------------------------------------------------------------ serve built frontend
_dist = (config.BASE_DIR.parent / "frontend" / "dist").resolve()
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}")
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404, "Not found.")
        f = (_dist / path).resolve()
        # only files inside the built web app may be served (blocks ../ traversal)
        if path and f.is_file() and f.is_relative_to(_dist):
            return FileResponse(f)
        return FileResponse(_dist / "index.html")
