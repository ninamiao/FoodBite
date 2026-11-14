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