"""Optional LLM second pass for extracting a workshop's submission deadline.

The high-precision regex (SUBMISSION_PHRASE_RE in fetch.py) only fires when a date
*immediately* follows an explicit "submission deadline" label. That keeps it from
emitting wrong dates on dense CfP/news pages, but it misses pages that phrase the
deadline less rigidly. This module fills that recall gap by asking a small LLM to
pick the real paper-submission deadline from the page's candidate dates.

Resilience by design (so a provider tightening its free tier never breaks us):
- **Multi-provider fallback chain.** Configure Gemini and/or Groq (and/or a generic
  OpenAI-compatible endpoint). We try them in order; if one errors or is rate
  limited (429/quota), we fall through to the next.
- **Graceful no-op.** No keys configured, all providers exhausted, bad JSON, network
  failure -> extract_deadline() returns None and the pipeline behaves exactly as it
  would without an LLM (regex + conference fallback). It never raises.
- **Self-limiting load.** A provider that errors is marked dead for the rest of the
  run so we stop hammering it. Combined with the caller only invoking us for
  still-unresolved workshops (and carry-forward never re-asking once solved), daily
  call volume stays tiny and shrinks over time — well inside any free tier.
- **No new pip dependency.** Both Gemini and Groq expose OpenAI-compatible chat
  endpoints; we POST JSON with stdlib urllib.

Configure via GitHub Actions secrets (all optional; set whichever you have). Tried
in this order, each falling through to the next on error/quota:
    GROQ_API_KEY       -> Groq console (free, no billing); GROQ_MODEL (default llama-3.3-70b-versatile)
    OPENROUTER_API_KEY -> openrouter.ai (free, no billing); OPENROUTER_MODEL
                          (default meta-llama/llama-3.3-70b-instruct:free)
    GEMINI_API_KEY     -> Google AI Studio; GEMINI_MODEL (default gemini-2.0-flash)
                          NOTE: Gemini's free tier needs a billing-enabled project.
    LLM_API_KEY + LLM_BASE_URL + LLM_MODEL  -> any other OpenAI-compatible endpoint
    LLM_TIMEOUT        -> seconds, default 20
"""

from __future__ import annotations

import json
import os
import re
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime
from urllib.request import Request, urlopen

_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

_PROMPT = (
    "You extract the PAPER SUBMISSION deadline for an academic workshop from snippets "
    "taken around dates on its call-for-papers page.\n"
    "Rules:\n"
    "- Return the date authors must SUBMIT their paper by.\n"
    "- IGNORE notification/acceptance, camera-ready, the workshop/event date, "
    "registration, and any date for a PREVIOUS edition/year.\n"
    "- If both an abstract and a paper deadline exist, return the PAPER one.\n"
    "- If you cannot identify it confidently, return null.\n"
    'Respond ONLY as JSON: {{"submission_deadline": "YYYY-MM-DD" or null}}.\n\n'
    "Workshop: {title} ({year})\n"
    "Snippets:\n{snippets}"
)


@dataclass(frozen=True)
class _Provider:
    name: str
    base_url: str
    model: str
    api_key: str


def _providers() -> list[_Provider]:
    """Build the ordered fallback chain from whichever keys are configured.

    Order = most-likely-to-work first (Groq and OpenRouter have real free tiers
    with no billing project; Gemini's free tier needs a billing-enabled project).
    A provider that errors is skipped for the rest of the run anyway, so order only
    decides who is tried first.
    """
    out: list[_Provider] = []
    if os.environ.get("GROQ_API_KEY"):
        out.append(_Provider(
            "groq",
            "https://api.groq.com/openai/v1",
            os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
            os.environ["GROQ_API_KEY"],
        ))
    if os.environ.get("OPENROUTER_API_KEY"):
        out.append(_Provider(
            "openrouter",
            "https://openrouter.ai/api/v1",
            os.environ.get("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free"),
            os.environ["OPENROUTER_API_KEY"],
        ))
    if os.environ.get("GEMINI_API_KEY"):
        out.append(_Provider(
            "gemini",
            "https://generativelanguage.googleapis.com/v1beta/openai",
            os.environ.get("GEMINI_MODEL", "gemini-2.0-flash"),
            os.environ["GEMINI_API_KEY"],
        ))
    if os.environ.get("LLM_API_KEY"):
        out.append(_Provider(
            "custom",
            os.environ.get("LLM_BASE_URL", "").rstrip("/"),
            os.environ.get("LLM_MODEL", "gpt-4o-mini"),
            os.environ["LLM_API_KEY"],
        ))
    return [p for p in out if p.base_url]


# Providers that errored/rate-limited this run; skipped for the remainder of it.
_dead: set[str] = set()
# Resolved (currently-valid) model id per provider, cached for the run.
_model_cache: dict[str, str] = {}


def llm_enabled() -> bool:
    return any(p.name not in _dead for p in _providers())


def _pick_model(provider: _Provider, ids: list[str]) -> str | None:
    """Choose a sensible currently-available model from a provider's live list.

    Prefers a free (`:free`) instruct-style chat model. This is what keeps us from
    breaking when a provider renames or retires the model we had pinned."""
    free = [m for m in ids if m.endswith(":free")] or ids
    preferred = ("llama", "qwen", "gemma", "mistral", "gemini", "deepseek")
    for kw in preferred:
        for m in free:
            low = m.lower()
            if kw in low and "vision" not in low and "embed" not in low:
                return m
    return free[0] if free else None


def _effective_model(provider: _Provider, timeout: float) -> str:
    """The configured model if it's still live, else an auto-picked current one.

    Resolved once per provider per run from GET {base}/models, so a pinned id going
    stale (404) never breaks us — we always send a model the provider lists today."""
    if provider.name in _model_cache:
        return _model_cache[provider.name]
    chosen = provider.model
    try:
        request = Request(
            f"{provider.base_url}/models",
            headers={
                "Authorization": f"Bearer {provider.api_key}",
                "User-Agent": "Mozilla/5.0 workshop-tracker",
            },
        )
        try:
            context = ssl.create_default_context(cafile=__import__("certifi").where())
        except Exception:
            context = ssl.create_default_context()
        with urlopen(request, timeout=timeout, context=context) as response:
            ids = [m["id"] for m in json.loads(response.read()).get("data", [])]
        if provider.model not in ids:
            chosen = _pick_model(provider, ids) or provider.model
    except Exception:
        pass  # network/list failure -> just use the configured model
    _model_cache[provider.name] = chosen
    return chosen


def _post_chat(provider: _Provider, messages: list[dict], timeout: float,
               max_tokens: int = 60, temperature: float = 0) -> str:
    body = json.dumps({
        "model": _effective_model(provider, timeout),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")
    request = Request(
        f"{provider.base_url}/chat/completions",
        data=body,
        headers={
            "Authorization": f"Bearer {provider.api_key}",
            "Content-Type": "application/json",
            # Some providers sit behind Cloudflare, which 403s (error 1010) the
            # default urllib User-Agent as a bot.
            "User-Agent": "Mozilla/5.0 workshop-tracker",
        },
    )
    try:
        import certifi

        context = ssl.create_default_context(cafile=certifi.where())
    except Exception:
        context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        payload = json.loads(response.read().decode("utf-8", "ignore"))
    return payload["choices"][0]["message"]["content"]


def _parse_iso(content: str, year: int) -> str | None:
    """Pull a YYYY-MM-DD from the reply and sanity-check the year."""
    match = re.search(r"\d{4}-\d{2}-\d{2}", content or "")
    if not match:
        return None
    value = match.group(0)
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None
    # Reject a deadline implausibly far from the workshop year (a prior edition's).
    if year and not (year - 1 <= parsed.year <= year + 1):
        return None
    return value


def complete(messages: list[dict], timeout: float | None = None,
             max_tokens: int = 400, temperature: float = 0.2) -> str | None:
    """Run a chat completion through the provider fallback chain; text or None.

    The first provider that *responds* wins; providers that error/rate-limit are
    skipped and disabled for the rest of the run. Returns None when none answer."""
    providers = [p for p in _providers() if p.name not in _dead]
    if not providers:
        return None
    timeout = timeout if timeout is not None else float(os.environ.get("LLM_TIMEOUT", "20"))
    for provider in providers:
        try:
            return _post_chat(provider, messages, timeout, max_tokens, temperature)
        except Exception as e:  # network / quota / 429 -> drop provider, try next
            _dead.add(provider.name)
            print(f"warn: llm provider {provider.name} unavailable ({e}); falling back", file=sys.stderr)
            continue
    return None


def extract_deadline(title: str, year: int, snippets: list[str], timeout: float | None = None) -> str | None:
    """Return an ISO submission deadline an LLM is confident about, else None."""
    if not snippets:
        return None
    prompt = _PROMPT.format(
        title=title or "(unknown)",
        year=year or "(unknown)",
        snippets="\n".join(f"- {s}" for s in snippets[:25]),
    )
    content = complete([{"role": "user", "content": prompt}], timeout, max_tokens=60, temperature=0)
    return _parse_iso(content, int(year or 0)) if content is not None else None


# Fixed taxonomy so themes aggregate into a handful of browsable groups instead of
# fragmenting. Keep in sync with fetch.py's keyword themes.
THEME_TAXONOMY = [
    "LLM Agents", "Alignment & Safety", "LLMs & Language", "Reasoning",
    "Reinforcement Learning", "Multimodal & Vision", "Generative Models",
    "AI for Science", "Robotics", "Graphs & Geometry", "Efficiency & Systems",
    "Data & Benchmarks", "Fairness & Society", "Theory & Optimization",
    "Time Series", "Speech & Audio", "Other",
]
_TAXONOMY_LOOKUP = {t.lower(): t for t in THEME_TAXONOMY}

THEME_PROMPT = (
    "Pick the SINGLE best-fitting theme for this academic workshop from this exact list:\n"
    + ", ".join(THEME_TAXONOMY) + ".\n"
    "Expand any acronym in the title to judge its topic. Reply with ONLY the chosen "
    "theme, copied exactly from the list.\n\nWorkshop title: {title}\nResearch area: {area}"
)


def extract_theme(title: str, area: str, timeout: float | None = None) -> str | None:
    """LLM sub-theme label (from the fixed taxonomy) for a workshop, or None."""
    if not title:
        return None
    prompt = THEME_PROMPT.format(title=title, area=area or "(general)")
    content = complete([{"role": "user", "content": prompt}], timeout, max_tokens=16, temperature=0)
    if not content:
        return None
    cleaned = re.sub(r"[\"'\n].*", "", content.strip()).strip(" .:-").lower()
    # Accept an exact taxonomy match, else a contained one; otherwise give up.
    if cleaned in _TAXONOMY_LOOKUP:
        return _TAXONOMY_LOOKUP[cleaned]
    for key, label in _TAXONOMY_LOOKUP.items():
        if key != "other" and key in cleaned:
            return label
    return None
