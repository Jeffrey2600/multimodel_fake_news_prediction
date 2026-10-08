"""Speech-to-text accuracy (word error rate) on synthetic news-claim recordings.

Generates speech with several neural voices (Indian, US, UK English; male/female), adds a
noisy variant, transcribes with the app's transcription path and reports WER.

  python -m bench.stt_bench
"""
import asyncio
import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent))

import edge_tts  # noqa: E402
import jiwer  # noqa: E402

from app import preprocess  # noqa: E402

SENTENCES = [
    "NASA has confirmed that the Earth will experience six days of complete darkness in December.",
    "India won the ICC Champions Trophy in March 2025 after defeating New Zealand by four wickets in Dubai.",
    "The Reserve Bank of India announced the withdrawal of two thousand rupee notes from circulation in May 2023.",
    "Chandrayaan-3 landed near the south pole of the Moon on the twenty third of August 2023.",
    "According to a viral message, drinking hot water with lemon every morning kills the coronavirus.",
    "Prime Minister Narendra Modi was sworn in for a third consecutive term in June 2024.",
    "Sunita Williams returned to Earth in March 2025 after spending more than nine months on the space station.",
    "The World Health Organization says the new variant spreads faster but does not cause more severe illness.",
    "Gukesh Dommaraju became the youngest undisputed world chess champion at the age of eighteen.",
    "A forwarded post claims that the government will deposit fifteen thousand rupees into every bank account next week.",
    "The Air India flight from Ahmedabad to London crashed shortly after takeoff on the twelfth of June 2025.",
    "Scientists warn that global temperatures in 2024 were about one and a half degrees above pre-industrial levels.",
]
VOICES = ["en-IN-NeerjaNeural", "en-IN-PrabhatNeural", "en-US-GuyNeural", "en-GB-SoniaNeural"]

NUM_WORDS = {
    "0": "zero", "1": "one", "2": "two", "3": "three", "4": "four", "5": "five", "6": "six", "7": "seven", "8": "eight",
    "9": "nine", "10": "ten", "12": "twelve", "15": "fifteen", "18": "eighteen", "23": "twenty three",
}


def norm(t: str) -> str:
    t = t.lower().replace("-", " ").replace("₹", "rupees ")
    t = re.sub(r"(\d+)(st|nd|rd|th)\b", r"\1", t)
    t = re.sub(r"[^\w\s.]", " ", t)
    t = re.sub(r"(?<!\d)\.|\.(?!\d)", " ", t)
    # numbers spoken vs written: compare in a single canonical form
    t = t.replace("2,000", "2000").replace("15,000", "15000")
    reps = {"two thousand": "2000", "fifteen thousand": "15000", "one and a half": "1.5", "twenty third": "23",
            "twelfth": "12", "eighteen": "18", "four": "4", "six": "6", "three": "3", "nine": "9", "first": "1"}
    for k, v in reps.items():
        t = re.sub(rf"\b{k}\b", v, t)
    return re.sub(r"\s+", " ", t).strip()


async def synth(text: str, voice: str, out: Path):
    await edge_tts.Communicate(text, voice).save(str(out))


def add_noise(src: Path, out: Path):
    subprocess.run([preprocess._ffmpeg(), "-y", "-i", str(src), "-f", "lavfi", "-i", "anoisesrc=color=pink:amplitude=0.06",
                    "-filter_complex", "[0][1]amix=inputs=2:duration=first:weights=1 1", str(out)],
                   capture_output=True, check=True)


async def main():
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        jobs = []
        for i, s in enumerate(SENTENCES):
            voice = VOICES[i % len(VOICES)]
            clean = tmp / f"s{i}.mp3"
            await synth(s, voice, clean)
            jobs.append((s, voice, "clean", clean))
            if i % 2 == 0:
                noisy = tmp / f"s{i}_noisy.wav"
                add_noise(clean, noisy)
                jobs.append((s, voice, "noisy", noisy))
        for ref, voice, cond, path in jobs:
            d = tmp / f"job_{path.stem}"
            d.mkdir()
            p = d / path.name
            p.write_bytes(path.read_bytes())
            hyp, engine = await preprocess.transcribe(str(p))
            w = jiwer.wer(norm(ref), norm(hyp))
            rows.append({"voice": voice, "cond": cond, "wer": w, "engine": engine, "ref": ref, "hyp": hyp})
            print(f"  WER {w:5.1%}  {cond:<5} {voice:<20} {hyp[:80]}")
    for cond in ("clean", "noisy"):
        rs = [r for r in rows if r["cond"] == cond]
        refs = [norm(r["ref"]) for r in rs]
        hyps = [norm(r["hyp"]) for r in rs]
        print(f"\n{cond}: corpus WER {jiwer.wer(refs, hyps):.2%} over {len(rs)} recordings")
    allw = jiwer.wer([norm(r["ref"]) for r in rows], [norm(r["hyp"]) for r in rows])
    print(f"overall corpus WER {allw:.2%}  → word accuracy {1 - allw:.2%}   engine: {rows[0]['engine']}")
    (ROOT / "results").mkdir(exist_ok=True)
    json.dump(rows, open(ROOT / "results" / "stt.json", "w", encoding="utf-8"), indent=1, ensure_ascii=False)


if __name__ == "__main__":
    asyncio.run(main())
