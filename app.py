"""Workshop GPT dashboard."""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import quote

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

sys.path.insert(0, str(Path(__file__).parent))
try:
    from fetcher import llm_extract
except ImportError:  # pragma: no cover
    llm_extract = None

DATA_PATH = Path(__file__).parent / "data" / "workshops.json"
LOGO_PATH = Path(__file__).parent / "assets" / "logo.png"
THUMBNAIL_PATH = Path(__file__).parent / "assets" / "thumbnail.png"
USER_AVATAR_PATH = Path(__file__).parent / "assets" / "user-avatar.jpg"
CONFERENCE_DASHBOARD_URL = "https://paper-tracker-madhava.streamlit.app/"

AUTHOR_NAME = "Madhava Gaikwad"
AUTHOR_LINKEDIN = "https://www.linkedin.com/in/alignops/"
GITHUB_URL = "https://github.com/krimler/workshop-tracker"
APP_URL = "https://workshop-gpt-madhava.streamlit.app/"  # live Streamlit app
SHARE_TEXT = quote("Workshop GPT: every ML/CS workshop with its deadline, in one place. Free, updated daily.")

# Visitor analytics (GoatCounter — free, cookie-less). Set to your subdomain
# (e.g. "workshop-gpt" for workshop-gpt.goatcounter.com) or the GOATCOUNTER_CODE
# env/secret to enable. Empty = disabled.
GOATCOUNTER_CODE = "li69nux"

CHAT_SESSION_LIMIT = 15      # messages per browser session
CHAT_DAILY_LIMIT = 500       # total LLM chat calls/day across all users (free-tier guard)
CHAT_INPUT_MAXLEN = 500

AREA_LABELS = {
    "biomedical": "Biomedical",
    "ai_ml": "AI / ML",
    "software_engineering": "Software Eng",
    "security": "Security & Privacy",
    "distributed_systems": "Distributed Sys",
    "networking": "Networking",
    "systems": "Systems",
    "theory": "Theory",
    "databases": "Databases",
    "programming_languages": "Programming Lang",
}

AREA_ORDER = [
    "ai_ml",
    "distributed_systems",
    "networking",
    "systems",
    "software_engineering",
    "security",
    "databases",
    "programming_languages",
    "theory",
    "biomedical",
]

AREA_COLORS = {
    "biomedical": "#059669",
    "ai_ml": "#7C3AED",
    "software_engineering": "#DB2777",
    "security": "#DC2626",
    "distributed_systems": "#D97706",
    "networking": "#0891B2",
    "systems": "#2563EB",
    "theory": "#475569",
    "databases": "#0D9488",
    "programming_languages": "#9333EA",
}

VENUE_INFO = {
    "AAAI": {"tier": "A*", "url": "https://aaai.org/conference/aaai/"},
    "ACL": {"tier": "A*", "url": "https://www.aclweb.org/portal/"},
    "COLM": {"tier": "New", "url": "https://colmweb.org/"},
    "CVPR": {"tier": "A*", "url": "https://cvpr.thecvf.com/"},
    "EMNLP": {"tier": "A", "url": "https://2026.emnlp.org/"},
    "ICLR": {"tier": "A*", "url": "https://iclr.cc/"},
    "ICML": {"tier": "A*", "url": "https://icml.cc/"},
    "IJCAI": {"tier": "A*", "url": "https://www.ijcai.org/"},
    "MICCAI": {"tier": "A*", "url": "https://conferences.miccai.org/"},
    "NeurIPS": {"tier": "A*", "url": "https://neurips.cc/"},
    "RLC": {"tier": "New", "url": "https://rl-conference.cc/"},
    "ICSE": {"tier": "A*", "url": "https://conf.researchr.org/series/icse"},
    "FSE": {"tier": "A*", "url": "https://conf.researchr.org/series/fse"},
    "ESEC/FSE": {"tier": "A*", "url": "https://conf.researchr.org/series/fse"},
    "ASE": {"tier": "A*", "url": "https://conf.researchr.org/series/ase"},
    "ISSTA": {"tier": "A", "url": "https://conf.researchr.org/series/issta"},
    "RE": {"tier": "A", "url": "https://conf.researchr.org/series/RE"},
    "MSR": {"tier": "A", "url": "https://conf.researchr.org/series/msr"},
    "SANER": {"tier": "A", "url": "https://conf.researchr.org/series/saner"},
    "MODELS": {"tier": "A", "url": "https://conf.researchr.org/series/models"},
    "ICSME": {"tier": "A", "url": "https://conf.researchr.org/series/icsme"},
    "ICPC": {"tier": "A", "url": "https://conf.researchr.org/series/icpc"},
    "ICST": {"tier": "A", "url": "https://conf.researchr.org/series/icst"},
    "SOSP": {"tier": "A*", "url": "https://www.sigops.org/s/conferences/sosp/"},
    "OSDI": {"tier": "A*", "url": "https://www.usenix.org/conferences/byname/179"},
    "USENIX ATC": {"tier": "A", "url": "https://www.usenix.org/conferences/byname/131"},
    "EuroSys": {"tier": "A", "url": "https://www.eurosys.org/"},
    "ASPLOS": {"tier": "A*", "url": "https://www.asplos-conference.org/"},
    "FAST": {"tier": "A", "url": "https://www.usenix.org/conferences/byname/171"},
    "HotOS": {"tier": "A", "url": "https://sigops.org/s/conferences/hotos/"},
    "SC": {"tier": "A", "url": "https://supercomputing.org/"},
    "PPoPP": {"tier": "A", "url": "https://ppopp.org/"},
    "HPCA": {"tier": "A*", "url": "https://hpca-conf.org/"},
    "ISCA": {"tier": "A*", "url": "https://iscaconf.org/"},
    "MICRO": {"tier": "A*", "url": "https://microarch.org/"},
    "CGO": {"tier": "A", "url": "https://conf.researchr.org/series/cgo"},
    "SIGCOMM": {"tier": "A*", "url": "https://www.sigcomm.org/"},
    "NSDI": {"tier": "A*", "url": "https://www.usenix.org/conferences/byname/925"},
    "INFOCOM": {"tier": "A", "url": "https://ieee-infocom.org/"},
    "IMC": {"tier": "A", "url": "https://conferences.sigcomm.org/imc/"},
    "CoNEXT": {"tier": "A", "url": "https://conferences2.sigcomm.org/co-next/"},
    "MobiCom": {"tier": "A*", "url": "https://www.sigmobile.org/mobicom"},
    "STOC": {"tier": "A*", "url": "https://acm-stoc.org/"},
    "FOCS": {"tier": "A*", "url": "https://focs.computer.org/"},
    "SODA": {"tier": "A*", "url": "https://www.siam.org/conferences-events/past-event-archive/soda26/"},
    "ITCS": {"tier": "A", "url": "https://itcs-conf.org/"},
    "ICALP": {"tier": "A", "url": "https://icalp.org/"},
    "ESA": {"tier": "A", "url": "https://esa-symposium.org/"},
    "SoCG": {"tier": "A", "url": "https://www.computational-geometry.org/"},
    "CCC": {"tier": "A", "url": "https://computationalcomplexity.org/"},
    "SIGMOD": {"tier": "A*", "url": "https://sigmod.org/"},
    "VLDB": {"tier": "A*", "url": "https://www.vldb.org/"},
    "PODS": {"tier": "A*", "url": "https://sigmod.org/pods-home/"},
    "ICDE": {"tier": "A*", "url": "https://ieee-icde.org/"},
    "EDBT": {"tier": "A", "url": "https://edbt.org/"},
    "CIDR": {"tier": "A", "url": "https://www.cidrdb.org/"},
    "CIKM": {"tier": "A", "url": "https://www.cikmconference.org/"},
    "PLDI": {"tier": "A*", "url": "https://pldi.org/"},
    "POPL": {"tier": "A*", "url": "https://popl.org/"},
    "OOPSLA": {"tier": "A", "url": "https://2026.splashcon.org/track/splash-2026-oopsla"},
    "SPLASH": {"tier": "A", "url": "https://splashcon.org/"},
    "ICFP": {"tier": "A", "url": "https://icfpconference.org/"},
    "ECOOP": {"tier": "A", "url": "https://2026.ecoop.org/"},
    "CC": {"tier": "A", "url": "https://conf.researchr.org/series/CC"},
    "VMCAI": {"tier": "A", "url": "https://conf.researchr.org/series/VMCAI"},
}

STATUS_LABELS = {
    "confirmed": "Confirmed",
    "cfp_open": "CFP Open",
    "proposal_open": "Proposal Open",
    "candidate": "Candidate",
    "expected": "Expected",
}

RECORD_TYPE_LABELS = {
    "workshop": "Actual Workshop",
    "proposal": "Proposal Call",
    "source_gap": "!",
}

CONFIDENCE_COLORS = {
    "high": ("#BBF7D0", "#14532D"),
    "medium": ("#FDE68A", "#78350F"),
    "low": ("#E5E7EB", "#374151"),
}

CUSTOM_CSS = """
<style>
/* ---- de-Streamlit: hide the chrome that both looks generic and overlays
   the top/bottom of the page (which was blocking the first & last buttons) ---- */
header[data-testid="stHeader"] { display: none; }
[data-testid="stDecoration"] { display: none; }
[data-testid="stToolbar"] { display: none; }
[data-testid="stStatusWidget"] { display: none; }
#MainMenu { display: none; }
footer { display: none; }
section[data-testid="stSidebar"] { display: none; }

/* keep dropdowns/tooltips from being clipped by column wrappers */
div[data-testid="column"] { overflow: visible !important; }
div[data-testid="stHorizontalBlock"] { overflow: visible !important; }

[data-testid="stAppViewContainer"] {
    background: linear-gradient(180deg, #FAF5FF 0%, #FFFFFF 42%);
}
.block-container { padding-top: 1.6rem; padding-bottom: 1.2rem; max-width: 100% !important; }

.header { display: flex; align-items: center; gap: 1.2rem; margin-bottom: 0.35rem; }
.brand-logo {
    width: 168px; height: 168px; object-fit: contain; border-radius: 22px;
    box-shadow: 0 12px 28px -12px rgba(124,58,237,0.55);
    background: transparent; flex-shrink: 0;
}
.title {
    font-size: 2.3rem; font-weight: 900; letter-spacing: -0.035em; line-height: 1; margin: 0;
    background: linear-gradient(120deg, #7C3AED 0%, #EC4899 52%, #F59E0B 100%);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.sub { color: #6B7280; font-size: 0.92rem; margin-top: 0.35rem; white-space: nowrap; }
.lucid-by { color: #6B7280; font-size: 0.82rem; margin-top: 0.3rem; }
.lucid-by a { color: #7C3AED !important; text-decoration: none !important; font-weight: 600; }
.lucid-by a:hover { text-decoration: underline !important; }
.header-text { flex: 0 1 auto; }
/* compact stat strip pinned to the top-right of the header */
.stat-row { margin-left: auto; display: flex; gap: 0.5rem; flex-wrap: wrap; align-items: stretch; }
.stat-box {
    text-align: center; padding: 0.45rem 0.85rem; border-radius: 12px;
    background: #F5F3FF; border: 1px solid #EDE9FE; min-width: 76px;
}
.stat-box b {
    display: block; font-size: 1.5rem; font-weight: 850; line-height: 1;
    background: linear-gradient(120deg, #7C3AED, #EC4899);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.stat-box span { font-size: 0.62rem; color: #6B7280; text-transform: uppercase; letter-spacing: 0.05em; font-weight: 700; }

/* thin, full-width honesty strip (horizontal, minimal height) */
.transparency {
    font-size: 0.8rem; color: #6B7280; line-height: 1.35;
    background: rgba(124,58,237,0.05); border: 1px solid #EDE9FE; border-radius: 9px;
    padding: 0.35rem 0.8rem; margin: 0.1rem 0 0.5rem;
}
.transparency b { color: #4C1D95; }

.about-band {
    background: #FFFFFF; border: 1px solid #EDE9FE; border-radius: 16px;
    padding: 1.05rem 1.2rem; margin: 0.95rem 0 1rem;
    color: #374151; font-size: 0.93rem; line-height: 1.55;
    box-shadow: 0 10px 28px -22px rgba(124,58,237,0.55);
}
.about-band strong { color: #111827; }
.about-band .lede { font-weight: 800; color: #111827; font-size: 1rem; }
.about-band .first-badge {
    display: inline-block; margin-bottom: 0.5rem; padding: 2px 10px; border-radius: 999px;
    font-size: 0.68rem; font-weight: 800; letter-spacing: 0.04em; text-transform: uppercase;
    color: #fff; background: linear-gradient(120deg, #7C3AED, #EC4899);
}
.about-links { margin-top: 0.55rem; color: #9CA3AF; font-size: 0.82rem; }
.about-inner { color: #374151; font-size: 0.93rem; line-height: 1.55; }
.about-inner .lede { font-weight: 800; color: #111827; font-size: 1rem; margin-bottom: 0.4rem; }

/* collapsible "why" panel styled to match (not the default Streamlit expander) */
[data-testid="stExpander"] {
    border: 1px solid #EDE9FE; border-radius: 14px; background: #FFFFFF;
    box-shadow: 0 10px 26px -22px rgba(124,58,237,0.5); margin: 0.5rem 0 0.9rem;
}
[data-testid="stExpander"] summary { font-weight: 800; color: #4C1D95; }
[data-testid="stExpander"] summary:hover { color: #7C3AED; }
.muted-state {
    background: #F5F3FF; border: 1px solid #EDE9FE; border-radius: 12px;
    color: #6B7280; padding: 0.75rem 0.9rem; font-size: 0.86rem;
    margin: 0.6rem 0 0.9rem;
}
.selected-venue { margin: 0.75rem 0 0.35rem; color: #111827; font-size: 1.05rem; font-weight: 850; }

.highlight-panel {
    background: #FFFFFF; border: 1px solid #EDE9FE; border-radius: 14px;
    padding: 0.95rem 1rem; margin-bottom: 0.8rem;
    box-shadow: 0 10px 26px -22px rgba(124,58,237,0.5);
}
.highlight-title { color: #111827; font-size: 0.95rem; font-weight: 850; margin-bottom: 0.5rem; }
.highlight-item { border-top: 1px solid #F5F3FF; padding: 0.55rem 0; }
.highlight-item:first-child { border-top: 0; padding-top: 0; }
.highlight-item a { color: #111827 !important; text-decoration: none !important; font-weight: 800; }
.highlight-item a:hover { color: #7C3AED !important; text-decoration: underline !important; }
.highlight-meta { color: #6B7280; font-size: 0.78rem; line-height: 1.35; margin-top: 0.15rem; }

.metric {
    background: #FFFFFF; border: 1px solid #EDE9FE; border-radius: 14px;
    padding: 0.85rem 1.05rem; box-shadow: 0 10px 26px -22px rgba(124,58,237,0.5);
}
.metric-label { color: #6B7280; font-size: 0.72rem; font-weight: 750; text-transform: uppercase; letter-spacing: 0.05em; }
.metric-value {
    font-size: 1.85rem; font-weight: 850; line-height: 1.1;
    background: linear-gradient(120deg, #7C3AED, #EC4899);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

.card {
    background: #FFFFFF; border: 1px solid #EDE9FE; border-radius: 16px;
    padding: 1rem 1.1rem; min-height: 168px; margin-bottom: 0.85rem;
    box-shadow: 0 8px 22px -16px rgba(124,58,237,0.4);
    transition: border-color .14s ease, box-shadow .14s ease, transform .14s ease;
}
a.card-link { display: block; color: inherit !important; text-decoration: none !important; }
a.card-link:hover .card {
    border-color: #DDD6FE; box-shadow: 0 16px 30px -16px rgba(124,58,237,0.5);
    transform: translateY(-2px);
}
.card-title { color: #111827; font-size: 1.05rem; line-height: 1.22; font-weight: 800; margin: 0.5rem 0; }
.meta { color: #6B7280; font-size: 0.82rem; line-height: 1.35; }
.strong-meta {
    color: #111827; font-size: 0.84rem; font-weight: 750; margin-top: 0.5rem;
    padding: 0.3rem 0.55rem; background: #FAF5FF; border-radius: 8px; border-left: 3px solid #7C3AED;
    display: inline-block;
}
.venue-heading {
    margin: 1rem 0 0.55rem; padding-top: 0.5rem;
    color: #111827; font-size: 1.05rem; font-weight: 850;
    border-top: 1px solid #EDE9FE;
}
.venue-counts { color: #6B7280; font-size: 0.82rem; font-weight: 650; margin-left: 0.35rem; }
.venue-link { color: #111827 !important; text-decoration: none !important; }
.venue-link:hover { color: #7C3AED !important; text-decoration: underline !important; }
.conf-days { color: #7C3AED; font-size: 0.8rem; font-weight: 650; margin-top: 0.25rem; }
.conf-days.soon { color: #EF4444; font-weight: 750; }
.pill {
    display: inline-block; padding: 2px 8px; border-radius: 999px;
    color: white; font-size: 0.68rem; font-weight: 800; margin: 0 0.25rem 0.25rem 0;
}
.badge {
    display: inline-block; padding: 2px 7px; border-radius: 6px;
    font-size: 0.68rem; font-weight: 850; margin-right: 0.25rem;
}
.evidence {
    color: #6B7280; font-size: 0.78rem; line-height: 1.35; margin-top: 0.5rem;
    display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden;
}
a.open { color: #7C3AED !important; text-decoration: none !important; font-weight: 750; font-size: 0.82rem; }
a.open:hover { text-decoration: underline !important; }

/* share row (GitHub / X / LinkedIn / copy-link), pinned top-right */
.social { display: flex; gap: 0.7rem; align-items: center; justify-content: flex-end; margin: 0 0 0.1rem; }
.social a { line-height: 0; }
.social img { display: block; opacity: 0.75; transition: opacity .12s ease, transform .12s ease; }
.social a:hover img, .social-copy:hover img { opacity: 1; transform: translateY(-2px); }
.social-copy { background: none; border: none; padding: 0; cursor: pointer; line-height: 0; }

/* ---- beautiful buttons (replaces the default grey Streamlit look) ---- */
.stButton > button {
    border-radius: 11px; border: 1px solid #EDE9FE; background: #FFFFFF;
    color: #4C1D95; font-weight: 700; font-size: 0.84rem; padding: 0.5rem 0.9rem;
    box-shadow: 0 6px 16px -12px rgba(124,58,237,0.45);
    transition: transform .13s ease, box-shadow .13s ease, border-color .13s ease, color .13s ease;
}
.stButton > button:hover {
    border-color: #C4B5FD; color: #6D28D9; transform: translateY(-1px);
    box-shadow: 0 12px 22px -12px rgba(124,58,237,0.5);
}
.stButton > button:focus:not(:active) { box-shadow: 0 0 0 3px rgba(196,181,253,0.6); }
/* selected venue (type="primary") = filled violet gradient */
.stButton > button[kind="primary"],
.stButton > button[data-testid="baseButton-primary"],
.stButton > button[data-testid="stBaseButton-primary"] {
    background: linear-gradient(120deg, #7C3AED, #6D28D9); border-color: transparent;
    color: #FFFFFF; box-shadow: 0 12px 24px -12px rgba(124,58,237,0.7);
}
.stButton > button[kind="primary"]:hover,
.stButton > button[data-testid="baseButton-primary"]:hover,
.stButton > button[data-testid="stBaseButton-primary"]:hover {
    color: #FFFFFF; transform: translateY(-1px); filter: brightness(1.06);
}
</style>
"""


@st.cache_data
def image_data_uri(path: Path) -> str:
    if not path.is_file():
        return ""
    mime = "image/png" if path.suffix.lower() == ".png" else "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode()}"


_ICON_PATHS = {
    "github": "M12 .297c-6.63 0-12 5.373-12 12 0 5.303 3.438 9.8 8.205 11.385.6.113.82-.258.82-.577 0-.285-.01-1.04-.015-2.04-3.338.724-4.042-1.61-4.042-1.61C4.422 18.07 3.633 17.7 3.633 17.7c-1.087-.744.084-.729.084-.729 1.205.084 1.838 1.236 1.838 1.236 1.07 1.835 2.809 1.305 3.495.998.108-.776.417-1.305.76-1.605-2.665-.305-5.467-1.334-5.467-5.931 0-1.311.469-2.381 1.236-3.221-.124-.303-.535-1.524.117-3.176 0 0 1.008-.322 3.301 1.23A11.51 11.51 0 0112 5.803c1.02.005 2.047.138 3.006.404 2.291-1.552 3.297-1.23 3.297-1.23.653 1.653.242 2.874.118 3.176.77.84 1.235 1.911 1.235 3.221 0 4.609-2.807 5.624-5.479 5.921.43.372.823 1.102.823 2.222 0 1.606-.014 2.898-.014 3.293 0 .322.216.694.825.576C20.565 22.092 24 17.592 24 12.297c0-6.627-5.373-12-12-12",
    "x": "M18.901 1.153h3.68l-8.04 9.19L24 22.846h-7.406l-5.8-7.584-6.638 7.584H.474l8.6-9.83L0 1.154h7.594l5.243 6.932ZM17.61 20.644h2.039L6.486 3.24H4.298Z",
    "linkedin": "M20.447 20.452h-3.554v-5.569c0-1.328-.027-3.037-1.852-3.037-1.853 0-2.136 1.445-2.136 2.939v5.667H9.351V9h3.414v1.561h.046c.477-.9 1.637-1.85 3.37-1.85 3.601 0 4.267 2.37 4.267 5.455v6.286zM5.337 7.433a2.062 2.062 0 01-2.063-2.065 2.064 2.064 0 112.063 2.065zm1.782 13.019H3.555V9h3.564v11.452zM22.225 0H1.771C.792 0 0 .774 0 1.729v20.542C0 23.227.792 24 1.771 24h20.451C23.2 24 24 23.227 24 22.271V1.729C24 .774 23.2 0 22.225 0z",
    "copy": "M16 1H4c-1.1 0-2 .9-2 2v14h2V3h12V1zm3 4H8c-1.1 0-2 .9-2 2v14c0 1.1.9 2 2 2h11c1.1 0 2-.9 2-2V7c0-1.1-.9-2-2-2zm0 16H8V7h11v14z",
    "check": "M9 16.17L4.83 12l-1.42 1.41L9 19 21 7l-1.41-1.41z",
}


def _icon_uri(name: str, color: str) -> str:
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" '
           f'fill="#{color}"><path d="{_ICON_PATHS[name]}"/></svg>')
    return "data:image/svg+xml," + quote(svg)


def render_social() -> None:
    """Share row: GitHub repo, post to X/LinkedIn, and copy-link."""
    enc_url = quote(APP_URL, safe="")
    x = f"https://twitter.com/intent/tweet?text={SHARE_TEXT}&url={enc_url}"
    li = f"https://www.linkedin.com/sharing/share-offsite/?url={enc_url}"
    st.markdown(
        '<div class="social">'
        f'<a href="{GITHUB_URL}" target="_blank" rel="noopener" title="Source on GitHub">'
        f'<img src="{_icon_uri("github", "24292F")}" width="22"></a>'
        f'<a href="{x}" target="_blank" rel="noopener" title="Share on X">'
        f'<img src="{_icon_uri("x", "000000")}" width="20"></a>'
        f'<a href="{li}" target="_blank" rel="noopener" title="Share on LinkedIn">'
        f'<img src="{_icon_uri("linkedin", "0A66C2")}" width="22"></a>'
        f'<button id="wgpt-copy" class="social-copy" title="Copy link">'
        f'<img src="{_icon_uri("copy", "6B7280")}" width="20"></button>'
        '</div>',
        unsafe_allow_html=True,
    )


def render_social_js() -> None:
    """Wire the copy-link button (lives in the parent doc) from a 0-height iframe."""
    components.html(
        f"""<script>
        (function () {{
          var doc = window.parent.document;
          var btn = doc.getElementById('wgpt-copy');
          if (!btn || btn.dataset.wired) return;
          btn.dataset.wired = '1';
          var orig = btn.innerHTML;
          var check = '<img src="{_icon_uri('check', '16A34A')}" width="20">';
          btn.addEventListener('click', function () {{
            var cb = window.parent.navigator.clipboard || navigator.clipboard;
            cb.writeText('{APP_URL}');
            btn.innerHTML = check;
            setTimeout(function () {{ btn.innerHTML = orig; }}, 1500);
          }});
        }})();
        </script>""",
        height=0,
    )


@st.cache_data(ttl=600)
def load_data() -> dict:
    with open(DATA_PATH) as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# AI chat assistant (grounded on the workshop dataset, guard-railed)
# ---------------------------------------------------------------------------
@st.cache_resource
def _chat_budget() -> dict:
    """Process-global daily call counter, shared across all user sessions."""
    return {"date": "", "count": 0}


def _ensure_llm_keys() -> None:
    """Mirror LLM keys from st.secrets into the env so llm_extract can read them.

    Keeps the key server-side (Streamlit secrets), never sent to the browser."""
    try:
        for key in ("GROQ_API_KEY", "OPENROUTER_API_KEY", "GEMINI_API_KEY",
                    "LLM_API_KEY", "LLM_BASE_URL", "LLM_MODEL",
                    "GROQ_MODEL", "OPENROUTER_MODEL", "GEMINI_MODEL"):
            if key not in os.environ and key in st.secrets:
                os.environ[key] = str(st.secrets[key])
    except Exception:
        pass


def chat_enabled() -> bool:
    _ensure_llm_keys()
    return llm_extract is not None and llm_extract.llm_enabled()


CHAT_STOPWORDS = {
    "workshop", "workshops", "which", "about", "when", "due", "deadline", "deadlines",
    "the", "for", "and", "are", "what", "show", "list", "find", "with", "that", "this",
    "close", "closing", "soon", "any", "there", "have", "does", "tell", "want", "would",
    "conference", "venue", "venues", "research", "paper", "papers", "submission",
}


def retrieve_workshops(df: pd.DataFrame, query: str, k: int = 25) -> pd.DataFrame:
    """Keyword-retrieve the most relevant *real* workshop rows for a question."""
    # Chat answers about actual workshops, not the venue placeholders.
    pool = df[df["record_type"] != "source_gap"] if "record_type" in df else df
    if pool.empty:
        pool = df
    terms = [
        t for t in re.findall(r"[a-z0-9&]+", query.lower())
        if len(t) > 2 and t not in CHAT_STOPWORDS
    ]
    if not terms:
        return pool[pool["days_left"].fillna(1e9) >= 0].sort_values("days_left").head(k)
    cols = ["title", "parent_venue", "area_text", "theme", "location"]
    hay = pool[cols].astype(str).agg(" ".join, axis=1).str.lower()
    score = sum(hay.str.count(re.escape(t)) for t in terms)
    scored = pool.assign(_score=score)
    hits = scored[scored["_score"] > 0].sort_values("_score", ascending=False).head(k)
    if hits.empty:
        hits = scored[scored["days_left"].fillna(1e9) >= 0].sort_values("days_left").head(k)
    return hits


def workshop_context(hits: pd.DataFrame) -> str:
    lines = []
    for r in hits.itertuples(index=False):
        dl = getattr(r, "submission_deadline", "") or "TBD"
        if getattr(r, "deadline_is_conference_fallback", False):
            dl += " (conference deadline, workshop TBD)"
        loc = getattr(r, "location", "") or "location TBD"
        lines.append(
            f"- {r.title} | {r.parent_venue} {r.year} | theme: {r.theme} | "
            f"deadline: {dl} | {loc} | {r.primary_url}"
        )
    return "\n".join(lines) or "(no matching workshops)"


CHAT_SYSTEM = (
    "You are Workshop GPT: a dry, sharp research concierge who has read every CFP and "
    "respects the user's time. You help people find ML/CS workshops from the records given.\n"
    "\n"
    "ANTI-SLOP RULES (follow strictly):\n"
    "- Lead with the answer. No preamble, no sign-off, no 'Great question', 'Sure!', "
    "'I'd be happy to', 'Let me…', 'Here's…'.\n"
    "- Don't restate the question. Don't add a closing summary or 'hope this helps'.\n"
    "- No hedging or filler ('it's worth noting', 'keep in mind', 'as of my knowledge').\n"
    "- No marketing tone, no purple prose, go easy on em-dashes and exclamation marks.\n"
    "- Be concrete: name the workshop, its parent venue, and the exact deadline. Use a tight "
    "bulleted list for multiple hits, one line each.\n"
    "- Short. If one workshop answers it, one line. Never pad to seem thorough.\n"
    "\n"
    "GREETINGS / SMALL TALK: if the user just says hi/hello/hey or chit-chat, greet back in "
    "one friendly line and invite a real question (offer an example like 'LLM-agent workshops "
    "closing soonest'). In the spirit of nohello.net, nudge them to ask the actual question "
    "directly. Never answer a greeting with 'Not in the tracked set'.\n"
    "\n"
    "GROUNDING: for actual workshop questions, use ONLY the records in the user's message. Never "
    "invent deadlines, venues, or links. A deadline marked '(conference deadline, workshop TBD)' "
    "is the parent conference's, not the workshop's; say so. If a workshop question's answer "
    "isn't in the records, reply 'Not in the tracked set.' plus one concrete way to rephrase. "
    "Decline genuinely off-topic requests (unrelated to finding workshops) in one line."
)


def render_chat(df: pd.DataFrame) -> None:
    with st.expander("💬  Ask Workshop GPT", expanded=True):
        st.caption(
            "Find workshops by topic, venue, deadline, or place. Answers use only the tracked "
            'data. Examples: "LLM agent workshops closing soonest", "NeurIPS workshops in San Diego".'
        )
        if not chat_enabled():
            st.info("The assistant is offline: no LLM key is configured for this deployment.")
            return
        assistant_avatar = str(THUMBNAIL_PATH) if THUMBNAIL_PATH.is_file() else "🛰️"
        user_avatar = str(USER_AVATAR_PATH) if USER_AVATAR_PATH.is_file() else "🧑‍💻"
        history = st.session_state.setdefault("chat_history", [])
        for msg in history:
            avatar = assistant_avatar if msg["role"] == "assistant" else user_avatar
            with st.chat_message(msg["role"], avatar=avatar):
                st.markdown(msg["content"])

        prompt = st.chat_input("e.g. Which LLM-agent workshops close soonest?")
        if not prompt:
            return
        prompt = prompt.strip()[:CHAT_INPUT_MAXLEN]
        if sum(1 for m in history if m["role"] == "user") >= CHAT_SESSION_LIMIT:
            st.warning("You've reached this session's question limit. Refresh to start over.")
            return
        budget = _chat_budget()
        today = pd.Timestamp.now(tz="UTC").date().isoformat()
        if budget["date"] != today:
            budget["date"], budget["count"] = today, 0
        if budget["count"] >= CHAT_DAILY_LIMIT:
            st.warning("The assistant has hit today's usage cap. Please try again tomorrow.")
            return
        budget["count"] += 1

        history.append({"role": "user", "content": prompt})
        user_msg = f"Question: {prompt}\n\nWorkshop records:\n{workshop_context(retrieve_workshops(df, prompt))}"
        with st.spinner("Searching the workshops…"):
            answer = llm_extract.complete(
                [{"role": "system", "content": CHAT_SYSTEM},
                 {"role": "user", "content": user_msg}],
                max_tokens=350, temperature=0.2,
            )
        history.append({
            "role": "assistant",
            "content": answer or "Sorry, the assistant is unavailable right now. Please try again later.",
        })
        st.rerun()


def html_escape(value) -> str:
    if value is None:
        value = ""
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def build_dataframe(data: dict) -> pd.DataFrame:
    df = pd.DataFrame(data.get("workshops", []))
    if df.empty:
        return df
    for column in (
        "official_url", "openreview_url", "location", "workshop_date", "submission_deadline",
        "location_source", "date_source", "deadline_source", "conference_dates_text",
        "conference_deadline", "conference_abstract_deadline",
    ):
        if column not in df:
            df[column] = ""
    if "deadline_is_conference_fallback" not in df:
        df["deadline_is_conference_fallback"] = False
    df["deadline_is_conference_fallback"] = df["deadline_is_conference_fallback"].fillna(False)
    if "theme" not in df:
        df["theme"] = ""
    df["theme"] = df["theme"].fillna("").replace("", "Other")
    for column in ("deadline_dates", "dates_found"):
        if column not in df:
            df[column] = [[] for _ in range(len(df))]
    df["area_primary"] = df["areas"].apply(lambda xs: (xs or [""])[0])
    df["area_text"] = df["areas"].apply(
        lambda xs: ", ".join(AREA_LABELS.get(x, x) for x in (xs or []))
    )
    df["status_label"] = df["status"].map(lambda s: STATUS_LABELS.get(s, s))
    df["actionable"] = df["safety"].apply(lambda s: bool((s or {}).get("actionable")))
    df["safety_note"] = df["safety"].apply(lambda s: (s or {}).get("note", ""))
    df["record_type"] = df.apply(record_type, axis=1)
    df["record_type_label"] = df["record_type"].map(RECORD_TYPE_LABELS)
    df["venue_tier"] = df["parent_venue"].map(lambda v: VENUE_INFO.get(v, {}).get("tier", ""))
    df["venue_url"] = df["parent_venue"].map(lambda v: VENUE_INFO.get(v, {}).get("url", ""))
    df["primary_url"] = df.apply(primary_url, axis=1)
    df["date_label"] = df.apply(date_label, axis=1)
    df["next_date"] = pd.to_datetime(
        list(df.apply(next_workshop_date, axis=1)),
        utc=True,
        errors="coerce",
    )
    now = pd.Timestamp.now(tz="UTC")
    df["days_left"] = (df["next_date"] - now).dt.total_seconds() / 86400
    df["urgency_label"] = df["days_left"].apply(days_label)
    return df


def record_type(row) -> str:
    title = str(row.get("title", "")).lower()
    url = str(row.get("website_url", "")).lower()
    if row.get("source_kind") == "source_gap":
        return "source_gap"
    if row.get("status") == "proposal_open" or "proposal" in title or "workshop_proposals" in url:
        return "proposal"
    return "workshop"


def primary_url(row) -> str:
    for key in ("official_url", "website_url", "openreview_url"):
        value = row.get(key, "")
        if value:
            return str(value)
    return "#"


def date_label(row) -> str:
    now = pd.Timestamp.now(tz="UTC")
    submission = parse_date_value(row.get("submission_deadline"))
    if pd.notna(submission) and submission >= now:
        if row.get("deadline_is_conference_fallback"):
            return f"Conference deadline · workshop TBD: {row['submission_deadline']}"
        return f"Submission deadline: {row['submission_deadline']}"
    deadlines = row.get("deadline_dates") or []
    upcoming_deadlines = [d for d in deadlines if pd.notna(parse_date_value(d)) and parse_date_value(d) >= now]
    if upcoming_deadlines:
        return "Deadline found: " + ", ".join(str(d) for d in upcoming_deadlines[:2])
    event_date = parse_date_value(row.get("workshop_date"))
    if pd.notna(event_date) and event_date >= now:
        return f"Workshop date: {row['workshop_date']}"
    dates = row.get("dates_found") or []
    upcoming_dates = [d for d in dates if pd.notna(parse_date_value(d)) and parse_date_value(d) >= now]
    if upcoming_dates:
        return "Date found: " + ", ".join(str(d) for d in upcoming_dates[:2])
    return ""


def parse_date_value(value):
    return pd.to_datetime(value, utc=True, errors="coerce")


def next_workshop_date(row):
    values = []
    if row.get("submission_deadline"):
        values.append(row.get("submission_deadline"))
    values.extend(row.get("deadline_dates") or [])
    if row.get("workshop_date"):
        values.append(row.get("workshop_date"))
    values.extend(row.get("dates_found") or [])
    parsed = pd.to_datetime(values, utc=True, errors="coerce")
    parsed = [p for p in parsed if pd.notna(p)]
    if not parsed:
        return pd.NaT
    now = pd.Timestamp.now(tz="UTC")
    upcoming = [p for p in parsed if p >= now]
    return min(upcoming) if upcoming else max(parsed)


def days_label(days) -> str:
    if pd.isna(days):
        return ""
    d = int(round(days))
    if d < 0:
        return ""
    if d == 0:
        return "today"
    return f"{d} days left"


def metric(label: str, value) -> str:
    return (
        '<div class="metric">'
        f'<div class="metric-label">{html_escape(label)}</div>'
        f'<div class="metric-value">{html_escape(value)}</div>'
        '</div>'
    )


def render_analytics() -> None:
    """Crude visitor count via GoatCounter (cookie-less). Fires once per session,
    counts the real browser (runs client-side in a 0-height iframe). No-op if unset."""
    code = (os.environ.get("GOATCOUNTER_CODE") or GOATCOUNTER_CODE).strip()
    if not code or st.session_state.get("_visit_counted"):
        return
    st.session_state["_visit_counted"] = True
    components.html(
        f"""<script>
        window.goatcounter = {{ path: '/app', title: 'Workshop GPT app' }};
        </script>
        <script data-goatcounter="https://{code}.goatcounter.com/count"
                async src="//gc.zgo.at/count.js"></script>""",
        height=0,
    )


def render_transparency(df: pd.DataFrame) -> None:
    """A thin, honest one-liner about how complete the data actually is."""
    real = df[df["record_type"] == "workshop"]
    total = len(real)
    if not total:
        return
    confirmed = int(real["deadline_source"].isin(["openreview", "official_page", "llm"]).sum())
    located = int((real["location"].astype(str).str.strip() != "").sum())
    pct = round(100 * confirmed / total)
    st.markdown(
        f'<div class="transparency"><b>Transparency:</b> '
        f'{confirmed}/{total} workshops ({pct}%) have a confirmed submission deadline. '
        f'The rest show the parent conference\'s deadline as a placeholder (marked '
        f'"workshop TBD"). {located} have a location. Rebuilt daily; more fill in each day.</div>',
        unsafe_allow_html=True,
    )


def area_pills(areas: list[str]) -> str:
    out = []
    for area in areas or []:
        color = AREA_COLORS.get(area, "#64748B")
        label = AREA_LABELS.get(area, area)
        out.append(f'<span class="pill" style="background:{color}">{html_escape(label)}</span>')
    return "".join(out)


def confidence_badge(confidence: str) -> str:
    bg, fg = CONFIDENCE_COLORS.get(confidence, CONFIDENCE_COLORS["low"])
    return f'<span class="badge" style="background:{bg};color:{fg}">{html_escape(confidence.upper())}</span>'


def status_badge(status: str) -> str:
    bg = {
        "confirmed": "#DBEAFE",
        "cfp_open": "#DCFCE7",
        "proposal_open": "#FEF3C7",
        "candidate": "#E0F2FE",
        "expected": "#F1F5F9",
    }.get(status, "#F1F5F9")
    return f'<span class="badge" style="background:{bg};color:#0F172A">{html_escape(STATUS_LABELS.get(status, status))}</span>'


def venue_badge(venue: str) -> str:
    tier = VENUE_INFO.get(venue, {}).get("tier")
    if not tier:
        return ""
    bg = "#DBEAFE" if tier == "A*" else "#DCFCE7" if tier == "A" else "#F1F5F9"
    return f'<span class="badge" style="background:{bg};color:#0F172A">Venue {html_escape(tier)}</span>'


def record_type_badge(record_kind: str) -> str:
    if record_kind == "source_gap":
        return (
            '<span class="badge" title="Tracked venue target; no confirmed workshop page yet" '
            'style="background:#FFF7ED;color:#9A3412">!</span>'
        )
    bg = {
        "workshop": "#E0F2FE",
        "proposal": "#FEF3C7",
    }.get(record_kind, "#F1F5F9")
    return f'<span class="badge" style="background:{bg};color:#0F172A">{html_escape(RECORD_TYPE_LABELS.get(record_kind, record_kind))}</span>'


def source_label(row) -> str:
    if row.record_type == "source_gap":
        return "tracking target"
    return str(row.source_kind).replace("_", " ")


def safety_label(row) -> str:
    if row.record_type == "source_gap":
        return "check venue"
    return "actionable" if row.actionable else "needs confirmation"


def render_header(data: dict, df: pd.DataFrame) -> None:
    raw_fetched = data.get("fetched_at", "")
    try:
        fetched = pd.to_datetime(raw_fetched, utc=True).strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        fetched = raw_fetched[:10]
    logo_uri = image_data_uri(THUMBNAIL_PATH if THUMBNAIL_PATH.is_file() else LOGO_PATH)
    logo_html = f'<img class="brand-logo" src="{logo_uri}" alt="Workshop GPT">' if logo_uri else ""
    workshops, calls_df, _targets = split_record_lanes(df)
    venues = workshops["parent_venue"].nunique()
    actionable = int(df["actionable"].sum())
    st.markdown(
        '<div class="header">'
        f'{logo_html}'
        '<div class="header-text">'
        '<div class="title">Workshop GPT</div>'
        f'<div class="sub">A list of ML/CS workshops with their deadlines and locations. '
        f'Updated {html_escape(fetched)}.</div>'
        f'<div class="lucid-by">by <a href="{AUTHOR_LINKEDIN}" target="_blank" '
        f'rel="noopener">{AUTHOR_NAME}</a></div>'
        '</div>'
        '<div class="stat-row">'
        f'<div class="stat-box"><b>{venues}</b><span>Venues</span></div>'
        f'<div class="stat-box"><b>{len(workshops)}</b><span>Workshops</span></div>'
        f'<div class="stat-box"><b>{len(calls_df)}</b><span>Calls / CFP</span></div>'
        f'<div class="stat-box"><b>{actionable}</b><span>Actionable</span></div>'
        '</div>'
        '</div>',
        unsafe_allow_html=True,
    )
    with st.expander("What this is", expanded=False):
        st.markdown(
            '<div class="about-inner">'
            'There is no single list of academic workshops. Each one runs its own call for '
            'papers, with its own deadline, on its own page, so finding them means checking '
            'conferences one by one. This collects them in one place: the workshop, its '
            'conference, the deadline, and the location. The data is rebuilt daily from public '
            'sources. You can browse by area and venue below, or ask the assistant to find the '
            'ones that fit what you work on.'
            '<br><br>'
            '<strong>Honest about where it stands:</strong> this is an early, one-person project. '
            'Coverage is not complete, many workshops still show the parent conference’s deadline '
            'until their own is confirmed, and the deadline/theme/chat features run on free LLM '
            'tiers that rate-limit, so the data fills in gradually. Always verify a deadline on the '
            'linked source before submitting.'
            '<br><br>'
            '<strong>Want to help?</strong> Any way is welcome: '
            '<a class="open" href="https://github.com/krimler/workshop-tracker" target="_blank" rel="noopener">code on GitHub</a>, '
            'LLM credits (Claude tokens or Groq/OpenRouter quota) so more deadlines fill in each '
            "day, a correction, a missing venue, or just an email to say it's useful. Even a hello "
            'helps me keep this going.'
            '<div class="about-links">Email <strong>yavan [at] outlook [dot] com</strong> '
            'to add a venue, contribute, support, or just say hi.</div>'
            '</div>',
            unsafe_allow_html=True,
        )


def render_cards(df: pd.DataFrame) -> None:
    cols = st.columns(3)
    for i, row in enumerate(df.itertuples(index=False)):
        with cols[i % 3]:
            source = html_escape(source_label(row))
            evidence = html_escape(row.evidence)
            safety = html_escape(safety_label(row))
            url = html_escape(row.primary_url)
            date_html = f'<div class="strong-meta">{html_escape(row.date_label)}</div>' if row.date_label else ""
            urgency_html = f'<div class="conf-days soon">{html_escape(row.urgency_label)}</div>' if row.urgency_label else ""
            location_text = html_escape(row.location) if getattr(row, "location", "") else ""
            if location_text and getattr(row, "location_source", "") == "conference":
                location_text += " · co-located"
            location_html = f'<div class="meta">{location_text}</div>' if location_text else ""
            st.markdown(
                f'<a class="card-link" href="{url}" target="_blank" rel="noopener">'
                '<div class="card">'
                f'<div>{area_pills(row.areas)}</div>'
                f'<div>{record_type_badge(row.record_type)}{venue_badge(row.parent_venue)}{confidence_badge(row.confidence)}</div>'
                f'<div class="card-title">{html_escape(row.title)}</div>'
                f'<div class="meta">{html_escape(row.parent_venue)} · {html_escape(row.year)} · {source} · {safety}</div>'
                f'{date_html}{urgency_html}{location_html}'
                f'<div class="evidence">{evidence}</div>'
                '</div></a>',
                unsafe_allow_html=True,
            )


def render_grouped_cards(df: pd.DataFrame) -> None:
    for venue, group in df.groupby("parent_venue", sort=True):
        call_mask = group["status"].isin(["cfp_open", "proposal_open"]) | (group["record_type"] == "proposal")
        workshop_group = group[(group["record_type"] == "workshop") & ~call_mask]
        call_group = group[call_mask]
        target_group = group[group["record_type"] == "source_gap"]
        actual = len(workshop_group)
        proposals = len(call_group)
        gaps = int((group["record_type"] == "source_gap").sum())
        count_bits = [f"{actual} workshops", f"{proposals} calls/CFP"]
        if gaps:
            count_bits.append(f"{gaps} targets")
        venue_url = VENUE_INFO.get(venue, {}).get("url", "")
        venue_name = html_escape(venue)
        venue_html = (
            f'<a class="venue-link" href="{html_escape(venue_url)}" target="_blank" rel="noopener">{venue_name}</a>'
            if venue_url else venue_name
        )
        label = f"{venue} - " + " · ".join(count_bits)
        with st.expander(label, expanded=False):
            st.markdown(
                f'<div class="venue-heading">{venue_html} {venue_badge(venue)}</div>',
                unsafe_allow_html=True,
            )
            if actual:
                st.markdown("**Workshop records**")
                render_cards(workshop_group.head(36))
            if proposals:
                if not actual:
                    st.info("Only calls / CFP / proposal records are available for this venue right now.")
                st.markdown("**Calls / CFP / proposals**")
                render_cards(call_group.head(24))
            if len(target_group):
                st.markdown("**Tracked targets**")
                st.caption("The ! marker means this is a venue we track for workshop discovery, but no confirmed workshop page has been parsed yet.")
                render_cards(target_group.head(12))


def render_table(df: pd.DataFrame) -> None:
    display = df[
        [
            "title", "parent_venue", "year", "area_text", "status_label",
            "record_type_label", "venue_tier", "date_label", "location", "confidence",
            "source_kind", "primary_url", "evidence",
            "actionable", "safety_note",
        ]
    ].rename(
        columns={
            "title": "Workshop / result",
            "parent_venue": "Venue / source",
            "year": "Year",
            "area_text": "Areas",
            "status_label": "Status",
            "record_type_label": "Type",
            "venue_tier": "Venue tier",
            "date_label": "Date",
            "location": "Location",
            "confidence": "Confidence",
            "source_kind": "Source",
            "primary_url": "URL",
            "evidence": "Evidence",
            "actionable": "Actionable",
            "safety_note": "Safety note",
        }
    )
    st.dataframe(
        display,
        column_config={"URL": st.column_config.LinkColumn("URL", display_text="open")},
        hide_index=True,
        use_container_width=True,
        height=660,
    )


def split_record_lanes(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    call_mask = df["status"].isin(["cfp_open", "proposal_open"]) | (df["record_type"] == "proposal")
    target_mask = df["record_type"] == "source_gap"
    workshop_mask = (df["record_type"] == "workshop") & ~call_mask & ~target_mask
    return df[workshop_mask], df[call_mask], df[target_mask]


def render_lane(df: pd.DataFrame, view_mode: str) -> None:
    if df.empty:
        return
    if view_mode == "Table":
        render_table(df)
    else:
        render_cards(df.head(120))


def render_themed_lane(df: pd.DataFrame, view_mode: str) -> None:
    """Render workshops grouped under sub-theme headers (largest first, Other last)."""
    counts = df["theme"].value_counts()
    themes = sorted(counts.index, key=lambda t: (t == "Other", -counts[t], str(t)))
    for theme in themes:
        sub = df[df["theme"] == theme]
        st.markdown(
            f'<div class="venue-heading">{html_escape(str(theme))}'
            f'<span class="venue-counts">{len(sub)} workshops</span></div>',
            unsafe_allow_html=True,
        )
        render_lane(sub, view_mode)


def venue_button_label(venue: str, workshops: int, calls: int, targets: int) -> str:
    bits = []
    if workshops:
        bits.append(f"{workshops}W")
    if calls:
        bits.append(f"{calls}CFP")
    if targets:
        bits.append(f"{targets}!")
    return f"{venue} · " + " · ".join(bits) if bits else venue


ALL_VENUES = "__all__"


def render_venue_buttons(area: str, summaries: list[dict]) -> str:
    selected_key = f"selected_venue_{area}"
    if not summaries:
        return ""
    # An "All venues" option first so the topic shows every workshop at once,
    # not one venue at a time. It is the default selection.
    total_w = sum(s["workshops"] for s in summaries)
    all_item = {"venue": ALL_VENUES, "label": f"★ All venues ({total_w}W)"}
    items = [all_item] + summaries
    valid = {item["venue"] for item in items}
    if st.session_state.get(selected_key) not in valid:
        st.session_state[selected_key] = ALL_VENUES

    columns_per_row = 5
    for start in range(0, len(items), columns_per_row):
        cols = st.columns(columns_per_row)
        for col, item in zip(cols, items[start:start + columns_per_row]):
            selected = st.session_state.get(selected_key) == item["venue"]
            label = item.get("label") or venue_button_label(
                item["venue"], item["workshops"], item["calls"], item["targets"]
            )
            if col.button(
                label,
                key=f"venue_{area}_{item['venue']}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state[selected_key] = item["venue"]
                st.rerun()  # re-run so the button colour reflects the new selection now
    return st.session_state.get(selected_key, ALL_VENUES)


def select_venue(area: str, venue: str) -> None:
    st.session_state[f"selected_venue_{area}"] = venue


def render_quick_views(areas: list[str], open_venues: list[str], years: list[int]) -> None:
    st.markdown('<div class="highlight-panel"><div class="highlight-title">Quick Views</div>', unsafe_allow_html=True)
    q1, q2 = st.columns(2)
    q1.button("Workshops", use_container_width=True, on_click=set_quick_view, args=("workshops", areas, open_venues, years))
    q2.button("Calls/CFP", use_container_width=True, on_click=set_quick_view, args=("proposals", areas, open_venues, years))
    q3, q4 = st.columns(2)
    q3.button("AI / ML", use_container_width=True, on_click=set_quick_view, args=("workshops", ["ai_ml"], open_venues, years))
    q4.button("Biomedical", use_container_width=True, on_click=set_quick_view, args=("workshops", ["biomedical"], open_venues, years))
    q5, q6 = st.columns(2)
    q5.button("Security", use_container_width=True, on_click=set_quick_view, args=("workshops", ["security"], open_venues, years))
    q6.button("RLC / RL", use_container_width=True, on_click=set_rlc_quick_view, args=(open_venues, years))
    q7, q8 = st.columns(2)
    q7.button("Coverage", use_container_width=True, on_click=set_quick_view, args=("coverage", areas, open_venues, years))
    q8.button("Theory", use_container_width=True, on_click=set_quick_view, args=("all", ["theory"], open_venues, years))
    st.button("Reset", use_container_width=True, on_click=set_quick_view, args=("all", areas, open_venues, years))
    st.markdown('</div>', unsafe_allow_html=True)


def render_highlights(df: pd.DataFrame) -> None:
    workshops, calls, targets = split_record_lanes(df)
    st.markdown('<div class="highlight-panel"><div class="highlight-title">Current Highlights</div>', unsafe_allow_html=True)
    rlc = workshops[workshops["parent_venue"] == "RLC"].head(4)
    if not rlc.empty:
        st.markdown('<div class="highlight-meta">Reinforcement Learning Conference workshops</div>', unsafe_allow_html=True)
        for row in rlc.itertuples(index=False):
            st.markdown(
                '<div class="highlight-item">'
                f'<a href="{html_escape(row.primary_url)}" target="_blank" rel="noopener">{html_escape(row.title)}</a>'
                f'<div class="highlight-meta">{html_escape(row.year)} · {html_escape(row.parent_venue)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
    if not calls.empty:
        st.markdown('<div class="highlight-title">Calls / CFP</div>', unsafe_allow_html=True)
        for row in calls.head(5).itertuples(index=False):
            st.markdown(
                '<div class="highlight-item">'
                f'<a href="{html_escape(row.primary_url)}" target="_blank" rel="noopener">{html_escape(row.title)}</a>'
                f'<div class="highlight-meta">{html_escape(row.parent_venue)} · {html_escape(row.year)} · {html_escape(row.status_label)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )
    if targets.empty and calls.empty and rlc.empty:
        st.markdown('<div class="highlight-meta">No current highlights under these filters.</div>', unsafe_allow_html=True)
    st.markdown('</div>', unsafe_allow_html=True)


def render_topic_closing_soon(topic_df: pd.DataFrame) -> None:
    dated = topic_df[
        topic_df["next_date"].notna()
        & (topic_df["days_left"].fillna(999999) >= 0)
        & (topic_df["urgency_label"].astype(bool))
    ].sort_values(["days_left", "parent_venue"]).head(8)
    if dated.empty:
        st.markdown(
            '<div class="muted-state">No dated closing-soon items parsed for this topic yet.</div>',
            unsafe_allow_html=True,
        )
        return

    cols = st.columns(min(4, len(dated)))
    for i, row in enumerate(dated.itertuples(index=False)):
        with cols[i % len(cols)]:
            st.markdown(
                '<div class="highlight-item">'
                f'<a href="{html_escape(row.primary_url)}" target="_blank" rel="noopener">{html_escape(row.title)}</a>'
                f'<div class="highlight-meta">{html_escape(row.parent_venue)} · {html_escape(row.urgency_label)}</div>'
                f'<div class="highlight-meta">{html_escape(row.date_label)}</div>'
                '</div>',
                unsafe_allow_html=True,
            )


def venue_summaries(topic_df: pd.DataFrame) -> list[dict]:
    out = []
    for venue, group in topic_df.groupby("parent_venue", sort=False):
        workshops, calls, targets = split_record_lanes(group)
        next_date = group["next_date"].dropna().min()
        days_left = group.loc[group["next_date"].notna(), "days_left"].min()
        out.append(
            {
                "venue": venue,
                "workshops": len(workshops),
                "calls": len(calls),
                "targets": len(targets),
                "next_date": next_date,
                "days_left": days_left,
            }
        )
    return sorted(
        out,
        key=lambda item: (
            pd.isna(item["days_left"]),
            item["days_left"] if pd.notna(item["days_left"]) else 999999,
            item["workshops"] == 0,
            -item["workshops"],
            -item["calls"],
            item["venue"].lower(),
        ),
    )


def current_topic(df: pd.DataFrame) -> tuple[str, pd.DataFrame]:
    present = [area for area in AREA_ORDER if df["areas"].map(lambda xs, a=area: a in (xs or [])).any()]
    present.extend(
        area for area in sorted({a for xs in df["areas"] for a in (xs or [])})
        if area not in present
    )
    if not present:
        return "", df.iloc[0:0]

    selected_key = "selected_topic"
    if st.session_state.get(selected_key) not in present:
        preferred = next((a for a in st.session_state.get("area_choice", []) if a in present), present[0])
        st.session_state[selected_key] = preferred

    columns_per_row = 5
    for start in range(0, len(present), columns_per_row):
        cols = st.columns(columns_per_row)
        for col, area in zip(cols, present[start:start + columns_per_row]):
            count = int(df["areas"].map(lambda xs, a=area: a in (xs or [])).sum())
            selected = st.session_state[selected_key] == area
            if col.button(
                f"{AREA_LABELS.get(area, area)} ({count})",
                key=f"topic_{area}",
                use_container_width=True,
                type="primary" if selected else "secondary",
            ):
                st.session_state[selected_key] = area
                st.rerun()  # re-run so the selected topic colours immediately

    area = st.session_state[selected_key]
    return area, df[df["areas"].map(lambda xs, a=area: a in (xs or []))]


def render_topic_browser(df: pd.DataFrame, view_mode: str) -> None:
    area, topic_df = current_topic(df)
    if topic_df.empty:
        st.info("No workshop records match the current filters.")
        return

    workshops, calls, targets = split_record_lanes(topic_df)
    c1, c2, c3 = st.columns(3)
    c1.markdown(metric("Workshops", len(workshops)), unsafe_allow_html=True)
    c2.markdown(metric("Calls / CFP", len(calls)), unsafe_allow_html=True)
    c3.markdown(metric("Tracking targets", len(targets)), unsafe_allow_html=True)

    st.markdown("**Closing soon in this topic**")
    render_topic_closing_soon(topic_df)

    selected_venue = render_venue_buttons(area, venue_summaries(topic_df))
    if selected_venue == ALL_VENUES:
        all_workshops, all_calls, all_targets = split_record_lanes(topic_df)
        st.markdown(
            f'<div class="selected-venue">All venues in {html_escape(AREA_LABELS.get(area, area))} '
            f'· {len(all_workshops)} workshops · grouped by theme</div>',
            unsafe_allow_html=True,
        )
        if not all_workshops.empty:
            render_themed_lane(all_workshops, view_mode)
        else:
            st.markdown(
                '<div class="muted-state">No workshop records in this topic yet.</div>',
                unsafe_allow_html=True,
            )
        if not all_calls.empty:
            st.markdown("**Calls / CFP**")
            render_lane(all_calls, view_mode)
        return
    selected_df = topic_df[topic_df["parent_venue"] == selected_venue]
    selected_workshops, selected_calls, selected_targets = split_record_lanes(selected_df)
    st.markdown(
        f'<div class="selected-venue">{html_escape(selected_venue)} '
        f'{venue_badge(selected_venue)}</div>',
        unsafe_allow_html=True,
    )
    if not selected_workshops.empty:
        st.markdown("**Workshops**")
        render_lane(selected_workshops, view_mode)
    else:
        st.markdown(
            '<div class="muted-state">No workshop records for this venue yet.</div>',
            unsafe_allow_html=True,
        )
    if not selected_calls.empty:
        st.markdown("**Calls / CFP**")
        render_lane(selected_calls, view_mode)
    if not selected_targets.empty:
        st.markdown(
            '<div class="muted-state">! Tracking target: watched from conference-source feeds; '
            'no parsed workshop page yet.</div>',
            unsafe_allow_html=True,
        )
        render_lane(selected_targets, view_mode)


def set_quick_view(kind: str, areas: list[str], venues: list[str], years: list[int]) -> None:
    st.session_state["year_choice"] = years
    st.session_state["venue_choice"] = venues
    st.session_state["area_choice"] = areas
    st.session_state["confidence_choice"] = ["high", "medium", "low"]
    st.session_state["search"] = ""
    st.session_state["view_mode"] = "Cards"
    st.session_state["actionable_only"] = False

    st.session_state["show_workshops"] = kind in {"all", "workshops"}
    st.session_state["show_proposals"] = kind in {"all", "proposals"}
    st.session_state["show_generated"] = kind in {"all", "coverage"}
    if len(areas) == 1:
        st.session_state["selected_topic"] = areas[0]


def set_rlc_quick_view(open_venues: list[str], years: list[int]) -> None:
    set_quick_view("all", ["ai_ml"], ["RLC"] if "RLC" in open_venues else open_venues, years)
    select_venue("ai_ml", "RLC")
    st.session_state["selected_topic"] = "ai_ml"


def ensure_default_view(areas: list[str], venues: list[str], years: list[int]) -> None:
    defaults = {
        "year_choice": years,
        "venue_choice": venues,
        "area_choice": areas,
        "status_choice": list(STATUS_LABELS),
        "confidence_choice": ["high", "medium", "low"],
        "search": "",
        "view_mode": "Cards",
        "actionable_only": False,
        "show_workshops": True,
        "show_proposals": True,
        "show_generated": True,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    for key in ("year_choice", "venue_choice", "area_choice", "status_choice", "confidence_choice"):
        if not st.session_state.get(key):
            st.session_state[key] = defaults[key]
    if not any(
        st.session_state.get(key)
        for key in ("show_workshops", "show_proposals", "show_generated")
    ):
        st.session_state["show_workshops"] = True
        st.session_state["show_proposals"] = True


def main() -> None:
    st.set_page_config(
        page_title="Workshop GPT",
        page_icon=str(THUMBNAIL_PATH) if THUMBNAIL_PATH.is_file() else ":mag:",
        layout="wide",
    )
    st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

    try:
        data = load_data()
    except FileNotFoundError:
        st.error("No workshop data yet. Run `python fetcher/fetch.py --offline` first.")
        return

    df = build_dataframe(data)
    if df.empty:
        st.warning("No workshop candidates found.")
        return

    render_analytics()
    render_social()
    render_header(data, df)
    render_transparency(df)

    # The assistant is the hero: full width, right under the header.
    render_chat(df)

    years = sorted(df["year"].dropna().unique())
    open_venues = sorted(df["parent_venue"].dropna().unique())
    venue_counts = df.groupby("parent_venue")["title"].count().to_dict()
    areas = sorted({area for xs in df["areas"] for area in xs})
    ensure_default_view(areas, open_venues, years)

    main_col, side_col = st.columns([3.5, 1.15], gap="large")

    with side_col:
        search = st.text_input("Search", key="search")
        render_quick_views(areas, open_venues, years)
        st.divider()
        st.markdown("### Advanced")
        year_choice = st.multiselect("Year", options=years, default=years, key="year_choice")
        venue_choice = st.multiselect(
            "Venues / sources",
            options=open_venues,
            default=open_venues,
            format_func=lambda v: f"{v} ({venue_counts.get(v, 0)})",
            key="venue_choice",
        )
        area_choice = st.multiselect(
            "Area",
            options=areas,
            default=areas,
            format_func=lambda a: AREA_LABELS.get(a, a),
            key="area_choice",
        )
        status_choice = st.multiselect(
            "Status",
            options=list(STATUS_LABELS),
            default=list(STATUS_LABELS),
            format_func=lambda s: STATUS_LABELS.get(s, s),
            key="status_choice",
        )
        confidence_choice = st.multiselect(
            "Confidence",
            options=["high", "medium", "low"],
            default=["high", "medium", "low"],
            key="confidence_choice",
        )
        view_mode = st.radio("View", options=["Cards", "Table"], horizontal=True, key="view_mode")
        show_workshops = st.toggle("Show actual workshops", value=True, key="show_workshops")
        show_proposals = st.toggle("Show calls / CFP / proposals", value=True, key="show_proposals")
        show_generated = st.toggle("Show coverage targets", value=True, key="show_generated")
        actionable_only = st.toggle("Actionable leads only", value=False, key="actionable_only")

    f = df.copy()
    f = f[f["year"].isin(year_choice)]
    if venue_choice:
        f = f[f["parent_venue"].isin(venue_choice)]
    else:
        f = f.iloc[0:0]
    f = f[f["status"].isin(status_choice)]
    f = f[f["confidence"].isin(confidence_choice)]
    if area_choice:
        area_mask = f["areas"].map(lambda xs: bool(set(xs or []) & set(area_choice)))
        f = f.loc[area_mask]
    call_mask = f["status"].isin(["cfp_open", "proposal_open"]) | (f["record_type"] == "proposal")
    target_mask = f["record_type"] == "source_gap"
    workshop_mask = (f["record_type"] == "workshop") & ~call_mask & ~target_mask
    display_mask = pd.Series(False, index=f.index)
    if show_workshops:
        display_mask |= workshop_mask
    if show_proposals:
        display_mask |= call_mask
    if show_generated:
        display_mask |= target_mask
    f = f[display_mask]
    if actionable_only:
        f = f[f["actionable"]]
    if search:
        s = search.lower()
        f = f[
            f["title"].str.lower().str.contains(s, na=False)
            | f["parent_venue"].str.lower().str.contains(s, na=False)
            | f["evidence"].str.lower().str.contains(s, na=False)
        ]

    workshops_view, calls_view, targets_view = split_record_lanes(f)
    st.caption(
        f"{len(workshops_view)} workshop records shown · "
        f"{workshops_view['parent_venue'].nunique()} workshop venues"
    )
    if f.empty:
        st.info("No workshop records match the current filters.")
        return

    status_order = {"cfp_open": 0, "confirmed": 1, "proposal_open": 2, "candidate": 3, "expected": 4}
    confidence_order = {"high": 0, "medium": 1, "low": 2}
    f = f.assign(
        _status=f["status"].map(status_order),
        _confidence=f["confidence"].map(confidence_order),
        _undated=f["next_date"].isna(),
    ).sort_values(
        ["_undated", "next_date", "year", "_status", "_confidence", "parent_venue"],
        na_position="last",
    ).drop(columns=["_status", "_confidence", "_undated"])

    with main_col:
        render_topic_browser(f, view_mode)
    with side_col:
        render_highlights(f)

    render_social_js()  # wire the copy-link button (must run after render_social)


if __name__ == "__main__":
    main()
