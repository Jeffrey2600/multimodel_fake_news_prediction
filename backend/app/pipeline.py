"""Runs the full verification workflow and yields progress events.

input -> preprocessing -> claim extraction -> evidence retrieval -> evidence analysis
      -> verification engine -> result & explanation
"""
import asyncio
import logging
import time
from typing import AsyncIterator

from . import analysis, claims as claims_mod, llm, retrieval
from .preprocess import Prepared

log = logging.getLogger("truthlens.pipeline")

STEPS = ["read", "claims", "evidence", "analysis", "verdict"]


def ev(step: str, state: str, detail: str = "", **extra) -> dict:
    return {"type": "step", "step": step, "state": state, "detail": detail, **extra}


async def run(prep: Prepared) -> AsyncIterator[dict]:
    t0 = time.monotonic()
    use_llm = llm.enabled()
    engines = {}
    yield ev("read", "done", f"{len(prep.text.split())} words ready", notes=prep.notes)

    # ---- claim extraction
    yield ev("claims", "active", "Finding the checkable statements")
    hint = ""
    if prep.kind == "url" and prep.meta.get("publisher"):
        hint = f"Article from {prep.meta.get('publisher')}, published {prep.meta.get('date') or 'date unknown'}."
    elif prep.meta.get("as_of"):
        hint = f"The content was made on {prep.meta['as_of']}."
    extracted, engines["claims"] = await claims_mod.extract(prep.text, hint)
    claim_list = extracted["claims"]
    yield ev("claims", "done", f"{len(claim_list)} claim{'s' if len(claim_list) != 1 else ''} to check",
             claims=[c["text"] for c in claim_list])

    # ---- evidence retrieval
    yield ev("evidence", "active", "Searching news, the web and reference sources")
    many = len(claim_list) > 2
    evidence = await asyncio.gather(*[retrieval.gather_evidence(c, use_llm, many) for c in claim_list])
    n_src = sum(len(e["items"]) for e in evidence)
    grounded_ok = any(e["brief"] for e in evidence)
    yield ev("evidence", "done", f"{n_src} sources collected" + (" · live Google grounding" if grounded_ok else ""))

    # ---- evidence analysis
    yield ev("analysis", "active", "Comparing each claim against its sources")
    judged, engines["analysis"] = await analysis.analyse(prep.text, prep.kind, claim_list, evidence, use_llm,
                                                         as_of=prep.meta.get("as_of") or prep.meta.get("date") or "")
    yield ev("analysis", "done", engines["analysis"])

    # ---- verification engine
    yield ev("verdict", "active", "Weighing evidence quality and agreement")
    claim_results = []
    for i, (c, e) in enumerate(zip(claim_list, evidence)):
        jc = judged["claims"][i]
        fin = analysis.finalize_claim(jc, e["items"])
        stance = {x.get("id"): x for x in jc.get("evidence", [])}
        items = []
        for it in e["items"]:
            s = stance.get(it["id"], {})
            items.append({**it, "stance": s.get("stance", "neutral"), "relevance": s.get("relevance", 0),
                          "quote": s.get("quote", "")})
        order = {"refutes": 0, "supports": 0, "neutral": 1}
        items.sort(key=lambda x: (order[x["stance"]], -float(x["relevance"] or 0)))
        explanation = jc.get("explanation") or _local_explanation(fin, items)
        claim_results.append({
            "text": c["text"],
            "central": bool(c.get("central")),
            "verdict": fin["verdict"],
            "confidence": fin["confidence"],
            "score": fin["score"],
            "explanation": explanation,
            "discrepancies": jc.get("discrepancies", []),
            "entities": {k: c.get(k, []) for k in ("people", "organizations", "locations", "names", "dates", "numbers")},
            "keywords": c.get("keywords", []),
            "queries": e["queries"],
            "brief": e["brief"],
            "evidence": items,
        })
    verdict, confidence = analysis.overall_verdict(claim_results, [c["central"] for c in claim_results])
    overall_expl = judged.get("overall_explanation") or claim_results[0]["explanation"]
    report = {
        "verdict": verdict,
        "confidence": confidence,
        "summary": extracted.get("summary", ""),
        "explanation": overall_expl,
        "context_gaps": judged.get("context_gaps", []),
        "bias_indicators": judged.get("bias_indicators", []),
        "missing_information": judged.get("missing_information", []),
        "claims": claim_results,
        "input": {"kind": prep.kind, "text": prep.text[:4000], "meta": prep.meta, "notes": prep.notes},
        "engines": engines,
        "degraded": _degraded(use_llm, engines["analysis"]),
        "elapsed": round(time.monotonic() - t0, 1),
    }
    yield ev("verdict", "done", f"{verdict} · {confidence}% confidence")
    yield {"type": "report", "report": report}


def _local_explanation(fin: dict, items: list) -> str:
    s = fin["score"]
    sup = [i["publisher"] for i in items if i["stance"] == "supports"][:3]
    ref = [i["publisher"] for i in items if i["stance"] == "refutes"][:3]
    parts = []
    if sup:
        parts.append(f"{s['n_support']} independent source(s) agree with the claim ({', '.join(sup)}).")
    if ref:
        parts.append(f"{s['n_refute']} independent source(s) conflict with it ({', '.join(ref)}).")
    if not parts:
        parts.append("None of the retrieved sources clearly confirm or contradict the claim.")
    parts.append("This result comes from the offline engine (automatic language-model fallback), so treat it as indicative.")
    return " ".join(parts)


def _degraded(use_llm: bool, engine: str) -> str:
    """Why this verdict deserves less trust than usual ('' when it doesn't)."""
    if not use_llm or engine.startswith("Local"):
        return "Made with the offline engine because the AI service was unavailable. Treat this verdict as indicative."
    if "lite" in engine:
        return ("The main AI models were busy or out of daily quota, so a lighter backup model judged the evidence. "
                "It is less accurate — re-check later for a firmer verdict.")
    return ""
