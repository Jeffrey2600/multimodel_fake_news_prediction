"""Gemini access with an ordered model fallback chain.

Every call walks the configured models in order. Rate-limit / overload errors
(429, 500, 503) move on to the next model; when the chain is exhausted the
caller gets LLMUnavailable and the pipeline switches to the local engine.
"""
import asyncio
import json
import logging
import re
from dataclasses import dataclass, field

from google import genai
from google.genai import types

from . import config

log = logging.getLogger("truthlens.llm")


class LLMUnavailable(RuntimeError):
    pass


@dataclass
class GroundedAnswer:
    text: str
    sources: list = field(default_factory=list)  # [{"title", "url"}]
    queries: list = field(default_factory=list)
    model: str = ""


_client = None
_available: set | None = None
_cooldown: dict[str, float] = {}
_grounding_until = 0.0


def grounding_available() -> bool:
    try:
        return _grounding_until <= asyncio.get_running_loop().time()
    except RuntimeError:
        return True


def enabled() -> bool:
    return bool(config.GEMINI_API_KEY)


def client() -> genai.Client:
    global _client
    if _client is None:
        if not enabled():
            raise LLMUnavailable("GEMINI_API_KEY is not set")
        _client = genai.Client(api_key=config.GEMINI_API_KEY)
    return _client


async def _available_models() -> set:
    global _available
    if _available is None:
        try:
            names = set()
            async for m in await client().aio.models.list():
                names.add(m.name.split("/")[-1])
            _available = names
        except Exception as e:  # listing failed: trust the configured names
            log.warning("model listing failed: %s", e)
            _available = set(config.GEMINI_MODELS + config.GEMINI_LIGHT_MODELS)
    return _available


async def _chain(light: bool) -> list[str]:
    avail = await _available_models()
    wanted = config.GEMINI_LIGHT_MODELS if light else config.GEMINI_MODELS
    chain = [m for m in wanted if m in avail]
    if not light:
        return chain
    # light chain may still fall back onto the main chain
    return chain + [m for m in await _chain(False) if m not in chain]


def _retryable(e: Exception) -> bool:
    s = str(e)
    return any(c in s for c in ("429", "500", "503", "RESOURCE_EXHAUSTED", "UNAVAILABLE", "overloaded", "DEADLINE"))


async def _generate(contents, cfg: types.GenerateContentConfig, light=False, timeout=60, prefer=None, only=False):
    loop = asyncio.get_running_loop()
    last = None
    chain = await _chain(light)
    if prefer and prefer in await _available_models():
        chain = [prefer] if only else [prefer] + [m for m in chain if m != prefer]
    for model in chain:
        if _cooldown.get(model, 0) > loop.time():
            continue
        for attempt in range(2):
            try:
                resp = await asyncio.wait_for(
                    client().aio.models.generate_content(model=model, contents=contents, config=cfg),
                    timeout=timeout,
                )
                return resp, model
            except Exception as e:
                last = e
                log.warning("gemini %s failed (attempt %d): %s", model, attempt + 1, str(e)[:200])
                if not _retryable(e) and not isinstance(e, asyncio.TimeoutError):
                    break
                if "503" in str(e) or "UNAVAILABLE" in str(e):
                    # overloaded: skip straight to the next model and rest this one briefly
                    _cooldown[model] = loop.time() + 90
                    break
                if "PerDay" in str(e):
                    # free-tier daily cap for this model: don't touch it again for hours
                    _cooldown[model] = loop.time() + 6 * 3600
                    log.warning("%s hit its daily quota; skipping it", model)
                    break
                if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                    m = re.search(r"retry in ([\d.]+)s", str(e))
                    wait = float(m.group(1)) if m else 20
                    if wait > 25 or attempt == 1:
                        _cooldown[model] = loop.time() + min(wait, 120)
                        break
                    await asyncio.sleep(wait + 1)
                else:
                    await asyncio.sleep(2 + attempt * 3)
    raise LLMUnavailable(f"all Gemini models failed: {last}")


def _parse_json(text: str):
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"[\[{].*[\]}]", text, re.S)
        if m:
            return json.loads(m.group(0))
        raise


async def generate_json(prompt, schema: dict | None = None, light=False, temperature=0.0, parts=None):
    cfg = types.GenerateContentConfig(
        temperature=temperature,
        response_mime_type="application/json",
        response_schema=schema,
    )
    contents = parts + [prompt] if parts else prompt
    resp, model = await _generate(contents, cfg, light=light)
    return _parse_json(resp.text or "{}"), model


async def generate_text(prompt, parts=None, light=False, temperature=0.0, timeout=90, model=None, only=False):
    cfg = types.GenerateContentConfig(temperature=temperature)
    contents = parts + [prompt] if parts else prompt
    resp, model = await _generate(contents, cfg, light=light, timeout=timeout, prefer=model, only=only)
    # transcription models return the transcript as an audio_transcription part, not as text
    pieces = []
    for cand in resp.candidates or []:
        for part in (cand.content.parts if cand.content else None) or []:
            if getattr(part, "text", None):
                pieces.append(part.text)
            at = getattr(part, "audio_transcription", None)
            if at is not None and getattr(at, "text", None):
                pieces.append(at.text)
    if pieces:
        return " ".join(p.strip() for p in pieces if p.strip()), model
    return resp.text or "", model


async def grounded_search(prompt: str) -> GroundedAnswer:
    """Ask Gemini with Google Search grounding; returns the answer plus cited web sources."""
    global _grounding_until
    loop = asyncio.get_running_loop()
    if _grounding_until > loop.time():
        raise LLMUnavailable("Google Search grounding quota exhausted")
    cfg = types.GenerateContentConfig(
        temperature=0.0,
        tools=[types.Tool(google_search=types.GoogleSearch())],
    )
    # Grounding has its own (often zero) free-tier quota, so failures here must not
    # put the models themselves on cooldown for ordinary calls.
    resp, model, last = None, "", None
    for m in (await _chain(False))[:2]:
        try:
            resp = await asyncio.wait_for(client().aio.models.generate_content(model=m, contents=prompt, config=cfg), 90)
            model = m
            break
        except Exception as e:
            last = e
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                _grounding_until = loop.time() + 1800
                log.warning("grounding quota exhausted; using own web retrieval for 30 min")
                break
    if resp is None:
        raise LLMUnavailable(f"grounding failed: {last}")
    out = GroundedAnswer(text=resp.text or "", model=model)
    try:
        gm = resp.candidates[0].grounding_metadata
        if gm:
            out.queries = list(gm.web_search_queries or [])
            for ch in gm.grounding_chunks or []:
                web = getattr(ch, "web", None)
                out.sources.append({"title": (web.title if web else "") or "", "url": (web.uri if web else "") or "",
                                    "snippets": []})
            # attach the sentences of the answer that each source backs
            for sup in gm.grounding_supports or []:
                seg = (sup.segment.text if sup.segment else "") or ""
                for idx in sup.grounding_chunk_indices or []:
                    if 0 <= idx < len(out.sources) and seg and seg not in out.sources[idx]["snippets"]:
                        out.sources[idx]["snippets"].append(seg)
            out.sources = [s for s in out.sources if s["url"]]
    except (IndexError, AttributeError):
        pass
    return out


async def upload_bytes(data: bytes, mime: str):
    return types.Part.from_bytes(data=data, mime_type=mime)
