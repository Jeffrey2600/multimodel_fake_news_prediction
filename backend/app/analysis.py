"""Evidence analysis + verification engine.

Primary path: Gemini reads the claim, the grounded research brief and every retrieved source,
labels each source's stance and gives a claim verdict. The verification engine then combines
those stance labels with source quality, independence and relevance into an evidence score that
calibrates the confidence and guards against verdicts the evidence does not back.

Fallback path (no LLM available): a local NLI model (DeBERTa-v3, MNLI/FEVER/ANLI) scores each
snippet for entailment / contradiction and the same engine aggregates them.
"""
import asyncio
import datetime as dt
import logging

from . import llm
from .credibility import TIERS

log = logging.getLogger("truthlens.analysis")

VERDICTS = ["Supported", "Contradicted", "Mixed", "Insufficient"]

JUDGE_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": VERDICTS},
                    "confidence": {"type": "integer"},
                    "explanation": {"type": "string"},
                    "discrepancies": {"type": "array", "items": {"type": "string"}},
                    "evidence": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "id": {"type": "string"},
                                "stance": {"type": "string", "enum": ["supports", "refutes", "neutral"]},
                                "relevance": {"type": "number"},
                                "quote": {"type": "string"},
                            },
                            "required": ["id", "stance", "relevance"],
                        },
                    },
                },
                "required": ["index", "verdict", "confidence", "explanation", "evidence"],
            },
        },
        "overall_explanation": {"type": "string"},
        "context_gaps": {"type": "array", "items": {"type": "string"}},
        "bias_indicators": {"type": "array", "items": {"type": "string"}},
        "missing_information": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["claims", "overall_explanation", "context_gaps", "bias_indicators", "missing_information"],
}

JUDGE_PROMPT = """You are the verification stage of TruthLens, a professional fact-checking system. Today is {today}.
Judge each claim strictly against the EVIDENCE below (research briefs written from live Google Search results,
plus retrieved sources). Your background knowledge may help you interpret evidence, but a verdict must be
justified by the evidence provided.

Verdict definitions:
- Supported: reliable evidence confirms the claim as stated, including its key specifics (who, what, when,
  where, how much). Minor rounding or wording differences are fine.
- Contradicted: reliable evidence shows the claim is false — the event didn't happen, a key specific is wrong
  (wrong person, date, number, place, outcome), it's a known hoax/fabrication, or it's debunked by fact-checkers.
  If authoritative sources clearly show what really happened and it differs from the claim, that is Contradicted,
  even if no source explicitly says "this claim is false".
- Mixed: the claim combines true and false parts, is technically true but misleading without important context,
  or reliable sources genuinely conflict.
- Insufficient: the evidence is not enough to confirm or refute it (e.g. too vague, too recent, unverifiable private
  matter). Do NOT use Insufficient merely because no source repeats the claim word-for-word — if the brief
  establishes the relevant facts, decide.

Attributed statements ("X said ...", quotes, posts): judge whether WHAT IS ASSERTED is true, not merely whether the
person said it — a false statement accurately quoted is still Contradicted. Only judge the attribution itself when
the claim is about who said what (e.g. "X said Y" where Y is harmless and the dispute is whether X said it).

Also:
- For each claim, label EVERY evidence item: stance (supports / refutes / neutral-or-irrelevant), relevance 0..1,
  and a short quote or paraphrase (max 25 words) of the decisive passage.
- confidence: 0-100, how certain the verdict is given the evidence quality and agreement.
- explanation: 2-4 plain sentences citing what the sources show (mention source names, not ids).
- discrepancies: specific wrong details, e.g. "Claim says 2019; sources say 2021".
- context_gaps / bias_indicators / missing_information: about the SUBMITTED CONTENT as a whole (loaded language,
  one-sided framing, missing dates or sources, cherry-picked numbers, satire). Empty lists if none.
- overall_explanation: 2-3 sentences summarising the verification of the whole submission.

{as_of}SUBMITTED CONTENT ({kind}):
\"\"\"{content}\"\"\"

{claims_block}"""


def _fmt_claims(claims: list, evidence: list) -> str:
    blocks = []
    for i, (c, ev) in enumerate(zip(claims, evidence)):
        lines = [f"=== CLAIM {i}: \"{c['text']}\""]
        if ev["brief"]:
            lines.append("RESEARCH BRIEF (from live Google Search):\n" + ev["brief"].strip()[:4000])
        lines.append("RETRIEVED SOURCES:")
        for it in ev["items"]:
            date = f" ({it['date']})" if it.get("date") else ""
            body = (it.get("snippet") or "")[:400]
            if it.get("passage"):
                body += f"\n    Article excerpt: {it['passage'][:1100]}"
            lines.append(f"[{it['id']}] {it['publisher']}{date} — {it['title']}\n    {body}")
        if not ev["items"]:
            lines.append("(none found)")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


async def judge_llm(content: str, kind: str, claims: list, evidence: list, as_of: str = "") -> tuple[dict, str]:
    as_of_line = (f"The content was published/made on {as_of}. Judge each claim as it stood on that date "
                  "(e.g. 'currently' means as of that date).\n\n") if as_of else ""
    prompt = JUDGE_PROMPT.format(
        today=dt.date.today().strftime("%A, %d %B %Y"), kind=kind, content=content[:6000], as_of=as_of_line,
        claims_block=_fmt_claims(claims, evidence),
    )
    data, model = await llm.generate_json(prompt, schema=JUDGE_SCHEMA)
    return data, model


# ----------------------------------------------------------------- local NLI fallback
_nli = None


def _load_nli():
    """Quantised DeBERTa NLI model on onnxruntime (CPU) — no PyTorch needed."""
    global _nli
    if _nli is None:
        import json

        import onnxruntime as ort
        from huggingface_hub import hf_hub_download
        from tokenizers import Tokenizer

        from . import config

        cfg = json.load(open(hf_hub_download(config.NLI_MODEL, "config.json"), encoding="utf-8"))
        tok = Tokenizer.from_file(hf_hub_download(config.NLI_MODEL, "tokenizer.json"))
        tok.enable_truncation(max_length=320)
        tok.enable_padding()
        sess = ort.InferenceSession(hf_hub_download(config.NLI_MODEL, config.NLI_ONNX_FILE),
                                    providers=["CPUExecutionProvider"])
        labels = [cfg["id2label"][str(i)].lower() for i in range(len(cfg["id2label"]))]
        _nli = (tok, sess, labels)
    return _nli


def nli_scores(premises: list[str], hypothesis: str) -> list[dict]:
    import numpy as np

    tok, sess, labels = _load_nli()
    names = {i.name for i in sess.get_inputs()}
    out = []
    for i in range(0, len(premises), 8):
        batch = premises[i: i + 8]
        enc = tok.encode_batch(list(zip(batch, [hypothesis] * len(batch))))
        feed = {"input_ids": np.array([e.ids for e in enc], dtype=np.int64),
                "attention_mask": np.array([e.attention_mask for e in enc], dtype=np.int64)}
        if "token_type_ids" in names:
            feed["token_type_ids"] = np.array([e.type_ids for e in enc], dtype=np.int64)
        logits = sess.run(None, feed)[0]
        probs = np.exp(logits - logits.max(-1, keepdims=True))
        probs /= probs.sum(-1, keepdims=True)
        for p in probs.tolist():
            out.append(dict(zip(labels, p)))
    return out


def judge_local(claims: list, evidence: list) -> dict:
    res = {"claims": [], "overall_explanation": "", "context_gaps": [], "bias_indicators": [],
           "missing_information": []}
    for i, (c, ev) in enumerate(zip(claims, evidence)):
        items = [it for it in ev["items"] if (it.get("snippet") or "").strip()]
        premises = [(it.get("title", "") + ". " + (it.get("passage") or it["snippet"]))[:1500] for it in items]
        scores = nli_scores(premises, c["text"]) if items else []
        labeled = []
        for it, s in zip(items, scores):
            ent, con = s.get("entailment", 0), s.get("contradiction", 0)
            stance = "supports" if ent > 0.6 and ent > con else "refutes" if con > 0.6 and con > ent else "neutral"
            labeled.append({"id": it["id"], "stance": stance, "relevance": round(max(ent, con), 2),
                            "quote": it["snippet"][:160]})
        res["claims"].append({"index": i, "verdict": None, "confidence": None, "explanation": "",
                              "discrepancies": [], "evidence": labeled})
    return res


# ----------------------------------------------------------------- verification engine
def evidence_score(items_by_id: dict, labeled: list) -> dict:
    """Weighted support vs refute mass, counting each publisher domain once (independence)."""
    best: dict[tuple, float] = {}
    for e in labeled:
        it = items_by_id.get(e.get("id"))
        if not it or e.get("stance") not in ("supports", "refutes"):
            continue
        w = TIERS.get(it.get("tier", "general"), 0.5) * max(0.0, min(1.0, float(e.get("relevance") or 0)))
        key = (it.get("domain", ""), e["stance"])
        best[key] = max(best.get(key, 0), w)
    sup = sum(w for (d, s), w in best.items() if s == "supports")
    ref = sum(w for (d, s), w in best.items() if s == "refutes")
    n_sup = sum(1 for (d, s) in best if s == "supports")
    n_ref = sum(1 for (d, s) in best if s == "refutes")
    return {"support": round(sup, 3), "refute": round(ref, 3), "n_support": n_sup, "n_refute": n_ref,
            "balance": round((sup - ref) / (sup + ref), 3) if sup + ref else 0.0}


def rule_verdict(score: dict) -> tuple[str, int]:
    sup, ref = score["support"], score["refute"]
    total = sup + ref
    if total < 0.45:
        return "Insufficient", 35
    b = score["balance"]
    if b >= 0.5:
        return "Supported", int(min(92, 55 + 25 * min(total, 1.6)))
    if b <= -0.5:
        return "Contradicted", int(min(92, 55 + 25 * min(total, 1.6)))
    return "Mixed", 50


def finalize_claim(llm_claim: dict, items: list) -> dict:
    by_id = {it["id"]: it for it in items}
    score = evidence_score(by_id, llm_claim.get("evidence", []))
    verdict, conf = llm_claim.get("verdict"), llm_claim.get("confidence")
    engine_note = ""
    if verdict not in VERDICTS:  # local path: rule-based verdict
        verdict, conf = rule_verdict(score)
        engine_note = "rule"
    else:
        conf = int(max(0, min(100, conf or 50)))
        # Calibrate: confidence can't exceed what the evidence mass supports.
        mass = score["support"] + score["refute"]
        if verdict in ("Supported", "Contradicted"):
            agrees = score["balance"] > 0 if verdict == "Supported" else score["balance"] < 0
            if mass == 0:
                conf = min(conf, 70)
            elif not agrees:
                conf = min(conf, 60)
        conf = max(conf, 20)
    return {"verdict": verdict, "confidence": conf, "score": score, "engine": engine_note}


def overall_verdict(claim_results: list, centrals: list[bool]) -> tuple[str, int]:
    vs = [c["verdict"] for c in claim_results]
    confs = [c["confidence"] for c in claim_results]
    central_vs = [v for v, ce in zip(vs, centrals) if ce] or vs[:1]
    if all(v == "Supported" for v in vs):
        return "Supported", min(confs)
    if any(v == "Contradicted" for v in central_vs):
        if all(v in ("Contradicted", "Insufficient") for v in vs):
            return "Contradicted", max(c for c, v in zip(confs, vs) if v == "Contradicted")
        return "Mixed", int(sum(confs) / len(confs))
    if any(v in ("Contradicted", "Mixed") for v in vs):
        return "Mixed", int(sum(confs) / len(confs))
    if all(v == "Insufficient" for v in vs) or all(v == "Insufficient" for v in central_vs):
        return "Insufficient", int(sum(confs) / len(confs))
    return "Mixed", int(sum(confs) / len(confs))


async def analyse(content: str, kind: str, claims: list, evidence: list, use_llm: bool,
                  as_of: str = "") -> tuple[dict, str]:
    if use_llm:
        try:
            data, model = await judge_llm(content, kind, claims, evidence, as_of)
            got = {c.get("index"): c for c in data.get("claims", [])}
            if all(i in got for i in range(len(claims))):
                data["claims"] = [got[i] for i in range(len(claims))]
                return data, f"Gemini ({model})"
            log.warning("judge returned incomplete claims; falling back")
        except llm.LLMUnavailable as e:
            log.warning("judge unavailable: %s", e)
    try:
        data = await asyncio.to_thread(judge_local, claims, evidence)
        return data, "Local NLI (DeBERTa-v3)"
    except Exception as e:  # model missing (e.g. no disk space to download it) or failed to load
        log.error("local NLI unavailable: %s", e)
        return {
            "claims": [{"index": i, "verdict": "Insufficient", "confidence": 20, "evidence": [], "discrepancies": [],
                        "explanation": "The AI analysis service is out of capacity and the offline model isn't installed, "
                                       "so the sources below were collected but not assessed. Try again later."}
                       for i in range(len(claims))],
            "overall_explanation": "", "context_gaps": [], "bias_indicators": [], "missing_information": [],
        }, "Local NLI (not installed)"
