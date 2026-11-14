This is a [Next.js](https://nextjs.org) project bootstrapped with [`create-next-app`](https://nextjs.org/docs/app/api-reference/cli/create-next-app).

## Getting Started

First, run the development server:

```bash
npm run dev
# or
yarn dev
# or
pnpm dev
# or
bun dev
```

Open [http://localhost:3000](http://localhost:3000) with your browser to see the result.

You can start editing the page by modifying `app/page.tsx`. The page auto-updates as you edit the file.

This project uses [`next/font`](https://nextjs.org/docs/app/building-your-application/optimizing/fonts) to automatically optimize and load [Geist](https://vercel.com/font), a new font family for Vercel.

## Learn More

To learn more about Next.js, take a look at the following resources:

- [Next.js Documentation](https://nextjs.org/docs) - learn about Next.js features and API.
- [Learn Next.js](https://nextjs.org/learn) - an interactive Next.js tutorial.

You can check out [the Next.js GitHub repository](https://github.com/vercel/next.js) - your feedback and contributions are welcome!

## FreeBite scraper (Bright Data)

`scraper/scrape.py` fetches one public webpage through Bright Data Web Unlocker. It reads `BRIGHTDATA_API_KEY` and `BRIGHTDATA_ZONE` from a `.env` file in the project root. Copy `.env.example` to `.env` and fill in your own values. Do not commit `.env`.

The script does not contact Bright Data unless you pass `--confirm-request`. That flag sends exactly one request and can use Bright Data credits. There is no retry.

In a new terminal:

```bash
cd /Users/miaowenxin/sand-project
source .venv/bin/activate
```

Check the configuration and print the request without sending it. Replace the URL with a real public page when you are ready. The API key is not printed.

```bash
python scraper/scrape.py "https://example.com/events" --dry-run
```

Send one real request. This uses Bright Data credits:

```bash
python scraper/scrape.py "https://example.com/events" --confirm-request
```

Successful HTML is saved under `data/` using a safe filename that will not overwrite an existing file. Errors are printed without the API key.

## FreeBite event extraction (Gemini)

`scraper/extract.py` preprocesses a saved HTML page with BeautifulSoup, then extracts event records through the installed `google-genai` SDK. It reads `GEMINI_API_KEY` and optional `GEMINI_MODEL` from the project-root `.env`; the model defaults to `gemini-3.8-flash`. Google lists this as a stable model with structured output support ([model documentation](https://ai.google.dev/gemini-api/docs/models/gemini-3.8-flash)). The SDK request has a 60-second HTTP timeout, one HTTP attempt, and automatic continuation disabled.

The preprocessor sends all usable, de-duplicated JSON-LD Event records as broad candidates rather than using a fixed food keyword list. This retains events described with varied food and drink wording and leaves the semantic decision to Gemini. When JSON-LD is unavailable, it falls back to event cards and then page text. Candidates are not automatically classified as food events by Python, so mentions such as “lunchboxes” do not imply food is served.

The event schema separates `provides_food` from `is_free`. `provides_food` is true only when the source indicates food or drinks are actually provided or served; `is_free` is true only when the source explicitly says the event or its food/drinks are free. A free event does not prove that it provides food. Each value has its own exact `evidence` quotation, and unsupported values are set to `null`.

Gemini extraction has **not yet been successfully verified**. The previous confirmed request hung while waiting for a response and was manually interrupted; it returned no result. The current code adds a finite timeout, but no new Gemini request has been made.

Preview the preprocessed input locally. This does not require a Gemini key and does not call Gemini:

```bash
python scraper/extract.py data/calendar_ucsd_edu_student-life.html --source-url "https://calendar.ucsd.edu/student-life" --dry-run
```

After reviewing the preview, this command makes one confirmed request and merges validated events into `data/events.json`:

```bash
python scraper/extract.py data/calendar_ucsd_edu_student-life.html --source-url "https://calendar.ucsd.edu/student-life" --confirm-api
```

The output file remains a JSON array of event objects. Each event contains the structured event fields and an `evidence` object with exact source quotations. Unsupported fields are set to `null`; records without a source-supported title or with invalid date/time formats are rejected. Existing array entries are preserved, duplicates are identified by title, date, location, and source URL, and a less complete duplicate will not replace a more complete record. No page or run metadata is added to the array.

## Deploy on Vercel

The easiest way to deploy your Next.js app is to use the [Vercel Platform](https://vercel.com/new?utm_medium=default-template&filter=next.js&utm_source=create-next-app&utm_campaign=create-next-app-readme) from the creators of Next.js.

Check out our [Next.js deployment documentation](https://nextjs.org/docs/app/building-your-application/deploying) for more details.
