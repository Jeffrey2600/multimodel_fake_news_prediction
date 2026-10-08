"""Claim extraction: splits content into atomic, independently checkable claims."""
import datetime as dt
import re

from . import config, llm

SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string"},
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "text": {"type": "string"},
                    "people": {"type": "array", "items": {"type": "string"}},
                    "organizations": {"type": "array", "items": {"type": "string"}},
                    "locations": {"type": "array", "items": {"type": "string"}},
                    "dates": {"type": "array", "items": {"type": "string"}},
                    "numbers": {"type": "array", "items": {"type": "string"}},
                    "keywords": {"type": "array", "items": {"type": "string"}},
                    "search_query": {"type": "string"},
                    "central": {"type": "boolean"},
                },
                "required": ["text", "search_query", "central"],
            },
        },
    },
    "required": ["summary", "claims"],
}

PROMPT = """You are the claim-extraction stage of a fact-checking system. Today is {today}.

Read the CONTENT and list the factual claims that can be checked against evidence.
Rules:
- Each claim must be atomic (one fact), self-contained (resolve pronouns, keep names, dates, numbers and places
  exactly as stated) and phrased as a declarative sentence. Never correct or soften the claim.
- If the content is a single claim, return exactly that claim, lightly normalised (fix typos only).
- Skip opinions, predictions without a factual basis, greetings and questions — unless the question embeds a claim.
- Merge near-duplicates. Return at most {max_claims}, most important first. Mark the claim(s) the content is
  mainly about as central=true.
- search_query: a concise web search query (keywords, not a sentence) that would find evidence for or against.
- summary: one sentence describing what the content asserts.
{source_hint}
CONTENT:
\"\"\"{content}\"\"\""""


def _today():
    return dt.date.today().strftime("%A, %d %B %Y")


async def extract(text: str, source_hint: str = "") -> tuple[dict, str]:
    """Returns ({summary, claims[]}, engine)."""
    if _is_single_claim(text):
        # one short statement: it already is the claim, so save a model call
        d = local_extract(text)
        d["claims"] = d["claims"][:1]
        d["claims"][0]["text"] = text.strip()
        return d, "direct (single statement)"
    if llm.enabled():
        try:
            data, model = await llm.generate_json(
                PROMPT.format(today=_today(), content=text[:12000], max_claims=config.MAX_CLAIMS,
                              source_hint=("Context: " + source_hint) if source_hint else ""),
                schema=SCHEMA, light=True,
            )
            claims = [c for c in data.get("claims", []) if c.get("text", "").strip()][: config.MAX_CLAIMS]
            if claims:
                if not any(c.get("central") for c in claims):
                    claims[0]["central"] = True
                return {"summary": data.get("summary", ""), "claims": claims}, model
        except llm.LLMUnavailable:
            pass
    return local_extract(text), "local heuristics"


def _is_single_claim(text: str) -> bool:
    t = text.strip()
    return "\n" not in t and len(t.split()) <= 40 and len(_SENT.split(t)) == 1


# ------------------------------------------------------------- local fallback
_SENT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'])")
_CAPS = re.compile(r"\b(?:[A-Z][a-z]+(?:\s+[A-Z][a-z]+)*|[A-Z]{2,})\b")
_NUM = re.compile(r"\b\d[\d,.]*\s*(?:%|percent|crore|lakh|million|billion|thousand)?")
_DATE = re.compile(r"\b(?:\d{1,2}\s+)?(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?(?:\s+\d{1,2})?,?\s*\d{4}\b|\b(?:19|20)\d{2}\b")
_STOP = set("the a an of to in on for and or is are was were be been by with from at as that this it its has have had will would can could".split())


def local_extract(text: str) -> dict:
    sents = [s.strip() for s in _SENT.split(text.replace("\n", " ")) if len(s.split()) >= 4]
    if not sents:
        sents = [text.strip()]
    scored = sorted(sents, key=lambda s: len(_CAPS.findall(s)) + 2 * len(_NUM.findall(s)), reverse=True)
    picked = [s for s in sents if s in scored[: config.MAX_CLAIMS]]
    claims = []
    for i, s in enumerate(picked):
        ents = [e for e in _CAPS.findall(s) if e.lower() not in _STOP][:6]
        words = [w.rstrip(".,'") for w in re.findall(r"[A-Za-z0-9][A-Za-z0-9,.'%-]*", s)]
        words = [w for w in words if w and w.lower() not in _STOP]
        claims.append({
            "text": s[:400],
            "people": [], "organizations": [], "locations": [], "names": ents,
            "dates": _DATE.findall(s), "numbers": [n.strip() for n in _NUM.findall(s)],
            "keywords": words[:8],
            "search_query": " ".join(words[:12]),
            "central": i == 0,
        })
    return {"summary": sents[0][:300], "claims": claims}
