"""Turns every input type into plain text (plus metadata) for claim extraction."""
import asyncio
import io
import logging
import os
import re
import subprocess
import tempfile
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urljoin

import httpx

from . import config, llm
from .credibility import domain_of
from .security import InputError, validate_public_url

log = logging.getLogger("truthlens.preprocess")

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"


@dataclass
class Prepared:
    kind: str                      # text | url | image | document | audio | video
    text: str                      # the content that will be fact-checked
    meta: dict = field(default_factory=dict)
    notes: list = field(default_factory=list)  # human-readable processing notes


def clean_text(s: str) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    s = s.replace("​", "").replace("﻿", "")
    s = re.sub(r"[ \t]+", " ", s)
    s = re.sub(r"\n{3,}", "\n\n", s)
    return s.strip()[: config.MAX_TEXT_CHARS]


# ---------------------------------------------------------------- text
def prepare_text(text: str) -> Prepared:
    t = clean_text(text)
    if len(t) < 8 or not re.search(r"[A-Za-zऀ-෿]{3,}", t):
        raise InputError("Enter a claim or article with at least a few words.")
    return Prepared("text", t)


# ---------------------------------------------------------------- url
def _browser_fetch(url: str, max_redirects=5) -> tuple[int, str, str, str]:
    """Fetch with a real-browser TLS/HTTP fingerprint, for sites that turn away plain HTTP clients."""
    import primp

    status, last = 0, None
    for imp, os_ in (("safari", "macos"), ("chrome", "windows"), ("firefox", "windows")):
        c = primp.Client(impersonate=imp, impersonate_os=os_, follow_redirects=False, timeout=20)
        u = url
        for _ in range(max_redirects + 1):
            validate_public_url(u)
            r = c.get(u)
            if 300 <= r.status_code < 400 and r.headers.get("location"):
                u = urljoin(u, r.headers["location"])
                continue
            break
        last = (r.status_code, r.headers.get("content-type", ""), r.text, u)
        if r.status_code < 400:
            return last
    return last


async def fetch_html(url: str, max_redirects=5) -> tuple[str, str]:
    status, ctype, text, final = 0, "", "", url
    try:
        async with httpx.AsyncClient(timeout=20, headers={"User-Agent": UA, "Accept-Language": "en"}) as c:
            for _ in range(max_redirects + 1):
                validate_public_url(final)
                r = await c.get(final, follow_redirects=False)
                if r.is_redirect:
                    final = urljoin(final, r.headers.get("location", ""))
                    continue
                status, ctype, text, final = r.status_code, r.headers.get("content-type", ""), r.text, str(r.url)
                break
            else:
                raise InputError("That link redirects too many times.")
    except httpx.HTTPError as e:
        log.info("plain fetch failed (%s), trying browser fetch", e)
    if status in (0, 401, 403, 429, 503):
        try:
            status, ctype, text, final = await asyncio.to_thread(_browser_fetch, url)
        except InputError:
            raise
        except Exception as e:
            log.info("browser fetch failed: %s", e)
    if status == 0:
        raise InputError("Couldn't load that page. Check the link, or paste the article text instead.")
    if status >= 400:
        raise InputError(f"The site refused the request ({status}) — it may need a login. Paste the article text instead.")
    if "html" not in ctype and "text" not in ctype:
        raise InputError("That link doesn't point to a web page.")
    return text[:3_000_000], final


def extract_article(html: str, url: str) -> dict:
    import trafilatura

    data = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False, favor_precision=True)
    d = {} if data is None else (data if isinstance(data, dict) else data.as_dict())
    if len(d.get("text") or "") < 400:  # precision mode can drop the body on unusual layouts
        data = trafilatura.bare_extraction(html, url=url, with_metadata=True, include_comments=False, favor_recall=True)
        if data is not None:
            d2 = data if isinstance(data, dict) else data.as_dict()
            if len(d2.get("text") or "") > len(d.get("text") or ""):
                d = d2
    if not d:
        return {}
    return {
        "title": d.get("title") or "",
        "text": d.get("text") or "",
        "publisher": d.get("sitename") or domain_of(url),
        "author": d.get("author") or "",
        "date": d.get("date") or "",
        "url": url,
    }


async def prepare_url(url: str) -> Prepared:
    url = validate_public_url(url)
    html, final = await fetch_html(url)
    art = extract_article(html, final)
    body = clean_text(art.get("text", ""))
    if len(body) < 120:
        raise InputError("Couldn't find article text on that page. It may need a login or JavaScript — paste the text instead.")
    head = f"{art['title']}\n\n" if art.get("title") else ""
    return Prepared("url", clean_text(head + body), meta=art)


# ---------------------------------------------------------------- images
_OCR_PROMPT = (
    "Transcribe every piece of readable text in this image exactly as written (headlines, captions, "
    "tweets, overlays), preserving reading order. Then, on a new line starting with 'VISUAL:', describe in "
    "one or two sentences what the image shows (people, logos, publication masthead, dates visible). "
    "Do not judge whether anything is true."
)

_rapid = None


def _rapidocr(data: bytes) -> str:
    global _rapid
    from rapidocr_onnxruntime import RapidOCR

    if _rapid is None:
        _rapid = RapidOCR()
    result, _ = _rapid(data)
    return "\n".join(r[1] for r in (result or []))


async def ocr_image(data: bytes, mime: str) -> tuple[str, str, str]:
    """Returns (text, visual description, engine)."""
    if llm.enabled():
        try:
            part = await llm.upload_bytes(data, mime)
            out, model = await llm.generate_text(_OCR_PROMPT, parts=[part], light=True)
            text, _, visual = out.partition("VISUAL:")
            return clean_text(text), visual.strip(), f"Gemini vision ({model})"
        except llm.LLMUnavailable as e:
            log.warning("vision OCR fallback: %s", e)
    text = await asyncio.to_thread(_rapidocr, data)
    return clean_text(text), "", "RapidOCR (local)"


async def prepare_image(data: bytes, mime: str, filename: str) -> Prepared:
    text, visual, engine = await ocr_image(data, mime)
    if len(text) < 8:
        raise InputError("No readable text was found in that image. Try a sharper screenshot.")
    p = Prepared("image", text, meta={"filename": filename, "visual": visual, "ocr_engine": engine})
    p.notes.append(f"Text read with {engine}.")
    return p


# ---------------------------------------------------------------- documents
async def prepare_document(data: bytes, mime: str, filename: str) -> Prepared:
    notes = []
    if mime == "application/pdf":
        import pymupdf

        doc = pymupdf.open(stream=data, filetype="pdf")
        pages = [p.get_text() for p in doc][:30]
        text = clean_text("\n".join(pages))
        if len(text) < 80:  # scanned PDF -> OCR rendered pages
            chunks = []
            for page in list(doc)[:6]:
                png = page.get_pixmap(dpi=150).tobytes("png")
                t, _, engine = await ocr_image(png, "image/png")
                chunks.append(t)
            text = clean_text("\n".join(chunks))
            notes.append(f"Scanned PDF — {min(len(doc), 6)} page(s) read with OCR ({engine}).")
        else:
            notes.append(f"Extracted text from {len(pages)} PDF page(s).")
    elif mime.endswith("wordprocessingml.document"):
        import docx

        d = docx.Document(io.BytesIO(data))
        text = clean_text("\n".join(p.text for p in d.paragraphs))
        notes.append("Extracted text from Word document.")
    else:
        text = clean_text(data.decode("utf-8", errors="replace"))
    if len(text) < 8:
        raise InputError("That document has no readable text.")
    return Prepared("document", text, meta={"filename": filename}, notes=notes)


# ---------------------------------------------------------------- audio / video
_whisper = None


def _ffmpeg() -> str:
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return "ffmpeg"


def _load_whisper():
    global _whisper
    if _whisper is None:
        from faster_whisper import WhisperModel

        try:
            import torch  # torch wheels ship the cuBLAS/cuDNN DLLs ctranslate2 needs

            if torch.cuda.is_available():
                lib = Path(torch.__file__).parent / "lib"
                if hasattr(os, "add_dll_directory"):
                    os.add_dll_directory(str(lib))
                os.environ["PATH"] = str(lib) + os.pathsep + os.environ.get("PATH", "")
                _whisper = WhisperModel(config.WHISPER_MODEL, device="cuda", compute_type="int8_float16")
                return _whisper
        except Exception as e:
            log.warning("whisper on GPU unavailable (%s); using CPU", e)
        _whisper = WhisperModel(config.WHISPER_MODEL, device="cpu", compute_type="int8")
    return _whisper


def _whisper_transcribe(path: str) -> tuple[str, str]:
    model = _load_whisper()
    segments, info = model.transcribe(path, beam_size=5, vad_filter=True)
    text = " ".join(s.text.strip() for s in segments)
    return clean_text(text), info.language


_STT_PROMPT = (
    "Transcribe the speech in this recording verbatim, in the language spoken. Output only the transcript text — "
    "no timestamps, speaker labels or commentary. If there is no speech, output nothing."
)


def _to_wav16k(path: str, out: str) -> bool:
    r = subprocess.run([_ffmpeg(), "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", out], capture_output=True)
    return r.returncode == 0 and Path(out).exists() and Path(out).stat().st_size > 1000


async def transcribe(path: str) -> tuple[str, str]:
    """Speech-to-text. Returns (transcript, engine). Gemini's transcription model first, local Whisper as fallback."""
    wav = str(Path(path).with_name("speech16k.wav"))
    src = wav if await asyncio.to_thread(_to_wav16k, path, wav) else path
    if llm.enabled():
        from .security import ALLOWED_FILES

        mime = ALLOWED_FILES.get(Path(src).suffix.lower(), ("", "audio/wav"))[1]
        part = await llm.upload_bytes(Path(src).read_bytes(), mime)
        # the dedicated transcription model first, then full flash models; never the lite
        # models, which have invented transcripts when the audio was hard
        for m in [config.GEMINI_TRANSCRIBE_MODEL] + [x for x in config.GEMINI_MODELS if "lite" not in x]:
            try:
                text, model = await llm.generate_text(_STT_PROMPT, parts=[part], model=m, only=True)
            except llm.LLMUnavailable as e:
                log.info("transcription with %s unavailable: %s", m, str(e)[:120])
                continue
            text = clean_text(text)
            if text:
                return text, f"Gemini speech-to-text ({model})"
        log.warning("no cloud transcription available; trying local Whisper")
    try:
        text, lang = await asyncio.to_thread(_whisper_transcribe, src)
        return text, f"Whisper {config.WHISPER_MODEL} (local), language: {lang}"
    except Exception as e:
        log.exception("whisper failed")
        raise InputError("Speech recognition is unavailable right now. Try again shortly, or type the claim.") from e


async def prepare_audio(data: bytes, filename: str) -> Prepared:
    suffix = Path(filename).suffix or ".wav"
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        src.write_bytes(data)
        text, engine = await transcribe(str(src))
    if len(text) < 8:
        raise InputError("No speech was detected in that recording.")
    return Prepared("audio", text, meta={"filename": filename}, notes=[f"Transcribed with {engine}."])


async def prepare_video(data: bytes, filename: str, mime: str) -> Prepared:
    suffix = Path(filename).suffix or ".mp4"
    ff = _ffmpeg()
    notes = []
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / f"in{suffix}"
        src.write_bytes(data)
        wav = Path(tmp) / "audio.wav"
        r = subprocess.run([ff, "-y", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(wav)],
                           capture_output=True)
        transcript = ""
        if r.returncode == 0 and wav.exists() and wav.stat().st_size > 2000:
            transcript, engine = await transcribe(str(wav))
            notes.append(f"Speech transcribed with {engine}.")

        # sample frames: one every few seconds, max 6
        frames_dir = Path(tmp) / "frames"
        frames_dir.mkdir()
        subprocess.run([ff, "-y", "-i", str(src), "-vf", "fps=1/4,scale=960:-1", "-frames:v", "6",
                        str(frames_dir / "f%02d.jpg")], capture_output=True)
        frames = sorted(frames_dir.glob("*.jpg"))
        on_screen, visuals = [], []
        for f in frames:
            t, v, _ = await ocr_image(f.read_bytes(), "image/jpeg")
            if t and t not in on_screen:
                on_screen.append(t)
            if v:
                visuals.append(v)
        if frames:
            notes.append(f"Analysed {len(frames)} sampled frame(s) for on-screen text.")
    parts = []
    if transcript:
        parts.append(transcript)
    if on_screen:
        parts.append("On-screen text: " + " | ".join(on_screen))
    text = clean_text("\n\n".join(parts))
    if len(text) < 8:
        raise InputError("No speech or on-screen text could be extracted from that video.")
    return Prepared("video", text, meta={"filename": filename, "visual": " ".join(visuals[:3])}, notes=notes)
