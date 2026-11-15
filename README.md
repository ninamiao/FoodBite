# FreeBite

FreeBite helps UCSD students discover free-food events and organize them into a personal food planner.

## Features

- Discover food-related events around UCSD.
- Extract event information from public event pages.
- Distinguish between events that provide food and food that is explicitly free.
- Validate extracted information against source evidence.
- Save events to a personal planner, including events with dates yet to be confirmed.

## Tech Stack

- **Frontend:** Next.js, React, TypeScript, Tailwind CSS
- **Backend / Scraping:** Python, BeautifulSoup
- **AI Extraction:** Google Gemini API
- **Web Scraping:** Bright Data Web Unlocker

## Getting Started

### 1. Install dependencies

```bash
npm install
```

For the Python scraper:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r scraper/requirements.txt
```

### 2. Configure environment variables

Copy the example environment file:

```bash
cp .env.example .env
```

Add your own API credentials to `.env`:

- `BRIGHTDATA_API_KEY`
- `BRIGHTDATA_ZONE`
- `GEMINI_API_KEY`
- `GEMINI_MODEL` (optional)

Never commit `.env` or expose API credentials.

### 3. Run the frontend

```bash
npm run dev
```

Open [http://localhost:3000](http://localhost:3000).

## Scraper

### Supported calendar listings

The shared Bright Data scraper accepts both the [UCSD Student Life Calendar](https://calendar.ucsd.edu/student-life)
and the [Muir College Calendar of Events](https://muir.ucsd.edu/studentlife/calendarofevents.html).
The scraper remains URL-driven; both sources use the same request configuration and save-to-`data/` flow.
Muir's live HTML structure and any linked event-detail pages have not yet been inspected, so its source-specific
coverage remains unverified until an authorized live review.

Preview the Muir listing request without contacting Bright Data:

```bash
python scraper/scrape.py "https://muir.ucsd.edu/studentlife/calendarofevents.html" --dry-run
```

After an authorized scrape, use the saved HTML and explicitly provide the listing URL to extraction:

```bash
python scraper/extract.py data/muir_ucsd_edu_studentlife_calendarofevents_html.html \
  --source-url "https://muir.ucsd.edu/studentlife/calendarofevents.html" --dry-run
```

Extraction supports the existing JSON-LD Event and event-card paths for either source. Do not assume Muir's
page layout matches those paths until the saved HTML has been reviewed.

### Fetch a webpage

Preview the request without sending it:

```bash
python scraper/scrape.py "https://example.com/events" --dry-run
```

Send one confirmed request:

```bash
python scraper/scrape.py "https://example.com/events" --confirm-request
```

### Extract events

Preview the extraction input without calling Gemini:

```bash
python scraper/extract.py data/calendar_ucsd_edu_student-life.html --source-url "https://calendar.ucsd.edu/student-life" --dry-run
```

Run a confirmed extraction:

```bash
python scraper/extract.py data/calendar_ucsd_edu_student-life.html --source-url "https://calendar.ucsd.edu/student-life" --confirm-api
```

Confirmed extraction requests may consume API credits. Review the source data and request configuration before running them.
The `--output` argument is a read-only merge base and accepts either a legacy event array or the canonical
object containing an `events` array. Extraction artifacts are written under `data/extraction_runs/`; the
canonical `data/events.json` is never replaced by an extraction run. Cross-source duplicate matches preserve
per-source evidence in optional `source_records` and `source_urls` fields. High-confidence matches require
the same occurrence date plus a shared event URL or a matching title, venue, and compatible time. Similar
same-date records with unresolved identity differences remain separate and carry a manual-review warning.

## Project Structure

```text
FreeBite/
├── app/                  # Next.js frontend
├── scraper/              # Python scraping and extraction
├── data/                 # Local source data and extraction outputs
├── .env.example          # Environment variable template
├── package.json
└── README.md
```

## Project Status

FreeBite is an ongoing hackathon project. Event extraction and validation are being improved, and the frontend planner is under development.
## Reviewed event dataset

`data/events.json` is the reviewed canonical dataset (schema version `1.2`). It is a JSON object with
`schema_version`, `source_run`, `reviewed_at`, `exclusions_file`, and an `events` array. Each
event keeps a stable `id`, the source extraction fields, field-specific
`evidence`, the original `extraction_evidence`, a derived `food_status`, and
`review_warnings` for unresolved issues. Unknown source values remain `null`.
The `conditions` array contains only explicit source-backed conditions, each
with a `type`, `scope` (`food` or `event`), exact `evidence`, and `source_url`.
An empty array means no supported condition was curated; it does not imply that
food is unlimited or that registration is never required.
Supported condition types are `limited_quantity`, `first_come_first_served`,
`rsvp_required`, `eligibility_required`, `event_participants_only`, and
`purchase_required`. Food availability conditions use `scope: "food"`; event
entry requirements use `scope: "event"` and must not be read as food conditions.

Food status values:

- `confirmed_free`: food provision and the food's free cost are both supported.
- `provided_cost_unknown`: food provision is supported, but its cost is not.
- `food_unconfirmed`: the source does not establish food provision.
- `not_provided`: use only with explicit source evidence that food is not provided.

An event's free admission or free activity does not establish that food is
free. Extraction runs remain review artifacts; only curated records belong in
`data/events.json`.

## Event inclusion and eligibility curation

The canonical dataset includes an event when its source explicitly supports
food provision or contains a useful food/beverage mention whose provision is
still uncertain. `food_unconfirmed` is reserved for those relevant mentions;
events with no food-related content are excluded. Terms that refer only to
attendee-supplied water, a sport, metaphorical wording, or food-themed exhibit
objects do not qualify as food opportunities. Excluded records are preserved
with their IDs and review reasons in `data/event_curation_exclusions.json`.

Broad unrestricted eligibility wording is normalized to `Everyone` only when
the source explicitly supports an open audience. Student-only wording remains
student-scoped (for example, `All students`); it is not broadened to `Everyone`.
The field-specific source evidence remains unchanged.

The frontend displays source-supported quantity limits and event registration
requirements as badges. An RSVP link or an RSVP recommendation alone is not
treated as proof that registration is required.
