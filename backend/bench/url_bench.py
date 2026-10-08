"""URL input accuracy: does the app pull the right headline and a full article body from real news pages?

Collects fresh article links from news search across several outlets, runs the app's own URL
preprocessing, and checks the extracted title against the publisher's headline.

  python -m bench.url_bench
"""
import asyncio
import difflib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from ddgs import DDGS  # noqa: E402

from app import preprocess  # noqa: E402
from app.security import InputError  # noqa: E402

TOPICS = ["India cricket", "ISRO mission", "RBI policy", "monsoon rainfall India", "Supreme Court India ruling",
          "NASA", "stock market today", "election commission", "climate change report", "football transfer"]


def collect(n_per=3):
    seen, out = set(), []
    with DDGS() as d:
        for t in TOPICS:
            try:
                res = d.news(t, max_results=8) or []
            except Exception:
                continue
            taken = 0
            for r in res:
                dom = re.sub(r"^https?://(www\.)?", "", r["url"]).split("/")[0]
                if dom in seen or "msn.com" in dom or "yahoo.com" in dom:
                    continue
                seen.add(dom)
                out.append({"url": r["url"], "title": r["title"], "source": r.get("source") or dom})
                taken += 1
                if taken >= n_per:
                    break
    return out


def sim(a, b):
    norm = lambda s: re.sub(r"\W+", " ", s.lower()).strip()
    return difflib.SequenceMatcher(None, norm(a), norm(b)).ratio()


async def main():
    fixed = ROOT / "data" / "urls.json"
    if fixed.exists():
        items = json.load(open(fixed, encoding="utf-8"))
    else:
        items = collect()
        json.dump(items, open(fixed, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
    print(f"{len(items)} live article links from {len({i['source'] for i in items})} outlets")
    rows = []
    for it in items:
        try:
            p = await preprocess.prepare_url(it["url"])
            title = p.meta.get("title", "")
            s = max(sim(title, it["title"]), sim(title, it["title"].split(" - ")[0]))
            words = len(p.text.split())
            ok = s >= 0.6 and words >= 150
            rows.append({**it, "status": "ok" if ok else "partial", "title_sim": round(s, 2), "words": words,
                         "got_title": title, "date": p.meta.get("date")})
            print(f"  {'✓' if ok else '~'} sim={s:.2f} words={words:<5} {it['source'][:22]:<22} {title[:60]}")
        except InputError as e:
            rows.append({**it, "status": "blocked", "error": str(e)})
            print(f"  ✗ blocked  {it['source'][:22]:<22} {str(e)[:70]}")
    n = len(rows)
    ok = sum(r["status"] == "ok" for r in rows)
    blocked = sum(r["status"] == "blocked" for r in rows)
    readable = [r for r in rows if r["status"] != "blocked"]
    print(f"\nfull, correct extraction: {ok}/{n} = {ok / n:.0%}")
    print(f"pages that allow automated reading: {len(readable)}/{n}; of those, correct: {ok}/{len(readable)} = {ok / max(1, len(readable)):.0%}")
    print(f"blocked by site (paywall / bot protection; user is told to paste text): {blocked}")
    dated = sum(1 for r in readable if r.get("date"))
    print(f"publication date found: {dated}/{len(readable)}")
    json.dump(rows, open(ROOT / "results" / "url.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
