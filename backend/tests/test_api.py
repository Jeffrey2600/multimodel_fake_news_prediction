"""Functional checks of the API surface that don't spend AI quota.

  python -m pytest tests -q        (or)        python tests/test_api.py
Runs against an isolated temp database.
"""
import io
import os
import sys
import tempfile
from pathlib import Path

os.environ["TRUTHLENS_DB"] = str(Path(tempfile.mkdtemp()) / "test.db")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import credibility, db  # noqa: E402
from app.claims import _is_single_claim, local_extract  # noqa: E402
from app.main import app  # noqa: E402
from app.security import InputError, classify_upload, validate_public_url  # noqa: E402

c = TestClient(app)
H = {"X-Client-Id": "test-client"}


def test_status():
    r = c.get("/api/status")
    assert r.status_code == 200 and "models" in r.json()


def test_rejects_unsupported_file():
    r = c.post("/api/verify", data={"kind": "file"}, files={"file": ("virus.exe", b"MZ\x90\x00", "application/octet-stream")}, headers=H)
    assert r.status_code == 400 and "supported" in r.json()["detail"]


def test_rejects_fake_pdf():
    r = c.post("/api/verify", data={"kind": "file"}, files={"file": ("x.pdf", b"hello", "application/pdf")}, headers=H)
    assert r.status_code == 400 and "valid PDF" in r.json()["detail"]


def test_rejects_empty_text():
    r = c.post("/api/verify", data={"kind": "text", "text": "  "}, headers=H)
    assert r.status_code == 400


def test_ssrf_guard():
    for bad in ["http://127.0.0.1:8000/api/status", "http://localhost/", "http://192.168.1.1/", "file:///etc/passwd"]:
        try:
            validate_public_url(bad)
            raise AssertionError(f"accepted {bad}")
        except InputError:
            pass
    assert validate_public_url("example.com").startswith("https://")


def test_short_text_is_rejected_in_stream():
    r = c.post("/api/verify", data={"kind": "text", "text": "hi"}, headers=H)
    assert '"type": "error"' in r.text


def test_upload_classification():
    assert classify_upload("a.png", b"\x89PNG\r\n", 100) == ("image", "image/png")
    assert classify_upload("a.docx", b"PK\x03\x04", 100)[0] == "document"
    assert classify_upload("talk.m4a", b"\x00\x00", 100)[0] == "audio"
    assert classify_upload("clip.mp4", b"\x00\x00", 100)[0] == "video"


def test_document_extraction():
    import asyncio

    import docx

    from app import preprocess

    d = docx.Document()
    d.add_paragraph("The Reserve Bank of India withdrew the 2000 rupee note in May 2023.")
    buf = io.BytesIO()
    d.save(buf)
    p = asyncio.run(preprocess.prepare_document(buf.getvalue(), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "a.docx"))
    assert "2000 rupee" in p.text

    import pymupdf

    pdf = pymupdf.open()
    pdf.new_page().insert_text((72, 72), "Chandrayaan-3 landed near the lunar south pole on 23 August 2023, said ISRO officials.")
    p = asyncio.run(preprocess.prepare_document(pdf.tobytes(), "application/pdf", "a.pdf"))
    assert "Chandrayaan-3" in p.text


def test_auth_history_share_flow():
    r = c.post("/api/auth/register", json={"name": "Test", "email": "t@example.com", "password": "longpassword"}, headers=H)
    assert r.status_code == 200
    token = r.json()["token"]
    auth = {**H, "Authorization": f"Bearer {token}"}
    assert c.get("/api/auth/me", headers=auth).json()["email"] == "t@example.com"
    assert c.post("/api/auth/login", json={"email": "t@example.com", "password": "wrongpass"}).status_code == 401
    assert c.post("/api/auth/register", json={"name": "T", "email": "t@example.com", "password": "longpassword"}).status_code == 409

    # store a finished report directly and exercise history / share / delete
    vid = db.create_verification("text", "Test claim", r.json()["user"]["user_id"], "test-client")
    rep = {"verdict": "Supported", "confidence": 90, "claims": [{"text": "Test claim", "verdict": "Supported", "confidence": 90,
           "explanation": "x", "entities": {"dates": []}, "keywords": [], "evidence": [
               {"publisher": "reuters.com", "url": "https://reuters.com/a", "title": "A", "stance": "supports"}]}]}
    db.save_report(vid, rep)
    hist = {h["verification_id"]: h for h in c.get("/api/history", headers=auth).json()}
    assert hist[vid]["verdict"] == "Supported"
    assert c.get("/api/history", headers={"X-Client-Id": "someone-else"}).json() == []  # not visible to others
    sid = c.post(f"/api/verifications/{vid}/share", headers=auth).json()["share_id"]
    assert c.get(f"/api/shared/{sid}").json()["verdict"] == "Supported"  # public read-only link
    assert c.get(f"/api/verifications/{vid}", headers={"X-Client-Id": "someone-else"}).status_code == 404
    assert c.delete(f"/api/verifications/{vid}", headers=auth).json()["ok"]
    assert vid not in {h["verification_id"] for h in c.get("/api/history", headers=auth).json()}


def test_no_path_traversal():
    secret = (Path(__file__).resolve().parent.parent / "app" / "config.py").read_text(encoding="utf-8")[:40]
    for p in ["/../backend/app/config.py", "/..%2F..%2Fbackend%2Fapp%2Fconfig.py", "/%2e%2e/%2e%2e/backend/app/config.py",
              "/file=../../backend/app/config.py", "/assets/../../../backend/app/config.py"]:
        r = c.get(p)
        assert secret not in r.text, f"leaked via {p}"
    assert c.get("/api/does-not-exist").status_code == 404


def test_credibility_tiers():
    assert credibility.tier_of("https://www.pib.gov.in/x") == "official"
    assert credibility.tier_of("https://factcheck.afp.com/x") == "factcheck"
    assert credibility.tier_of("https://www.reuters.com/x") == "wire"
    assert credibility.tier_of("https://www.thehindu.com/x") == "major"
    assert credibility.tier_of("https://en.wikipedia.org/wiki/X") == "reference"
    assert credibility.tier_of("https://www.facebook.com/x") == "social"
    assert credibility.tier_of("https://www.theonion.com/x") == "unreliable"


def test_claim_helpers():
    assert _is_single_claim("Pope Francis died in April 2025.")
    assert not _is_single_claim("India won. Rohit was player of the match.")
    q = local_extract("RBI withdrew ₹2,000 notes in May 2023.")["claims"][0]["search_query"]
    assert "2,000" in q


if __name__ == "__main__":
    fails = 0
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            try:
                fn()
                print("PASS", name)
            except Exception as e:
                fails += 1
                print("FAIL", name, type(e).__name__, e)
    print(f"\n{'all passed' if not fails else f'{fails} failed'}")
    sys.exit(1 if fails else 0)
