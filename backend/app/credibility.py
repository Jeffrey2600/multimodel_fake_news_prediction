"""Source-quality tiers used to weight evidence.

Tier weights are deliberately coarse; they decide how much a source counts,
never whether it agrees with the claim.
"""
from urllib.parse import urlparse

TIERS = {
    "official": 1.0,      # governments, intergovernmental bodies, courts, science agencies
    "factcheck": 0.95,    # IFCN-style fact-checkers
    "wire": 0.95,         # news agencies
    "major": 0.85,        # established newsrooms
    "reference": 0.75,    # encyclopedias, journals
    "general": 0.5,       # unknown / blogs
    "social": 0.25,       # user generated
    "unreliable": 0.1,    # known fabricators / satire
}

_DOMAINS = {
    "factcheck": [
        "snopes.com", "politifact.com", "factcheck.org", "fullfact.org", "altnews.in", "boomlive.in",
        "factly.in", "afp.com", "factcheck.afp.com", "leadstories.com", "checkyourfact.com",
        "healthfeedback.org", "sciencefeedback.co", "vishvasnews.com", "newschecker.in",
        "thequint.com", "logicallyfacts.com", "africacheck.org", "teyit.org", "maldita.es",
    ],
    "wire": ["reuters.com", "apnews.com", "pti.in", "ptinews.com", "aninews.in", "dpa.com", "efe.com", "ians.in"],
    "major": [
        "bbc.com", "bbc.co.uk", "nytimes.com", "washingtonpost.com", "theguardian.com", "wsj.com",
        "ft.com", "economist.com", "bloomberg.com", "cnn.com", "nbcnews.com", "cbsnews.com",
        "abcnews.go.com", "npr.org", "pbs.org", "aljazeera.com", "dw.com", "france24.com",
        "thehindu.com", "indianexpress.com", "hindustantimes.com", "timesofindia.indiatimes.com",
        "ndtv.com", "livemint.com", "economictimes.indiatimes.com", "business-standard.com",
        "theprint.in", "scroll.in", "indiatoday.in", "deccanherald.com", "news18.com",
        "espncricinfo.com", "cricinfo.com", "wisden.com", "sportstar.thehindu.com", "espn.com", "skysports.com", "cricbuzz.com", "time.com", "usatoday.com",
        "latimes.com", "axios.com", "politico.com", "theatlantic.com", "nature.com", "science.org",
        "scientificamerican.com", "newscientist.com", "cnbc.com", "forbes.com", "abc.net.au",
        "cbc.ca", "japantimes.co.jp", "scmp.com", "straitstimes.com", "independent.co.uk",
        "telegraph.co.uk", "sky.com", "lemonde.fr", "spiegel.de", "bcci.tv", "icc-cricket.com",
        "fifa.com", "olympics.com", "nasa.gov",
    ],
    "reference": [
        "wikipedia.org", "britannica.com", "who.int", "pubmed.ncbi.nlm.nih.gov", "ncbi.nlm.nih.gov",
        "arxiv.org", "jstor.org", "worldbank.org", "imf.org", "statista.com", "ourworldindata.org",
    ],
    "social": [
        "facebook.com", "x.com", "twitter.com", "instagram.com", "tiktok.com", "reddit.com",
        "youtube.com", "quora.com", "medium.com", "substack.com", "telegram.me", "t.me",
        "linkedin.com", "pinterest.com", "threads.net",
    ],
    "unreliable": [
        "theonion.com", "babylonbee.com", "infowars.com", "naturalnews.com", "beforeitsnews.com",
        "worldnewsdailyreport.com", "yournewswire.com", "newspunch.com", "thegatewaypundit.com",
        "postcard.news", "fakingnews.com",
    ],
}

_LOOKUP = {d: tier for tier, ds in _DOMAINS.items() for d in ds}

_OFFICIAL_SUFFIXES = (".gov", ".gov.in", ".nic.in", ".gov.uk", ".gov.au", ".gc.ca", ".mil", ".europa.eu", ".un.org", ".int")


def domain_of(url: str) -> str:
    try:
        host = (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def tier_of(url_or_domain: str) -> str:
    d = domain_of(url_or_domain) if "/" in url_or_domain else url_or_domain.lower()
    if not d:
        return "general"
    if d.endswith(_OFFICIAL_SUFFIXES) or d in ("who.int", "un.org"):
        return "official"
    parts = d.split(".")
    for i in range(len(parts) - 1):
        cand = ".".join(parts[i:])
        if cand in _LOOKUP:
            return _LOOKUP[cand]
    if d.endswith(".edu") or d.endswith(".ac.in") or d.endswith(".ac.uk"):
        return "reference"
    return "general"


def weight_of(url: str) -> float:
    return TIERS[tier_of(url)]


def publisher_name(url: str, fallback: str = "") -> str:
    d = domain_of(url)
    if not d:
        return fallback
    return d
