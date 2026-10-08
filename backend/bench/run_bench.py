"""Accuracy benchmark for the text verification pipeline.

  python -m bench.run_bench curated            # 45 hand-labelled claims
  python -m bench.run_bench averitec --n 80    # stratified sample of AVeriTeC dev
  python -m bench.run_bench report             # print metrics for all finished runs

Predictions are appended to bench/results/<set>.jsonl so runs can resume.
"""
import argparse
import asyncio
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

from app import pipeline, preprocess  # noqa: E402

MAP = {
    "Supported": "Supported",
    "Refuted": "Contradicted",
    "Not Enough Evidence": "Insufficient",
    "Conflicting Evidence/Cherrypicking": "Mixed",
}
LABELS = ["Supported", "Contradicted", "Mixed", "Insufficient"]


def load(name: str, n: int, seed=7):
    if name == "curated":
        items = json.load(open(ROOT / "data" / "curated.json", encoding="utf-8"))
        return [{"id": f"c{i}", "claim": x["claim"], "gold": MAP[x["label"]], "as_of": ""} for i, x in enumerate(items)]
    path = ROOT / "data" / "averitec_dev.json"
    if not path.exists():  # AVeriTeC dev set (CC BY-NC 4.0) is fetched on first use, not shipped
        import urllib.request

        print("downloading AVeriTeC dev set…")
        urllib.request.urlretrieve("https://huggingface.co/chenxwh/AVeriTeC/resolve/main/data/dev.json", path)
    data = json.load(open(path, encoding="utf-8"))
    by = defaultdict(list)
    for i, x in enumerate(data):
        by[x["label"]].append({"id": f"a{i}", "claim": x["claim"], "gold": MAP[x["label"]],
                               "as_of": x.get("claim_date") or "", "speaker": x.get("speaker") or ""})
    rnd = random.Random(seed)
    # roughly natural mix, but enough minority-class items to measure them
    quota = {"Refuted": int(n * 0.40), "Supported": int(n * 0.30),
             "Conflicting Evidence/Cherrypicking": int(n * 0.15), "Not Enough Evidence": n - int(n * 0.40) - int(n * 0.30) - int(n * 0.15)}
    out = []
    for lab, q in quota.items():
        out += rnd.sample(by[lab], q)
    rnd.shuffle(out)
    return out


async def run_one(item):
    prep = preprocess.prepare_text(item["claim"])
    if item.get("as_of"):
        # AVeriTeC dates are DD-MM-YYYY; the speaker is context, not part of the claim
        prep.meta["as_of"] = item["as_of"] + (f" (stated by {item['speaker']})" if item.get("speaker") else "")
    t = time.monotonic()
    async for ev in pipeline.run(prep):
        if ev["type"] == "report":
            r = ev["report"]
            return {"id": item["id"], "claim": item["claim"], "gold": item["gold"], "pred": r["verdict"],
                    "confidence": r["confidence"], "engine": r["engines"].get("analysis"),
                    "n_sources": sum(len(c["evidence"]) for c in r["claims"]),
                    "explanation": r["explanation"][:400], "secs": round(time.monotonic() - t, 1)}


async def run(name: str, n: int, conc: int):
    out_path = ROOT / "results" / f"{name}.jsonl"
    out_path.parent.mkdir(exist_ok=True)
    done = set()
    if out_path.exists():
        done = {json.loads(l)["id"] for l in out_path.open(encoding="utf-8") if l.strip()}
    items = [x for x in load(name, n) if x["id"] not in done]
    print(f"{name}: {len(done)} done, {len(items)} to go")
    sem = asyncio.Semaphore(conc)

    async def go(it):
        async with sem:
            try:
                res = await run_one(it)
            except Exception as e:
                print("  ERROR", it["id"], type(e).__name__, str(e)[:120])
                return
            with out_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(res, ensure_ascii=False) + "\n")
            mark = "✓" if res["pred"] == res["gold"] else "✗"
            print(f"  {mark} {res['gold']:<12} → {res['pred']:<12} {res['confidence']:>3}%  {res['secs']:>5}s  {it['claim'][:70]}")

    await asyncio.gather(*[go(it) for it in items])
    report(name)


def report(name: str):
    path = ROOT / "results" / f"{name}.jsonl"
    rows = [json.loads(l) for l in path.open(encoding="utf-8") if l.strip()]
    rows = [r for r in rows if not (r.get("engine") or "").startswith("Local")] or rows
    n = len(rows)
    acc = sum(r["pred"] == r["gold"] for r in rows) / n
    f1s = []
    lines = []
    for lab in LABELS:
        tp = sum(r["pred"] == lab and r["gold"] == lab for r in rows)
        fp = sum(r["pred"] == lab and r["gold"] != lab for r in rows)
        fn = sum(r["pred"] != lab and r["gold"] == lab for r in rows)
        sup = tp + fn
        if sup == 0:
            continue
        p = tp / (tp + fp) if tp + fp else 0
        rc = tp / sup
        f1 = 2 * p * rc / (p + rc) if p + rc else 0
        f1s.append(f1)
        lines.append(f"    {lab:<13} n={sup:<3} precision={p:.2f} recall={rc:.2f} F1={f1:.2f}")
    # binary: true vs false claims only (the core "is this fake?" question)
    tf = [r for r in rows if r["gold"] in ("Supported", "Contradicted")]
    bin_acc = sum(r["pred"] == r["gold"] for r in tf) / len(tf) if tf else 0
    flipped = sum({r["pred"], r["gold"]} == {"Supported", "Contradicted"} for r in rows)
    print(f"\n== {name}: {n} claims")
    print(f"  4-class accuracy : {acc:.1%}   macro-F1: {sum(f1s) / len(f1s):.3f}")
    print(f"  true/false claims: {bin_acc:.1%} exact ({len(tf)} claims)")
    print(f"  opposite verdicts (true called false or vice versa): {flipped}")
    print("\n".join(lines))
    cm = Counter((r["gold"], r["pred"]) for r in rows)
    print("  confusion (gold → pred):")
    for g in LABELS:
        row = "  ".join(f"{p[:5]}:{cm[(g, p)]:<2}" for p in LABELS)
        print(f"    {g[:12]:<12} {row}")
    secs = [r["secs"] for r in rows]
    print(f"  median latency: {sorted(secs)[len(secs) // 2]}s")
    return acc


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("set", choices=["curated", "averitec", "report"])
    ap.add_argument("--n", type=int, default=80)
    ap.add_argument("--conc", type=int, default=3)
    a = ap.parse_args()
    if a.set == "report":
        for f in sorted((ROOT / "results").glob("*.jsonl")):
            report(f.stem)
    else:
        asyncio.run(run(a.set, a.n, a.conc))
