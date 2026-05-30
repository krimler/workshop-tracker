#!/usr/bin/env python3
"""Discover workshop candidates from known workshop sources.

The fetcher is deliberately source-plural but not search-engine driven. It
parses known sources, starting with OpenReview, and always checks the current
year and next year.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import ssl
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import parse_qs, urlencode, urljoin, urlparse
from urllib.request import Request, urlopen

try:
    import yaml
except ImportError:  # pragma: no cover - surfaced as a warning at runtime.
    yaml = None

try:
    from fetcher import llm_extract
except ImportError:  # pragma: no cover - allow running as a loose script.
    import llm_extract

ROOT = Path(__file__).resolve().parent.parent
SEEDS_PATH = ROOT / "workshop_seeds.json"
WATCHLIST_PATH = ROOT / "venue_watchlist.json"
CONFERENCE_SOURCES_PATH = ROOT / "conference_sources.json"
OUT_PATH = ROOT / "data" / "workshops.json"
DOCS_OUT_PATH = ROOT / "docs" / "workshops.json"  # published data feed for the static site

UPSTREAM_CONFERENCE_REPOS = {
    "ccfddl": "https://github.com/ccfddl/ccf-deadlines.git",
    "ai_deadlines": "https://github.com/paperswithcode/ai-deadlines.git",
    "sec_deadlines": "https://github.com/sec-deadlines/sec-deadlines.github.io.git",
    "tcs_conf": "https://github.com/tcs-conf/tcs-conf.github.io.git",
}

CCFDDL_AREA_MAP = {
    "AI": "ai_ml",
    "DB": "databases",
    "SE": "software_engineering",
    "DS": "distributed_systems",
    "NW": "networking",
    "NS": "security",
    "TC": "theory",
    "CG": "systems",
    "HI": "biomedical",
}

SOURCE_LOCATIONS = {
    "openreview": ("openreview.net",),
    "hotcrp": ("hotcrp.com",),
    "wikicfp": ("wikicfp.com",),
    "dblp": ("dblp.org",),
    "researchr": ("conf.researchr.org",),
    "usenix": ("usenix.org",),
    "acm": ("acm.org", "sigcomm.org", "sigsoft.org"),
    "ieee": ("ieee.org", "computer.org"),
    "biomedical": ("amia.org", "iscb.org", "miccai.org"),
}

TRUSTED_SOURCE_KINDS = {
    "official_parent",
    "openreview",
    "hotcrp",
    "researchr",
    "usenix",
    "acm",
    "ieee",
    "biomedical",
}

AREA_KEYWORDS = {
    "biomedical": (
        "biomedical", "bioinformatics", "clinical", "health", "medicine",
        "medical", "patient", "genomics", "omics", "healthcare",
    ),
    "ai_ml": (
        "machine learning", "deep learning", "artificial intelligence", "ai",
        "ml", "reinforcement learning", "rl", "foundation model",
        "language model", "agent", "generative",
    ),
    "security": (
        "security", "privacy", "cryptography", "vulnerability", "malware",
        "attack", "defense", "trustworthy", "safety",
    ),
    "distributed_systems": (
        "distributed", "cloud", "edge", "consensus", "replication",
        "fault tolerance", "serverless", "microservice",
    ),
    "networking": (
        "network", "internet", "wireless", "measurement", "routing",
        "mobile", "sensor", "protocol",
    ),
    "systems": (
        "systems", "operating system", "storage", "database", "runtime",
        "compiler", "architecture", "hpc", "performance",
    ),
    "software_engineering": (
        "software engineering", "program analysis", "testing", "debugging",
        "requirements", "developer", "maintenance", "verification",
    ),
    "theory": (
        "theory", "theoretical computer science", "algorithm", "complexity",
        "combinatorics", "graph", "geometry", "logic", "optimization",
    ),
    "databases": (
        "database", "databases", "data management", "query", "transaction",
        "indexing", "sql", "knowledge graph", "data systems",
    ),
    "programming_languages": (
        "programming language", "programming languages", "compiler", "type system",
        "static analysis", "semantics", "verification", "runtime", "synthesis",
    ),
}

DATE_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|"
    r"Dec(?:ember)?)\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*)?\d{4}\b",
    re.IGNORECASE,
)

NUMERIC_DATE_RE = re.compile(r"\b20\d{2}[-/]\d{1,2}[-/]\d{1,2}\b")

# Lenient "Month Day Year" — allows space-separated with no comma ("May 13 2026"),
# which is how OpenReview group date fields are written. normalize_date parses it.
MONTH_DAY_YEAR_RE = re.compile(
    r"\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"\d{1,2}(?:st|nd|rd|th)?,?\s+\d{4}\b",
    re.IGNORECASE,
)

# Hard cap on per-record date/url lists so repeated (stale-triggered) re-scrapes
# can't make a record grow without bound when a page's dates drift over time.
DATE_LIST_CAP = 24
URL_LIST_CAP = 12

DEADLINE_WORD_RE = re.compile(
    r"\b(?:submission|paper|abstract|deadline|due|camera-ready|camera ready|notification)\b",
    re.IGNORECASE,
)

# Date sub-patterns (no \b anchors so they can be embedded in a larger phrase).
_DATE_CORE = (
    r"(?:(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{1,2}(?:st|nd|rd|th)?(?:,\s*)?\d{4}|20\d{2}[-/]\d{1,2}[-/]\d{1,2})"
)

# High-precision submission deadline: a date that *immediately follows* an explicit
# submission-deadline label (e.g. "Paper submission deadline: June 15, 2026",
# "Abstract due by 2026-02-01"). Deliberately strict — dense CfP/news pages put
# submission words everywhere, so proximity matching produced false positives
# (e.g. a news-post date). We accept low recall to avoid showing a wrong date;
# when nothing matches, the labeled conference fallback stands instead.
SUBMISSION_PHRASE_RE = re.compile(
    # "...submission/paper/abstract ... deadline|due ..."  OR  "submission date ..."
    # (bare "date" alone is excluded — it matched event/workshop dates).
    r"(?:(?:paper|abstract|submission|manuscript)s?[^.\n]{0,40}?(?:deadline|due)"
    r"|submissions?\s+date)"
    r"\s*(?:\([^)]*\))?\s*[:\-–—]?\s*(?:is|by|on|before)?\s*(" + _DATE_CORE + r")",
    re.IGNORECASE,
)

EVENT_WORD_RE = re.compile(
    r"\b(?:workshop|event date|conference date|held on|takes place|program)\b",
    re.IGNORECASE,
)

OPENREVIEW_TITLE_RE = re.compile(
    r"\b(?P<venue>[A-Za-z0-9&.+ -]{2,40})\s+"
    r"(?P<year>20\d{2})\s+Workshop\s+"
    r"(?P<name>[A-Za-z0-9][A-Za-z0-9 .,&:/+_()'\\-]{1,120})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class VenueSeed:
    name: str
    area: str
    domains: tuple[str, ...]
    url: str = ""


TITLE_ALIASES = {
    "s&p": "IEEE S&P",
    "sp": "IEEE S&P",
    "ccs": "ACM CCS",
    "sigkdd": "KDD",
    "sigops atc": "USENIX ATC",
    "ieee/acm cgo": "CGO",
    "socg": "SoCG",
    "models": "MODELS",
    "mode ls": "MODELS",
    "ecml-pkdd": "ECML PKDD",
    "ecml pkdd": "ECML PKDD",
    "interspeech": "INTERSPEECH",
    "acm siggraph": "SIGGRAPH",
    "acm siggraph asia": "SIGGRAPH ASIA",
}

PL_VENUES = {
    "PLDI", "POPL", "OOPSLA", "SPLASH", "ICFP", "ECOOP", "CC", "VMCAI",
    "ESOP", "TACAS", "CAV", "LICS", "SAS", "SLE", "GPCE", "PEPM",
    "PADL", "Haskell Symposium", "ML Family Workshop", "Scheme Workshop",
    "Scala Symposium", "TyDe", "HOPE", "Onward!", "REBLS", "ISMM",
}


def canonical_title(title: str) -> str:
    title = re.sub(r"\s+", " ", str(title or "")).strip()
    if not title:
        return ""
    return TITLE_ALIASES.get(title.lower(), title)


def area_from_conference(row: dict, title: str) -> str:
    area = str(row.get("area") or "").strip()
    title = canonical_title(title)
    if title in PL_VENUES:
        return "programming_languages"
    if area == "software_engineering" and title in PL_VENUES:
        return "programming_languages"
    return area or classify_areas(" ".join(str(row.get(k, "")) for k in ("title", "description", "sub")), "ai_ml")[0]


def as_int(value, default: int | None = None) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def year_distance(row: dict) -> int:
    year = as_int(row.get("year"))
    if year is None:
        return 9999
    return abs(year - datetime.now(timezone.utc).year)


def source_config() -> dict:
    if not CONFERENCE_SOURCES_PATH.is_file():
        return {}
    try:
        return json.load(open(CONFERENCE_SOURCES_PATH))
    except (OSError, json.JSONDecodeError):
        return {}


def clone_repo(repo_url: str, dest: Path) -> None:
    subprocess.run(
        ["git", "clone", "--depth", "1", repo_url, str(dest)],
        check=True,
        capture_output=True,
    )


def parse_yaml(path: Path):
    if yaml is None:
        raise RuntimeError("pyyaml is required to fetch upstream conference sources")
    return yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or []


def parse_ccfddl_conferences(repo: Path, years: list[int]) -> list[dict]:
    rows = []
    conf_dir = repo / "conference"
    if not conf_dir.is_dir():
        return rows
    for cat_dir in sorted(conf_dir.iterdir()):
        if not cat_dir.is_dir():
            continue
        area_hint = CCFDDL_AREA_MAP.get(cat_dir.name, "")
        for yml in sorted(cat_dir.rglob("*.yml")):
            try:
                entry = parse_yaml(yml)
            except Exception as e:
                print(f"warn: ccfddl parse failed for {yml.name}: {e}", file=sys.stderr)
                continue
            if isinstance(entry, list):
                entry = entry[0] if entry else {}
            if not isinstance(entry, dict):
                continue
            title = canonical_title(entry.get("title", ""))
            if not title:
                continue
            rank = entry.get("rank") or {}
            base = {
                "title": title,
                "description": entry.get("description", ""),
                "sub": entry.get("sub", ""),
                "area": area_hint or classify_areas(" ".join(str(entry.get(k, "")) for k in ("title", "description", "sub")), "ai_ml")[0],
                "ccfddl_category": cat_dir.name,
                "ccf": rank.get("ccf"),
                "core": rank.get("core"),
                "dblp": entry.get("dblp", ""),
                "source": "ccfddl_upstream",
            }
            confs = entry.get("confs") or []
            selected = [conf for conf in confs if conf.get("year") in years]
            if not selected and confs:
                selected = [max(confs, key=lambda conf: int(conf.get("year") or 0))]
            if not selected:
                rows.append(base)
                continue
            for conf in selected:
                row = dict(base)
                row.update(
                    {
                        "year": conf.get("year"),
                        "link": conf.get("link"),
                        "timezone": conf.get("timezone"),
                        "date": conf.get("date"),
                        "place": conf.get("place"),
                    }
                )
                rows.append(row)
    return rows


def parse_ai_deadlines(repo: Path, years: list[int]) -> list[dict]:
    path = repo / "_data" / "conferences.yml"
    if not path.is_file():
        return []
    rows = []
    for entry in parse_yaml(path):
        if not isinstance(entry, dict):
            continue
        year = as_int(entry.get("year"))
        if year and year not in years:
            continue
        title = canonical_title(entry.get("title", ""))
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "description": strip_tags(entry.get("note") or ""),
                "sub": entry.get("sub", ""),
                "area": "ai_ml",
                "year": year,
                "link": entry.get("link"),
                "date": entry.get("date"),
                "place": entry.get("place"),
                "source": "ai_deadlines_upstream",
            }
        )
    return rows


def parse_sec_deadlines(repo: Path, years: list[int]) -> list[dict]:
    path = repo / "_data" / "conferences.yml"
    if not path.is_file():
        return []
    rows = []
    for entry in parse_yaml(path):
        if not isinstance(entry, dict):
            continue
        year = as_int(entry.get("year"))
        if year and year not in years:
            continue
        title = canonical_title(entry.get("name", ""))
        if not title:
            continue
        rows.append(
            {
                "title": title,
                "description": strip_tags(entry.get("description") or entry.get("comment") or ""),
                "sub": "",
                "area": "security",
                "year": year,
                "link": entry.get("link"),
                "date": entry.get("date"),
                "place": entry.get("place"),
                "source": "sec_deadlines_upstream",
            }
        )
    return rows


def parse_tcs_conf(repo: Path, years: list[int]) -> list[dict]:
    path = repo / "index.html"
    if not path.is_file():
        return []
    doc = path.read_text(encoding="utf-8", errors="replace")
    rows = []
    row_re = re.compile(r"<tr>(.*?)</tr>", re.S)
    name_re = re.compile(r'class="confname"><a href="([^"]*)"[^>]*>([^<]+)</a>', re.S)
    for match in row_re.finditer(doc):
        block = match.group(1)
        name_match = name_re.search(block)
        if not name_match:
            continue
        link, title = name_match.group(1).strip(), canonical_title(name_match.group(2))
        year_match = re.search(r"\b(20\d{2})\b", block)
        year = int(year_match.group(1)) if year_match else None
        if year and year not in years:
            continue
        rows.append(
            {
                "title": title,
                "description": strip_tags(block),
                "sub": "",
                "area": "theory",
                "year": year,
                "link": link,
                "source": "tcs_conf_upstream",
            }
        )
    return rows


def fetch_upstream_conference_rows(years: list[int]) -> list[dict]:
    config = source_config()
    if config.get("fetch_upstream_sources") is False:
        return []
    if yaml is None:
        print("warn: pyyaml missing; skipping upstream conference sources", file=sys.stderr)
        return []
    repo_urls = dict(UPSTREAM_CONFERENCE_REPOS)
    repo_urls.update(config.get("upstream_git_sources") or {})
    parsers = {
        "ccfddl": parse_ccfddl_conferences,
        "ai_deadlines": parse_ai_deadlines,
        "sec_deadlines": parse_sec_deadlines,
        "tcs_conf": parse_tcs_conf,
    }
    rows = []
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for name, repo_url in repo_urls.items():
            parser = parsers.get(name)
            if not parser:
                continue
            repo = tmp_path / name
            try:
                clone_repo(repo_url, repo)
                rows.extend(parser(repo, years))
            except Exception as e:
                print(f"warn: upstream conference source {name} failed: {e}", file=sys.stderr)
    return rows


def current_and_next_year(now: datetime | None = None) -> list[int]:
    now = now or datetime.now(timezone.utc)
    return [now.year, now.year + 1]


def load_seeds() -> list[VenueSeed]:
    docs = []
    for path in (SEEDS_PATH, WATCHLIST_PATH):
        if path.is_file():
            with open(path) as f:
                docs.append(json.load(f))
    seeds = []
    seen = set()
    for doc in docs:
        for area, venues in doc.get("areas", {}).items():
            for item in venues or []:
                if isinstance(item, str):
                    seed = VenueSeed(item, area, ())
                else:
                    seed = VenueSeed(
                        str(item["name"]),
                        area,
                        tuple(item.get("domains") or ()),
                        str(item.get("url") or ""),
                    )
                key = (seed.name.lower(), seed.area)
                if key in seen:
                    continue
                seen.add(key)
                seeds.append(seed)
    for seed in load_conference_source_seeds():
        key = (seed.name.lower(), seed.area)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(seed)
    return seeds


def configured_conference_sources() -> list[Path]:
    paths = []
    doc = source_config()
    for value in doc.get("local_conference_json", []):
        path = Path(value).expanduser()
        if not path.is_absolute():
            path = ROOT / path
        paths.append(path)
    paths.extend(
        [
            ROOT.parent / "paper_tracker" / "data" / "conferences.json",
            ROOT.parent / "paper-tracker" / "data" / "conferences.json",
            Path("/Users/madhavagaikwad/Documents/New project/paper-tracker/data/conferences.json"),
        ]
    )
    return dedupe_paths(paths)


def dedupe_paths(paths: Iterable[Path]) -> list[Path]:
    seen = set()
    out = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        seen.add(key)
        out.append(path)
    return out


_CONFERENCE_ROWS_CACHE: list[dict] | None = None


def conference_source_rows() -> list[dict]:
    """Load and cache conference rows from local JSON sources + upstream feeds.

    Each row carries per-(venue, year) structured data: ``place`` (physical
    location), ``date`` (event-date text), and either a ``timeline`` (ccfddl) or
    flat ``deadline``/``abstract_deadline`` fields. Cached because both the seed
    builder and the metadata builder iterate the same rows, and the upstream
    fetch makes network calls we don't want to repeat.
    """
    global _CONFERENCE_ROWS_CACHE
    if _CONFERENCE_ROWS_CACHE is not None:
        return _CONFERENCE_ROWS_CACHE
    rows_from_sources: list[dict] = []
    for path in configured_conference_sources():
        if not path.is_file():
            continue
        try:
            payload = json.load(open(path))
        except (OSError, json.JSONDecodeError) as e:
            print(f"warn: cannot read conference source {path}: {e}", file=sys.stderr)
            continue
        rows = payload.get("conferences", payload if isinstance(payload, list) else [])
        rows_from_sources.extend(row for row in rows if isinstance(row, dict))
    rows_from_sources.extend(fetch_upstream_conference_rows(current_and_next_year()))
    _CONFERENCE_ROWS_CACHE = sorted(rows_from_sources, key=year_distance)
    return _CONFERENCE_ROWS_CACHE


def conference_row_deadline(row: dict) -> tuple[str, str]:
    """Return (submission_deadline_iso, abstract_deadline_iso) for a conference row.

    Handles both the ccfddl shape (a ``timeline`` list of rounds) and the flat
    ai-deadlines / sec-deadlines shape (top-level ``deadline``/``abstract_deadline``).
    """
    deadline = ""
    abstract = ""
    timeline = row.get("timeline")
    if isinstance(timeline, list) and timeline:
        first = timeline[0] if isinstance(timeline[0], dict) else {}
        deadline = normalize_date(str(first.get("deadline") or "").split(" ")[0])
        abstract = normalize_date(str(first.get("abstract_deadline") or "").split(" ")[0])
    if not deadline and row.get("deadline"):
        deadline = normalize_date(str(row.get("deadline")).split(" ")[0])
    if not abstract and row.get("abstract_deadline"):
        abstract = normalize_date(str(row.get("abstract_deadline")).split(" ")[0])
    return deadline, abstract


def load_conference_meta() -> dict[tuple[str, int], dict]:
    """Build a {(venue_lower, year): {place, date_text, event_date_iso,
    deadline, abstract_deadline}} lookup from conference source rows.

    Rows are sorted nearest-year-first, so the first entry per (venue, year)
    wins. This is what lets a workshop inherit its parent conference's physical
    location and event dates (mirrors paper_tracker's structured data).
    """
    meta: dict[tuple[str, int], dict] = {}
    for row in conference_source_rows():
        title = canonical_title(row.get("title", ""))
        year = row.get("year")
        if not title or not isinstance(year, int):
            continue
        key = (title.lower(), year)
        if key in meta:
            continue
        date_text = str(row.get("date") or "").strip()
        deadline, abstract = conference_row_deadline(row)
        meta[key] = {
            "place": str(row.get("place") or "").strip(),
            "date_text": date_text,
            "event_date_iso": parse_conference_dates(date_text, year),
            "deadline": deadline,
            "abstract_deadline": abstract,
        }
    return meta


def load_conference_source_seeds() -> list[VenueSeed]:
    seeds: list[VenueSeed] = []
    seen = set()
    for row in conference_source_rows():
        title = canonical_title(row.get("title", ""))
        if not title:
            continue
        area = area_from_conference(row, title)
        if not area:
            continue
        link = str(row.get("link") or "")
        host = urlparse(link).netloc.lower().removeprefix("www.")
        domains = (host,) if host else ()
        key = (title.lower(), area)
        if key in seen:
            continue
        seen.add(key)
        seeds.append(VenueSeed(title, area, domains, link))
    return seeds


def urlopen_text(url: str, timeout: int = 25) -> str:
    request = Request(url, headers={"User-Agent": "Mozilla/5.0 workshop-tracker"})
    context = None
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        return response.read().decode("utf-8", "ignore")


def urlopen_json(url: str, timeout: int = 25) -> dict:
    return json.loads(urlopen_text(url, timeout=timeout))


def strip_tags(value: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html.unescape(value))).strip()


def content_value(content: dict, key: str, default=None):
    value = (content or {}).get(key, {})
    if isinstance(value, dict) and "value" in value:
        return value["value"]
    return default


def date_from_millis(value) -> str:
    if not value:
        return ""
    try:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc).date().isoformat()
    except (TypeError, ValueError, OSError):
        return ""


def openreview_group_id(url: str) -> str:
    parsed = urlparse(url)
    if "openreview.net" not in parsed.netloc:
        return ""
    return parse_qs(parsed.query).get("id", [""])[0]


def record_source_key(record: dict) -> str:
    return (
        record.get("openreview_url")
        or next((u for u in record.get("source_urls", []) if "openreview.net" in u), "")
        or record.get("website_url", "")
    )


def carry_forward_existing_metadata(records: list[dict]) -> None:
    if not OUT_PATH.is_file():
        return
    try:
        existing = json.load(open(OUT_PATH))
    except (OSError, json.JSONDecodeError):
        return
    by_source = {
        record_source_key(record): record
        for record in existing.get("workshops", [])
        if record_source_key(record)
    }
    # Carry forward page/OpenReview-derived enrichment so we don't re-scrape it.
    enriched_fields = (
        "official_url", "openreview_url", "location", "workshop_date",
        "submission_deadline", "deadline_source", "deadline_dates", "dates_found",
        "venue_correction", "official_venue_checked", "official_checked_at",
        "openreview_checked_at", "theme", "theme_source",
    )
    for record in records:
        old = by_source.get(record_source_key(record))
        if not old:
            continue
        # Conference-baseline values are recomputed every run by
        # apply_conference_baseline; carrying them forward would (a) go stale and
        # (b) re-trip the "already have a deadline" gate and block re-scraping.
        # So drop them from the old record before copying scraped values over.
        old = dict(old)
        if old.get("deadline_is_conference_fallback") or old.get("deadline_source") == "conference":
            old.pop("submission_deadline", None)
            old.pop("deadline_source", None)
        if old.get("location_source") == "conference":
            old.pop("location", None)
        if old.get("date_source") == "conference":
            old.pop("workshop_date", None)
        for field in enriched_fields:
            if old.get(field) and not record.get(field):
                record[field] = old[field]
        correction = record.get("venue_correction")
        if isinstance(correction, dict) and correction.get("to"):
            record["parent_venue"] = correction["to"]
            record["acronym"] = correction["to"]


def discover_openreview_homepage(seeds: list[VenueSeed], years: list[int]) -> list[dict]:
    """Parse OpenReview's public venue list, which contains many workshop calls."""
    try:
        doc = urlopen_text("https://openreview.net/")
    except Exception as e:
        print(f"warn: OpenReview homepage fetch failed: {e}", file=sys.stderr)
        return []

    seed_by_name = {seed.name.lower(): seed for seed in seeds}
    seed_names = sorted(seed_by_name, key=len, reverse=True)
    records = []

    for anchor in re.finditer(r'<a[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<body>.*?)</a>', doc, re.I | re.S):
        title = strip_tags(anchor.group("body"))
        if "workshop" not in title.lower():
            continue
        match = OPENREVIEW_TITLE_RE.search(title)
        if not match:
            continue
        year = int(match.group("year"))
        if year not in years:
            continue
        title_l = title.lower()
        seed = next((seed_by_name[name] for name in seed_names if title_l.startswith(name)), None)
        if not seed:
            continue
        url = urljoin("https://openreview.net/", html.unescape(anchor.group("href")))
        result = {
            "title": title,
            "url": url,
            "snippet": title,
            "query": "openreview_homepage",
        }
        records.append(candidate_from_result(seed, year, result))

    return records


def seed_page_url(seed: VenueSeed) -> str:
    if seed.url:
        return seed.url
    if seed.domains:
        domain = seed.domains[0]
        if domain.startswith("http://") or domain.startswith("https://"):
            return domain
        return f"https://{domain}"
    return ""


def discover_official_seed_pages(
    seeds: list[VenueSeed],
    years: list[int],
    limit: int,
    delay_seconds: float,
) -> list[dict]:
    records = []
    fetched = 0
    failures = 0
    priority_areas = {
        "distributed_systems", "networking", "systems", "software_engineering",
        "security", "databases", "programming_languages", "theory", "biomedical",
    }
    candidates = [
        seed for seed in seeds
        if seed.area in priority_areas and seed_page_url(seed) and "dblp.org" not in seed_page_url(seed)
    ]
    for seed in candidates:
        if limit <= 0 or fetched >= limit or failures >= 30:
            break
        url = seed_page_url(seed)
        try:
            doc = urlopen_text(url, timeout=12)
        except Exception as e:
            failures += 1
            print(f"warn: official seed page fetch failed for {seed.name} {url}: {e}", file=sys.stderr)
            continue
        fetched += 1
        page_text = strip_tags(doc)
        for anchor in re.finditer(r'<a[^>]+href=["\'](?P<href>[^"\']+)["\'][^>]*>(?P<body>.*?)</a>', doc, re.I | re.S):
            title = strip_tags(anchor.group("body"))
            href = html.unescape(anchor.group("href"))
            full_url = urljoin(url, href)
            haystack = f"{title} {full_url}".lower()
            if "workshop" not in haystack and "cfp" not in haystack and "call-for" not in haystack:
                continue
            if any(skip in haystack for skip in ("sponsorship", "volunteer", "registration", "hotel")):
                continue
            matched_year = next((year for year in years if str(year) in haystack or str(year) in page_text), years[0])
            result = {
                "title": title or f"{seed.name} {matched_year} workshops",
                "url": full_url,
                "snippet": title or f"Workshop link found on {url}",
                "query": f"official_seed_page:{url}",
            }
            records.append(candidate_from_result(seed, matched_year, result))
        if delay_seconds > 0 and fetched < limit:
            time.sleep(delay_seconds)
    return records


def openreview_group_payload(group_id: str, attempts: int = 4) -> dict:
    """Fetch an OpenReview group, backing off and retrying only when throttled.

    OpenReview rate-limits bursts (429/503). Rather than slowing every call, we
    sleep-and-retry just the throttled ones (4s, 8s, 12s)."""
    api_url = "https://api2.openreview.net/groups?" + urlencode({"id": group_id})
    for attempt in range(attempts):
        try:
            return urlopen_json(api_url, timeout=8)
        except Exception as e:
            if getattr(e, "code", None) in (429, 503) and attempt < attempts - 1:
                time.sleep(4 * (attempt + 1))
                continue
            raise


def enrich_openreview_records(records: list[dict], limit: int, delay_seconds: float) -> None:
    """Add OpenReview group metadata: official website, location, and dates."""
    enriched = 0
    failures = 0
    for record in records:
        if limit <= 0 or enriched >= limit or failures >= 20:
            return
        if record.get("source_kind") != "openreview":
            continue
        # Skip if we already have a real deadline, or checked this group recently —
        # so a rate-limited run doesn't keep re-fetching the same groups and never
        # reach the un-checked tail.
        has_real = record.get("deadline_source") in ("openreview", "official_page", "llm")
        if has_real and record.get("location") and record.get("workshop_date"):
            continue
        if days_since_iso(record.get("openreview_checked_at")) < OFFICIAL_PAGE_STALE_DAYS:
            continue
        group_id = openreview_group_id(record.get("website_url", ""))
        if not group_id:
            continue
        try:
            payload = openreview_group_payload(group_id)
        except Exception as e:
            code = getattr(e, "code", None)
            if code in (400, 404):
                # Group doesn't exist — mark checked so we don't retry it.
                record["openreview_checked_at"] = datetime.now(timezone.utc).isoformat()
            elif code not in (429, 503):
                # A real error counts toward the bail. Persistent throttling (429/503)
                # does not: leave the record unchecked so the next run retries it.
                failures += 1
            print(f"warn: OpenReview group fetch failed for {group_id}: {e}", file=sys.stderr)
            continue
        record["openreview_checked_at"] = datetime.now(timezone.utc).isoformat()
        groups = payload.get("groups") or []
        if not groups:
            continue
        content = groups[0].get("content") or {}
        official_title = content_value(content, "title", "")
        official_url = content_value(content, "website", "")
        location = content_value(content, "location", "")
        start_date = date_from_millis(content_value(content, "start_date", ""))
        # OpenReview groups often state the real workshop deadline in their free-text
        # "date" field (e.g. "Submission Deadline: May 13 2026 01:59PM UTC-0"). This
        # is the actual workshop deadline, not the parent conference's, so it beats
        # the conference fallback. We don't need to scrape a page for it.
        or_date_text = str(content_value(content, "date", "") or "")
        or_deadline = ""
        if or_date_text:
            match = MONTH_DAY_YEAR_RE.search(or_date_text) or NUMERIC_DATE_RE.search(or_date_text)
            if match:
                parsed = normalize_date(match.group(0), default_year=int(record.get("year") or 0))
                if parsed and re.search(r"submission|deadline|due", or_date_text, re.I):
                    or_deadline = parsed

        record["openreview_url"] = record["website_url"]
        if official_title:
            record["title"] = str(official_title).strip()
        if official_url:
            record["official_url"] = str(official_url).strip()
            record["website_url"] = record["official_url"]
        if location:
            record["location"] = str(location).strip()
        if or_deadline:
            record["submission_deadline"] = or_deadline
            record["deadline_is_conference_fallback"] = False
            record["deadline_source"] = "openreview"
            record["dates_found"] = dedupe_keep_order(
                record.get("dates_found", []) + [or_deadline]
            )[:DATE_LIST_CAP]
        if start_date:
            record["workshop_date"] = start_date
            record["date_source"] = record.get("date_source") or "openreview"
            record["dates_found"] = dedupe_keep_order(
                record.get("dates_found", []) + [start_date]
            )[:DATE_LIST_CAP]
        record["source_urls"] = dedupe_keep_order(
            record.get("source_urls", []) + [record.get("openreview_url", "")]
        )[:URL_LIST_CAP]
        enriched += 1
        if delay_seconds > 0 and enriched < limit:
            time.sleep(delay_seconds)


def normalize_date(value: str, default_year: int | None = None) -> str:
    raw = re.sub(r"\s+", " ", value or "").strip().replace("/", "-")
    if not raw:
        return ""
    try:
        parsed = datetime.strptime(raw, "%Y-%m-%d")
        return parsed.date().isoformat()
    except ValueError:
        pass
    cleaned = re.sub(r"(\d{1,2})(st|nd|rd|th)", r"\1", raw, flags=re.I)
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%B %d %Y", "%b %d %Y"):
        try:
            return datetime.strptime(cleaned, fmt).date().isoformat()
        except ValueError:
            continue
    if default_year and not re.search(r"\b20\d{2}\b", cleaned):
        for fmt in ("%B %d", "%b %d"):
            try:
                parsed = datetime.strptime(cleaned, fmt)
                return parsed.replace(year=default_year).date().isoformat()
            except ValueError:
                continue
    return ""


CONF_RANGE_RE = re.compile(
    r"(?P<month>Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\.?\s+(?P<day>\d{1,2})",
    re.IGNORECASE,
)


def parse_conference_dates(text: str, year: int | None = None) -> str:
    """Return the ISO date of the first day of a conference date string.

    Handles the human ranges paper_tracker stores, e.g. "October 6-9, 2026",
    "Feb 22 - Mar 1, 2022", "October 7-9, 2024", as well as single dates and
    ISO strings. Returns "" when nothing parseable is found (never raises).
    """
    raw = (text or "").strip()
    if not raw:
        return ""
    direct = normalize_date(raw, default_year=year)
    if direct:
        return direct
    year_match = re.search(r"\b(20\d{2})\b", raw)
    parsed_year = int(year_match.group(1)) if year_match else year
    first = CONF_RANGE_RE.search(raw)
    if first and parsed_year:
        candidate = f"{first.group('month')} {first.group('day')}, {parsed_year}"
        return normalize_date(candidate)
    return ""


def date_candidates(text: str, year: int) -> list[tuple[str, int]]:
    out: list[tuple[str, int]] = []
    for regex in (DATE_RE, NUMERIC_DATE_RE):
        for match in regex.finditer(text):
            date = normalize_date(match.group(0), default_year=year)
            if date:
                out.append((date, match.start()))
    return out


def nearest_keyword(text: str, pos: int, regex: re.Pattern) -> bool:
    window = text[max(0, pos - 180): pos + 180]
    return bool(regex.search(window))


def keyword_distance(text: str, pos: int, regex: re.Pattern, window: int = 180) -> int | float:
    """Distance in characters from `pos` to the nearest match of `regex`.

    Returns inf when no match falls within `window` characters. Used to pick the
    label closest to a date in dense "Important Dates" lists, where a fixed
    window would otherwise see every label near every date.
    """
    lo = max(0, pos - window)
    best: float = float("inf")
    for match in regex.finditer(text[lo: pos + window]):
        start = lo + match.start()
        best = min(best, abs(start - pos))
    return best


def extract_submission_dates(stripped: str, year: int) -> list[str]:
    """High-precision: only dates that directly follow a submission-deadline label."""
    out = []
    for match in SUBMISSION_PHRASE_RE.finditer(stripped):
        date = normalize_date(match.group(1), default_year=year)
        if date:
            out.append(date)
    return dedupe_keep_order(out)


# Anchors for LLM context windows: month names, ISO dates, or bare 4-digit years.
DATE_ANCHOR_RE = re.compile(
    r"(?:\b(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\b"
    r"|20\d{2}[-/]\d{1,2}[-/]\d{1,2}|\b20\d{2}\b)",
    re.IGNORECASE,
)


def deadline_context_snippets(stripped: str, window: int = 90, cap: int = 25) -> list[str]:
    """Short text windows around every date-like anchor, for the LLM to judge.

    Sends only the neighbourhoods of dates (not the whole page) so the call stays
    cheap, while covering date formats the strict submission regex doesn't catch
    (e.g. "5 March 2026")."""
    snippets = []
    for match in DATE_ANCHOR_RE.finditer(stripped):
        lo = max(0, match.start() - window)
        snippet = stripped[lo: match.end() + window].strip()
        if snippet:
            snippets.append(re.sub(r"\s+", " ", snippet))
    return dedupe_keep_order(snippets)[:cap]


def extract_official_page_dates(text: str, year: int) -> dict:
    stripped = strip_tags(text)
    deadlines = []
    events = []
    all_dates = []
    for date, pos in date_candidates(stripped, year):
        all_dates.append(date)
        # Broad "deadline-ish" and "event-ish" buckets are kept only as raw signal
        # surfaced in the UI for humans to verify — never as the authoritative date.
        if nearest_keyword(stripped, pos, DEADLINE_WORD_RE):
            deadlines.append(date)
        if nearest_keyword(stripped, pos, EVENT_WORD_RE):
            events.append(date)
    return {
        "deadline_dates": dedupe_keep_order(deadlines)[:DATE_LIST_CAP],
        "submission_dates": extract_submission_dates(stripped, year),
        "event_dates": dedupe_keep_order(events)[:DATE_LIST_CAP],
        "dates_found": dedupe_keep_order(all_dates)[:DATE_LIST_CAP],
    }


def days_since_iso(value: str, now: datetime | None = None) -> float:
    """Whole/fractional days since an ISO timestamp; inf when missing/unparseable."""
    if not value:
        return float("inf")
    try:
        ts = datetime.fromisoformat(str(value))
    except ValueError:
        return float("inf")
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return ((now or datetime.now(timezone.utc)) - ts).total_seconds() / 86400


# Re-validate an already-scraped page after this many days so that conferences
# adding / removing / re-dating workshops are eventually picked up.
OFFICIAL_PAGE_STALE_DAYS = 7


def should_fetch_official_page(record: dict, stale_days: float = OFFICIAL_PAGE_STALE_DAYS) -> bool:
    if record.get("source_kind") == "source_gap":
        return False
    url = record.get("official_url") or record.get("website_url") or ""
    if not url:
        return False
    host = urlparse(url).netloc.lower()
    if not host or "openreview.net" in host or "dblp.org" in host:
        return False
    # Never scraped yet -> fetch.
    if not record.get("official_venue_checked"):
        return True
    # Only have the conference fallback, not a real workshop deadline -> keep trying.
    has_real_deadline = bool(record.get("submission_deadline")) and not record.get(
        "deadline_is_conference_fallback"
    )
    if not has_real_deadline:
        return True
    # Otherwise re-check only once the last scrape has gone stale (bounded churn).
    return days_since_iso(record.get("official_checked_at"), None) >= stale_days


def page_venue_scores(html_doc: str, seeds: list[VenueSeed]) -> dict[str, int]:
    title_match = re.search(r"<title[^>]*>(.*?)</title>", html_doc, re.I | re.S)
    title_text = strip_tags(title_match.group(1)) if title_match else ""
    meta_text = " ".join(
        html.unescape(m.group(1))
        for m in re.finditer(r'<meta[^>]+content=["\']([^"\']+)["\']', html_doc[:6000], re.I | re.S)
    )
    lead_text = strip_tags(html_doc[:7000])
    scores: dict[str, int] = {}
    for seed in seeds:
        name = seed.name
        if len(name) < 2:
            continue
        pattern = re.compile(rf"(?<![A-Za-z0-9]){re.escape(name)}(?![A-Za-z0-9])", re.I)
        score = 0
        if pattern.search(title_text):
            score += 8
        if pattern.search(meta_text):
            score += 5
        if pattern.search(lead_text):
            score += 2
        if score:
            scores[name] = max(scores.get(name, 0), score)
    return scores


def maybe_correct_parent_venue(record: dict, html_doc: str, seeds: list[VenueSeed]) -> None:
    scores = page_venue_scores(html_doc, seeds)
    if not scores:
        return
    current = record.get("parent_venue", "")
    current_score = scores.get(current, 0)
    best, best_score = max(scores.items(), key=lambda item: item[1])
    if best == current or best_score < 5 or best_score < current_score + 3:
        return
    seed = next((s for s in seeds if s.name == best), None)
    old = current
    record["parent_venue"] = best
    record["acronym"] = best
    if seed:
        record["areas"] = dedupe_keep_order([seed.area] + record.get("areas", []))
    record["venue_correction"] = {
        "from": old,
        "to": best,
        "reason": "official_page_title_or_meta",
    }


def enrich_official_page_dates(
    records: list[dict],
    seeds: list[VenueSeed],
    limit: int,
    delay_seconds: float,
    llm_limit: int = 0,
) -> None:
    enriched = 0
    failures = 0
    llm_used = 0
    for record in records:
        if limit <= 0 or enriched >= limit or failures >= 20:
            return
        if not should_fetch_official_page(record):
            continue
        url = record.get("official_url") or record.get("website_url")
        try:
            doc = urlopen_text(url, timeout=12)
        except Exception as e:
            failures += 1
            print(f"warn: official page fetch failed for {url}: {e}", file=sys.stderr)
            continue
        maybe_correct_parent_venue(record, doc, seeds)
        record["official_venue_checked"] = True
        record["official_checked_at"] = datetime.now(timezone.utc).isoformat()
        found = extract_official_page_dates(doc, int(record.get("year") or 0))
        # A high-precision submission date (label immediately followed by a date) is
        # authoritative: it replaces anything prior and is marked as page-sourced.
        # We deliberately do NOT promote a broad "deadline-ish" date to the headline
        # deadline — that produced wrong dates on dense CfP/news pages.
        if found["submission_dates"]:
            record["submission_deadline"] = min(found["submission_dates"])
            record["deadline_is_conference_fallback"] = False
            record["deadline_source"] = "official_page"
        elif record.get("deadline_source") not in ("official_page", "llm"):
            # No precise regex date -> this is exactly the low-confidence subset the
            # LLM second pass is for. We only spend a (free-tier) call when it can
            # plausibly pay off: budget left, an LLM configured, the record is an
            # actionable real workshop (not junk/gap), and the page actually has
            # date anchors. Otherwise drop any prior heuristic/stale value so the
            # labeled conference fallback fills in. Page/LLM deadlines are preserved.
            llm_date = None
            actionable = (record.get("safety") or {}).get("actionable", True)
            if llm_used < llm_limit and actionable and llm_extract.llm_enabled():
                snippets = deadline_context_snippets(strip_tags(doc))
                if snippets:
                    llm_date = llm_extract.extract_deadline(
                        record.get("title", ""), int(record.get("year") or 0), snippets
                    )
                    llm_used += 1
            if llm_date:
                record["submission_deadline"] = llm_date
                record["deadline_is_conference_fallback"] = False
                record["deadline_source"] = "llm"
            else:
                record["submission_deadline"] = ""
                record["deadline_is_conference_fallback"] = False
        if found["deadline_dates"]:
            record["deadline_dates"] = dedupe_keep_order(
                record.get("deadline_dates", []) + found["deadline_dates"]
            )[:DATE_LIST_CAP]
        if found["event_dates"] and not record.get("workshop_date"):
            record["workshop_date"] = found["event_dates"][0]
            record["date_source"] = "official_page"
        if found["dates_found"]:
            record["dates_found"] = dedupe_keep_order(
                record.get("dates_found", []) + found["dates_found"]
            )[:DATE_LIST_CAP]
        if found["deadline_dates"] or found["event_dates"] or found["dates_found"]:
            record["date_source_url"] = url
        enriched += 1
        if delay_seconds > 0 and enriched < limit:
            time.sleep(delay_seconds)


def source_kind(url: str, seed: VenueSeed | None = None) -> str:
    host = urlparse(url).netloc.lower()
    if seed and any(urlparse(domain).netloc.lower() in host if domain.startswith(("http://", "https://")) else domain.lower() in host for domain in seed.domains):
        return "official_parent"
    for kind, domains in SOURCE_LOCATIONS.items():
        if any(domain in host for domain in domains):
            return kind
    return "official_or_other"


def classify_areas(text: str, fallback: str) -> list[str]:
    lowered = text.lower()
    scores = []
    for area, keywords in AREA_KEYWORDS.items():
        score = sum(1 for kw in keywords if kw in lowered)
        if score:
            scores.append((score, area))
    if not scores:
        return [fallback]
    scores.sort(reverse=True)
    return [area for _, area in scores[:3]]


def infer_status(text: str, year: int) -> str:
    lowered = text.lower()
    if "accepted workshop" in lowered or "accepted workshops" in lowered:
        return "confirmed"
    if "call for papers" in lowered or "cfp" in lowered or "submissions are open" in lowered:
        return "cfp_open"
    if "call for workshop" in lowered or "workshop proposal" in lowered:
        return "proposal_open"
    if str(year) in lowered and "workshop" in lowered:
        return "candidate"
    return "expected"


def confidence_for(kind: str, status: str) -> str:
    if status in {"confirmed", "cfp_open"} and kind in {
        "official_parent", "openreview", "hotcrp", "researchr", "usenix", "acm", "ieee", "biomedical",
    }:
        return "high"
    if kind in {"openreview", "hotcrp", "researchr", "usenix", "acm", "ieee", "biomedical"}:
        return "medium"
    if kind in {"wikicfp", "dblp"}:
        return "medium" if status != "expected" else "low"
    return "low"


def safety_assessment(record: dict, text: str, year: int) -> dict:
    checks = {
        "has_year_signal": str(year) in text,
        "has_workshop_signal": "workshop" in text.lower(),
        "trusted_source": record["source_kind"] in TRUSTED_SOURCE_KINDS,
        "actionable_status": record["status"] in {"confirmed", "cfp_open", "proposal_open"},
        "non_generated": record["source_kind"] != "source_gap",
    }
    score = sum(1 for ok in checks.values() if ok)
    actionable = (
        checks["non_generated"]
        and checks["has_year_signal"]
        and checks["has_workshop_signal"]
        and record["confidence"] in {"high", "medium"}
        and record["status"] != "expected"
    )
    return {
        "actionable": actionable,
        "score": score,
        "checks": checks,
        "note": (
            "Use as a lead; verify deadlines on the linked source before submitting."
            if actionable
            else "Discovery lead only; needs source confirmation before acting."
        ),
    }


def extract_dates(text: str) -> list[str]:
    return dedupe_keep_order(m.group(0) for m in DATE_RE.finditer(text))


def title_from_result(seed: VenueSeed, year: int, result: dict) -> str:
    title = result.get("title") or ""
    title = re.sub(r"\s+", " ", title).strip(" -|")
    if title:
        return title[:180]
    return f"{seed.name} {year} workshop candidate"


def candidate_from_result(seed: VenueSeed, year: int, result: dict) -> dict:
    text = " ".join([result.get("title", ""), result.get("snippet", ""), result.get("url", "")])
    kind = source_kind(result["url"], seed)
    status = infer_status(text, year)
    record = {
        "title": title_from_result(seed, year, result),
        "acronym": seed.name,
        "year": year,
        "parent_venue": seed.name,
        "areas": classify_areas(text, seed.area),
        "website_url": result["url"],
        "official_url": "",
        "openreview_url": result["url"] if kind == "openreview" else "",
        "location": "",
        "workshop_date": "",
        "submission_deadline": "",
        "deadline_dates": [],
        "cfp_url": result["url"] if "call" in text.lower() or "cfp" in text.lower() else "",
        "submission_url": result["url"] if kind in {"openreview", "hotcrp"} else "",
        "dates_found": extract_dates(text),
        "status": status,
        "confidence": confidence_for(kind, status),
        "source_kind": kind,
        "source_urls": [result["url"]],
        "discovered_by": result.get("query", "seed"),
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "evidence": (result.get("snippet") or "")[:500],
    }
    record["safety"] = safety_assessment(record, text, year)
    return record


def expected_record(seed: VenueSeed, year: int) -> dict:
    status = "candidate" if year == datetime.now(timezone.utc).year else "expected"
    official_url = (
        seed.url
        if seed.url
        else f"https://{seed.domains[0]}"
        if seed.domains
        else "https://dblp.org/search?" + urlencode({"q": f"{seed.name} {year} workshops"})
    )
    record = {
        "title": f"{seed.name} {year} workshops",
        "acronym": seed.name,
        "year": year,
        "parent_venue": seed.name,
        "areas": [seed.area],
        "website_url": official_url,
        "official_url": official_url,
        "openreview_url": "",
        "location": "",
        "workshop_date": "",
        "submission_deadline": "",
        "deadline_dates": [],
        "cfp_url": "",
        "submission_url": "",
        "dates_found": [],
        "status": status,
        "confidence": "low",
        "source_kind": "source_gap",
        "source_urls": [],
        "discovered_by": "seed_gap",
        "last_checked": datetime.now(timezone.utc).isoformat(),
        "evidence": (
            f"Tracking {seed.name} {year} because this venue often hosts workshops in "
            f"{seed.area.replace('_', ' ')}. No parser has confirmed a workshop page yet; "
            "use this as a reminder to check the venue site."
        ),
        "source_targets": {
            "openreview": "https://openreview.net/",
            "official_domains": list(seed.domains),
        },
    }
    record["safety"] = {
        "actionable": False,
        "score": 1,
        "checks": {
            "has_year_signal": True,
            "has_workshop_signal": True,
            "trusted_source": False,
            "actionable_status": False,
            "non_generated": False,
        },
        "note": "Tracked venue target; no confirmed workshop page has been parsed yet.",
    }
    return record


def apply_conference_baseline(
    records: list[dict], conf_meta: dict[tuple[str, int], dict]
) -> None:
    """Inherit the parent conference's structured location and event dates onto
    each workshop.

    Runs after OpenReview/official-page enrichment, so any value scraped for the
    workshop itself is already present and wins ("page overrides"); the
    conference data only fills the gaps. Reference fields (conference_deadline,
    conference_dates_text, ...) are always attached. This mirrors how
    paper_tracker surfaces place/date straight from structured sources.
    """
    for record in records:
        venue = str(record.get("parent_venue") or "").lower()
        year = record.get("year")
        meta = conf_meta.get((venue, year))
        if not meta:
            continue
        if not record.get("location") and meta["place"]:
            record["location"] = meta["place"]
            record["location_source"] = "conference"
        if not record.get("workshop_date") and meta["event_date_iso"]:
            record["workshop_date"] = meta["event_date_iso"]
            record["date_source"] = record.get("date_source") or "conference"
        if meta["date_text"]:
            record["conference_dates_text"] = meta["date_text"]
        if meta["deadline"]:
            record["conference_deadline"] = meta["deadline"]
        if meta["abstract_deadline"]:
            record["conference_abstract_deadline"] = meta["abstract_deadline"]
        # Labeled fallback: when we have no confident workshop deadline, borrow the
        # main conference's (clearly marked "workshop TBD"). Raw scraped date
        # candidates are too unreliable to count as a real deadline, so the only
        # thing that blocks this is an actual submission_deadline value.
        if not record.get("submission_deadline") and meta["deadline"]:
            record["submission_deadline"] = meta["deadline"]
            record["deadline_is_conference_fallback"] = True
            record["deadline_source"] = "conference"


# Ordered (theme, keywords); first keyword hit in the title wins. Deterministic and
# free, so every workshop gets a browsable sub-theme instantly; the optional LLM
# pass only refines the ones that fall through to "Other".
THEME_KEYWORDS = [
    ("LLM Agents", ("agent", "agentic", "tool use", "tool-use")),
    ("Alignment & Safety", ("alignment", "safety", "rlhf", "interpretab", "trustworth",
                            "adversarial", "jailbreak", "red team", "guardrail", "robust")),
    ("LLMs & Language", ("language model", "llm", " nlp", "natural language", "transformer",
                         "instruction", "prompt", "retrieval-augmented", " rag", "in-context")),
    ("Reasoning", ("reasoning", "math", "logic", "planning", "chain-of-thought", "theorem")),
    ("Reinforcement Learning", ("reinforcement", " rl ", "rl-", "policy", "reward", "bandit", "control")),
    ("Multimodal & Vision", ("vision", "image", "multimodal", "video", " 3d", "perception", "visual", "scene")),
    ("Generative Models", ("generative", "diffusion", " gan", "synthesis", "text-to-image")),
    ("AI for Science", ("biolog", "medical", "health", "clinical", "science", "physics", "chemistr",
                        "climate", "material", "protein", "drug", "genom", "molecul", "weather")),
    ("Robotics", ("robot", "embodied", "manipulation", "navigation", "autonomous driving")),
    ("Graphs & Geometry", ("graph", "geometric", "topolog", "geometry")),
    ("Efficiency & Systems", ("efficient", "compression", "quantiz", "hardware", "systems for",
                              "scal", "distributed", "federated", "edge", "on-device", "mlsys")),
    ("Data & Benchmarks", ("benchmark", "dataset", "evaluation", "data-centric", "leaderboard")),
    ("Fairness & Society", ("fairness", "ethic", "societ", "social", "governance", "bias", "privacy")),
    ("Theory & Optimization", ("theory", "optimization", "generalization", "statistical", "convex")),
    ("Time Series", ("time series", "temporal", "forecasting")),
]


def derive_theme(title: str) -> str:
    text = " " + (title or "").lower() + " "
    for theme, keywords in THEME_KEYWORDS:
        if any(kw in text for kw in keywords):
            return theme
    return "Other"


def apply_themes(records: list[dict], llm_limit: int = 0) -> None:
    """Give every record a browsable `theme`. Keyword baseline for all; optional
    bounded LLM refinement for the ones that land in 'Other' (carried forward)."""
    used = 0
    for record in records:
        if record.get("theme_source") == "llm" and record.get("theme"):
            continue  # keep a good LLM theme from a previous run
        theme = derive_theme(record.get("title", ""))
        record["theme"] = theme
        record["theme_source"] = "keyword"
        # Don't spend LLM calls on placeholder venue gaps (opaque titles like
        # "NeurIPS 2026 workshops"); only refine real workshop records.
        if (
            theme == "Other"
            and record.get("source_kind") != "source_gap"
            and used < llm_limit
            and llm_extract.llm_enabled()
        ):
            area = (record.get("areas") or [""])[0]
            refined = llm_extract.extract_theme(record.get("title", ""), area)
            used += 1
            if refined:
                record["theme"] = refined
                record["theme_source"] = "llm"


def normalized_key(record: dict) -> tuple:
    host = urlparse(record.get("website_url") or "").netloc.lower().removeprefix("www.")
    title = re.sub(r"[^a-z0-9]+", " ", record["title"].lower()).strip()
    return (record["year"], record["parent_venue"].lower(), host, title[:80])


def merge_records(records: Iterable[dict]) -> list[dict]:
    merged: dict[tuple, dict] = {}
    rank = {"high": 3, "medium": 2, "low": 1}
    for record in records:
        key = normalized_key(record)
        old = merged.get(key)
        if not old:
            merged[key] = record
            continue
        old["source_urls"] = dedupe_keep_order(old.get("source_urls", []) + record.get("source_urls", []))[:URL_LIST_CAP]
        old["areas"] = dedupe_keep_order(old.get("areas", []) + record.get("areas", []))
        old["dates_found"] = dedupe_keep_order(old.get("dates_found", []) + record.get("dates_found", []))[:DATE_LIST_CAP]
        if rank.get(record["confidence"], 0) > rank.get(old["confidence"], 0):
            old.update({k: v for k, v in record.items() if k not in {"source_urls", "areas", "dates_found"}})
    return sorted(merged.values(), key=lambda r: (r["year"], r["parent_venue"], r["title"]))


def dedupe_keep_order(items: Iterable[str]) -> list[str]:
    seen = set()
    out = []
    for item in items:
        if not item or item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


def discover(
    offline: bool,
    enrich_openreview_limit: int,
    enrich_delay_seconds: float,
    enrich_official_limit: int,
    enrich_official_delay_seconds: float,
    enrich_llm_limit: int = 0,
    enrich_theme_limit: int = 0,
) -> dict:
    seeds = load_seeds()
    years = current_and_next_year()
    records = discover_openreview_homepage(seeds, years) if not offline else []
    carry_forward_existing_metadata(records)
    if records:
        enrich_openreview_records(
            records,
            limit=enrich_openreview_limit,
            delay_seconds=enrich_delay_seconds,
        )
        enrich_official_page_dates(
            records,
            seeds,
            limit=enrich_official_limit,
            delay_seconds=enrich_official_delay_seconds,
            llm_limit=enrich_llm_limit,
        )

    for seed in seeds:
        for year in years:
            found_for_seed_year = any(
                r["parent_venue"] == seed.name and r["year"] == year for r in records
            )
            if not found_for_seed_year:
                records.append(expected_record(seed, year))

    apply_conference_baseline(records, load_conference_meta())
    apply_themes(records, enrich_theme_limit)
    workshops = merge_records(records)
    return {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "target_years": years,
        "source": (
            "Known source parsers: OpenReview homepage + upstream conference feeds "
            "+ curated venue seeds"
        ),
        "source_parsers": [
            "openreview_homepage",
            "ccfddl",
            "ai_deadlines",
            "sec_deadlines",
            "tcs_conf",
            "local_paper_tracker_json",
            "curated_venue_watchlist",
        ],
        "seed_count": len(seeds),
        "workshop_count": len(workshops),
        "workshops": workshops,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--offline",
        action="store_true",
        help="Skip source fetching and emit generated current/next-year gap records.",
    )
    parser.add_argument(
        "--enrich-openreview-limit",
        type=int,
        default=300,
        help="Maximum OpenReview group records to enrich with website/location/date metadata.",
    )
    parser.add_argument(
        "--enrich-delay-seconds",
        type=float,
        default=60.0,
        help="Delay between OpenReview enrichment calls. Use 60 for one call per minute.",
    )
    parser.add_argument(
        "--enrich-official-limit",
        type=int,
        default=80,
        help="Maximum official workshop pages to fetch for deadline/date extraction.",
    )
    parser.add_argument(
        "--enrich-official-delay-seconds",
        type=float,
        default=1.0,
        help="Delay between official workshop page fetches.",
    )
    parser.add_argument(
        "--enrich-llm-limit",
        type=int,
        default=0,
        help=(
            "Maximum LLM second-pass deadline extractions per run (only used when a "
            "GROQ_API_KEY/OPENROUTER_API_KEY/GEMINI_API_KEY is set; 0 disables the LLM pass)."
        ),
    )
    parser.add_argument(
        "--enrich-theme-limit",
        type=int,
        default=0,
        help=(
            "Maximum LLM theme-refinement calls per run for workshops the keyword "
            "tagger leaves as 'Other' (0 = keyword themes only)."
        ),
    )
    args = parser.parse_args()

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = discover(
        offline=args.offline,
        enrich_openreview_limit=args.enrich_openreview_limit,
        enrich_delay_seconds=args.enrich_delay_seconds,
        enrich_official_limit=args.enrich_official_limit,
        enrich_official_delay_seconds=args.enrich_official_delay_seconds,
        enrich_llm_limit=args.enrich_llm_limit,
        enrich_theme_limit=args.enrich_theme_limit,
    )
    if OUT_PATH.exists():
        OUT_PATH.chmod(0o644)
    with open(OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    DOCS_OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(DOCS_OUT_PATH, "w") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)
    print(
        f"wrote {OUT_PATH} "
        f"({payload['workshop_count']} records, years {payload['target_years']})"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
