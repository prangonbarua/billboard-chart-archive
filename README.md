# Billboard Chart Archive

A web app for exploring decades of U.S. music chart history — every Hot 100 and Billboard 200 chart week, searchable by song, artist, or date, with cover art and chart-run statistics.

## Features

- Full Hot 100 archive and Billboard 200 album chart archive (CSV datasets included, updated weekly)
- Search any song or artist and see complete chart runs: debut, peak, weeks on chart
- Browse any chart week in history
- Cover art and metadata lookups
- Export results

## Quick start

```bash
pip install -r requirements.txt
python app.py
```

Then open http://localhost:5001.

Use Python 3.12, matching the Dockerfile and the weekly workflow — the pinned
pandas and numpy publish no wheels for 3.13.

Configuration lives in `.env` (see `.env.example`). The app runs without API keys; they only enrich metadata.

## Tests

```bash
pip install -r requirements-dev.txt
python3 -m pytest
python3 scripts/verify_charts.py    # data integrity across every chart
```

## Docker

```bash
docker build -t billboard-archive .
docker run -d -p 5001:5001 billboard-archive
```

## Data

The chart datasets live in `data/`:

| File | Contents |
|---|---|
| `data/hot100.csv` | Weekly Hot 100 singles charts |
| `data/billboard200.csv` | Weekly Billboard 200 album charts |

Update scripts are in `scripts/` and should be run from the repo root, e.g.:

```bash
python scripts/weekly_update.py
```

## Structure

```
app.py            Flask app (serves the site and API)
data/             Chart history datasets
scripts/          Data update and scraping utilities
static/           CSS and fonts
templates/        Pages
```
