"""Evidence retrieval: Google-grounded Gemini research + keyless web/news search + Wikipedia (+ NewsAPI)."""
import asyncio
import datetime as dt
import logging
import re
from urllib.parse import quote

import httpx

from . import config, llm
from .credibility import TIERS as TIER_WEIGHT, domain_of, publisher_name, tier_of

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0 Safari/537.36"

log = logging.getLogger("truthlens.retrieval")

RESEARCH_PROMPT = """Today is {today}. You are a research assistant for a professional fact-checker.
Use Google Search to find the most authoritative, up-to-date reporting on this claim:

CLAIM: "{claim}"

Search for it directly AND for the underlying facts (exact figures, dates, names, official statements,
fact-checks or debunks). Then write a neutral evidence brief:
- What reliable sources actually report, with specific facts, figures and dates.
- Any fact-check articles about this claim or close variants.
- Where sources disagree, or where the claim mixes true and false details (wrong date, number, person, place).
Write only what the sources say. If nothing relevant is found, say so plainly."""


async def _resolve_redirect(c: httpx.AsyncClient, url: str) -> str:
    if "grounding-api-redirect" not in url:
        return url
    try:
        r = await c.head(url, follow_redirects=False, timeout=8)
        loc = r.headers.get("location")
        if loc:
            return loc
        r = await c.get(url, follow_redirects=False, timeout=8)
        return r.headers.get("location") or url
    except httpx.HTTPError:
        return url


async def grounded(claim: str) -> tuple[str, list, list]:
    ans = await llm.grounded_search(RESEARCH_PROMPT.format(today=dt.date.today().strftime("%d %B %Y"), claim=claim))
    async with httpx.AsyncClient() as c:
        urls = await asyncio.gather(*[_resolve_redirect(c, s["url"]) for s in ans.sources])
    items = []
    for s, url in zip(ans.sources, urls):
        items.append({
            "title": s["title"],  # grounding often only gives the domain; dedupe() fills gaps
            "url": url,
            "snippet": " ".join(s["snippets"])[:700],
            "via": "Google Search",
        })
    return ans.text, items, ans.queries


def _ddg(query: str, news: bool) -> list:
    from ddgs import DDGS

    try:
        with DDGS() as d:
            res = d.news(query, max_results=6) if news else d.text(query, max_results=6)
        return list(res or [])
    except Exception as e:
        log.info("ddgs %s failed: %s", "news" if news else "web", e)
        return []


async def web_search(query: str) -> list:
    web, news = await asyncio.gather(asyncio.to_thread(_ddg, query, False), asyncio.to_thread(_ddg, query, True))
    out = []
    for r in web:
        out.append({"title": r.get("title", ""), "url": r.get("href", ""), "snippet": r.get("body", ""), "via": "Web search"})
    for r in news:
        out.append({"title": r.get("title", ""), "url": r.get("url", ""), "snippet": r.get("body", ""),
                    "date": (r.get("date") or "")[:10], "publisher": r.get("source", ""), "via": "News search"})
    return out


async def wikipedia(query: str) -> list:
    try:
        async with httpx.AsyncClient(timeout=10, headers={"User-Agent": "TruthLens/1.0 (fact-check research)"}) as c:
            r = await c.get("https://en.wikipedia.org/w/api.php", params={
                "action": "query", "list": "search", "srsearch": query, "srlimit": 3, "format": "json"})
            hits = r.json().get("query", {}).get("search", [])
            out = []
            for h in hits:
                title = h["title"]
                ex = await c.get("https://en.wikipedia.org/w/api.php", params={
                    "action": "query", "prop": "extracts", "exintro": 1, "explaintext": 1,
                    "titles": title, "format": "json"})
                pages = ex.json().get("query", {}).get("pages", {})
                text = next(iter(pages.values()), {}).get("extract", "")
                out.append({"title": f"{title} — Wikipedia", "url": f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                            "snippet": text[:900], "publisher": "Wikipedia", "via": "Wikipedia"})
            return out
    except Exception as e:
        log.info("wikipedia failed: %s", e)
        return []


async def newsapi(query: str) -> list:
    if not config.NEWSAPI_KEY:
        return []
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get("https://newsapi.org/v2/everything", params={
                "q": query, "pageSize": 6, "sortBy": "relevancy", "language": "en"},
                headers={"X-Api-Key": config.NEWSAPI_KEY})
            arts = r.json().get("articles", [])
        return [{"title": a.get("title", ""), "url": a.get("url", ""),
                 "snippet": (a.get("description") or "") + " " + (a.get("content") or "")[:300],
                 "date": (a.get("publishedAt") or "")[:10], "publisher": (a.get("source") or {}).get("name", ""),
                 "via": "NewsAPI"} for a in arts]
    except Exception as e:
        log.info("newsapi failed: %s", e)
        return []


def _norm_url(u: str) -> str:
    u = re.sub(r"[?#].*$", "", u.strip().lower())
    return re.sub(r"^https?://(www\.|m\.)?", "", u).rstrip("/")


def dedupe(items: list, limit=12) -> list:
    seen, titles, out = set(), set(), []
    for it in items:
        if not it.get("url"):
            continue
        key = _norm_url(it["url"])
        tkey = re.sub(r"\W+", " ", (it.get("title") or "").lower()).strip()[:70]
        if key in seen or (tkey and len(tkey) > 25 and tkey in titles):
            continue
        seen.add(key)
        titles.add(tkey)
        it["domain"] = domain_of(it["url"])
        it["publisher"] = it.get("publisher") or publisher_name(it["url"])
        it["tier"] = tier_of(it["url"])
        if not it.get("title"):
            it["title"] = it["domain"]
        out.append(it)
    return out[:limit]


_STOP = set("""a an the of to in on for and or is are was were be been being by with from at as that this these those it its
has have had will would can could should may might not no yes do does did said says say about after before over under into
than then there their they them he she his her we our you your i me my who what when where which why how all any more most
also just new news report reports reported according""".split())

_SKIP_FETCH = ("youtube.com", "facebook.com", "instagram.com", "x.com", "twitter.com", "tiktok.com", "reddit.com", "msn.com")


def _terms(text: str) -> dict:
    """Claim terms with weights: numbers and capitalised names count more."""
    out = {}
    for w in re.findall(r"[A-Za-z][A-Za-z\-']+|\d[\d,.]*", text):
        lw = w.lower().strip(".,")
        if lw in _STOP or len(lw) < 2:
            continue
        wt = 2.0 if lw[0].isdigit() else 1.5 if w[0].isupper() else 1.0
        out[lw] = max(out.get(lw, 0), wt)
    return out


def _overlap(terms: dict, text: str) -> float:
    toks = set(re.findall(r"[a-z][a-z\-']+|\d[\d,.]*", text.lower()))
    return sum(w for t, w in terms.items() if t in toks)


def best_passages(text: str, terms: dict, max_chars=1100) -> str:
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+|\n+", text) if 25 < len(s.strip()) < 600]
    if not sents:
        return ""
    scored = sorted(range(len(sents)), key=lambda i: _overlap(terms, sents[i]), reverse=True)
    keep = set()
    for i in scored[:4]:
        if _overlap(terms, sents[i]) <= 0:
            break
        keep.update({i, i + 1} if i + 1 < len(sents) else {i})
    out, n = [], 0
    for i in sorted(keep):
        if n + len(sents[i]) > max_chars:
            break
        out.append(sents[i])
        n += len(sents[i])
    return " ".join(out)


async def _fetch_passage(c: httpx.AsyncClient, it: dict, terms: dict):
    import trafilatura

    try:
        r = await c.get(it["url"], timeout=10, follow_redirects=True)
        if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
            return
        data = await asyncio.to_thread(trafilatura.bare_extraction, r.text[:2_000_000], url=str(r.url), with_metadata=True)
        if data is None:
            return
        d = data if isinstance(data, dict) else data.as_dict()
        body = d.get("text") or ""
        p = best_passages(body, terms)
        if p:
            it["passage"] = p
        if d.get("date") and not it.get("date"):
            it["date"] = d["date"][:10]
        if d.get("title") and len(it.get("title") or "") < 12:
            it["title"] = d["title"]
    except Exception:
        return


def _rank(items: list, terms: dict) -> list:
    def key(it):
        rel = _overlap(terms, (it.get("title") or "") + " " + (it.get("snippet") or ""))
        return rel * (0.6 + TIER_WEIGHT.get(it.get("tier", "general"), 0.5)) + (3 if it.get("via") == "Google Search" else 0)
    return sorted(items, key=key, reverse=True)


async def gather_evidence(claim: dict, use_llm: bool) -> dict:
    """Collect evidence for one claim from every configured source."""
    text = claim["text"]
    q1 = (claim.get("search_query") or text).strip()
    queries = [q1]
    if text.lower() != q1.lower():
        queries.append(text[:220])
    queries.append(f"{q1} fact check")
    terms = _terms(text)

    tasks = [web_search(q) for q in queries] + [wikipedia(q1), newsapi(q1)]
    if use_llm and llm.grounding_available():
        tasks.append(grounded(text))
    results = await asyncio.gather(*tasks, return_exceptions=True)

    brief, g_items, errors = "", [], []
    pool = []
    for r in results:
        if isinstance(r, Exception):
            errors.append(str(r)[:200])
        elif isinstance(r, tuple):  # grounded
            brief, g_items, gq = r
            queries = gq or queries
        else:
            pool.extend(r)
    items = dedupe(g_items + pool, limit=40)
    items = _rank(items, terms)[:12]

    # read the top articles in full and keep the passages that discuss the claim
    to_fetch = [it for it in items if it["domain"] not in _SKIP_FETCH and it.get("via") != "Wikipedia"][:7]
    async with httpx.AsyncClient(headers={"User-Agent": UA, "Accept-Language": "en"}) as c:
        await asyncio.gather(*[_fetch_passage(c, it, terms) for it in to_fetch])
    for i, it in enumerate(items):
        it["id"] = f"E{i + 1}"
    return {"brief": brief, "items": items, "queries": queries, "errors": errors}
