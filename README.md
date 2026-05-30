# Workshop GPT

![Workshop GPT](assets/thumbnail.png)

A list of academic ML/CS workshops with their submission deadlines and locations,
each mapped to its parent conference. It rebuilds daily from public sources, and
includes an assistant you can ask in plain English.

There is no single list of academic workshops: each one runs its own call for
papers, with its own deadline, on its own page (OpenReview, a GitHub site, or a
personal homepage). Workshop GPT collects them in one place so you don't find out
about a workshop the week after its deadline.

Live app: <https://workshop-gpt-madhava.streamlit.app/> ·
Discovery page: <https://krimler.github.io/workshop-tracker/> ·
Maintained by [Madhava Gaikwad](https://www.linkedin.com/in/alignops/).

## What it tracks

Workshops across nine areas (AI/ML, theory, security, systems, networking,
databases, software engineering, distributed systems, biomedical), for the
current and next conference year. Conference deadlines themselves live in a
separate dashboard; this tracks the workshops held at those conferences.

Each record has: title, parent conference, year, area(s), sub-theme, submission
deadline, workshop date, location, status, and source links.

## How the data is built

`fetcher/fetch.py` runs a pipeline, not a web search:

1. **Discover** — parse OpenReview's public listing and the upstream conference
   feeds (via `conference_sources.json`, default `paper_tracker/data/conferences.json`),
   plus curated seeds in `workshop_seeds.json` and `venue_watchlist.json`.
2. **Inherit from the parent conference** — a workshop's location and event dates
   default to its conference's (from the structured feeds). Anything scraped for
   the workshop itself overrides this.
3. **Find the real deadline**, in order of trust (`deadline_source`):
   - `openreview` — read from the workshop's OpenReview group metadata
     (e.g. its `date` field, "Submission Deadline: May 13 2026").
   - `official_page` — high-precision extraction from the workshop's own site:
     a date is only taken when it directly follows a "submission deadline" label,
     so dense CfP/news pages don't produce wrong dates.
   - `llm` — optional fallback: a small LLM reads the page's date snippets when
     the regex finds nothing (see *LLM configuration*).
   - `conference` — labeled fallback. When nothing above is found, the parent
     conference's deadline is shown, marked "conference deadline · workshop TBD".
4. **Theme** — each workshop gets a browsable sub-theme (keyword tagger for the
   obvious ones, optional LLM for opaque acronyms), from a fixed taxonomy.

The run is incremental: results are carried forward, scraped pages and OpenReview
groups are re-checked on a staleness window, and per-record date/URL lists are
capped, so the file doesn't grow without bound and a daily run finishes in minutes.

## The assistant

The app has an "Ask Workshop GPT" chat. It retrieves the most relevant workshop
records for your question and answers only from those (no invented deadlines).
Guardrails: the key stays server-side, per-session and global daily call caps
protect the free-tier quota, and a multi-provider fallback chain is used. With no
key configured the chat is simply offline; the rest of the app works.

## LLM configuration (optional)

All LLM use (deadline fallback, theme refinement, chat) is optional and off by
default. Set any of these as environment variables (or Streamlit/Actions secrets);
they're tried in order, falling through on error or rate-limit:

```text
GROQ_API_KEY        # groq.com, free tier; GROQ_MODEL (default llama-3.3-70b-versatile)
OPENROUTER_API_KEY  # openrouter.ai, free tier; OPENROUTER_MODEL
GEMINI_API_KEY      # Google AI Studio; GEMINI_MODEL (needs a billing-enabled project)
LLM_API_KEY + LLM_BASE_URL + LLM_MODEL   # any other OpenAI-compatible endpoint
```

No new Python dependency: these are OpenAI-compatible HTTP endpoints called with
the standard library.

## Layout

```text
fetcher/fetch.py        # discovery + enrichment pipeline
fetcher/llm_extract.py  # optional multi-provider LLM client (deadline, theme, chat)
app.py                  # Streamlit app + assistant
conference_sources.json # conference feeds used for venue targets and inherited dates
workshop_seeds.json     # known workshop sources by area
venue_watchlist.json    # broad coverage targets by area
data/workshops.json     # generated snapshot (the app reads this)
docs/                   # static landing page + crawler files (GitHub Pages)
assets/                 # logo, thumbnail, chat avatars
.github/workflows/      # refresh-workshops.yml (daily fetch) + pages.yml (Pages deploy)
```

## Running locally

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python fetcher/fetch.py            # live refresh
python fetcher/fetch.py --offline  # offline placeholder snapshot
# optional LLM passes:
# GROQ_API_KEY=... python fetcher/fetch.py --enrich-llm-limit 60 --enrich-theme-limit 60

streamlit run app.py
```

Useful flags: `--enrich-openreview-limit`, `--enrich-delay-seconds`,
`--enrich-official-limit`, `--enrich-llm-limit`, `--enrich-theme-limit`.

## Deployment

1. **GitHub Actions** (`refresh-workshops.yml`) runs the fetcher daily and commits
   `data/workshops.json` and `docs/workshops.json`. Add `GROQ_API_KEY` /
   `OPENROUTER_API_KEY` as repo secrets to enable the LLM passes.
2. **Streamlit Community Cloud** deploys `app.py`. Add the same key under the app's
   Secrets to enable the chat.
3. **GitHub Pages** (`pages.yml`, Settings → Pages → Source: GitHub Actions)
   publishes `docs/` as the indexable, AI-discoverable front door.

## Editing sources

- `conference_sources.json` — the conference feeds used for venue discovery and
  inherited dates (default: the adjacent `paper_tracker/data/conferences.json`).
- `workshop_seeds.json` — known workshop sources, each with likely official domains.
- `venue_watchlist.json` — broad coverage targets so top venues stay visible while
  parsers mature.

## Contact

To add a venue or send feedback, email **yavan [at] outlook [dot] com**.

Workshop dates and deadlines should be verified on the linked official source
before submitting.
