# UMass Activity Hours

Static site showing operating hours for UMass Amherst swim, climbing, and ice skating facilities. Data refreshed daily by a GitHub Action.

## Local development

Frontend only (uses `tests/fixtures/hours.sample.json`):
```
python -m http.server 8000
# open http://localhost:8000/?fixture=1
```

Run scraper:
```
cd scraper
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
playwright install chromium
python -m scraper.main
```

## Deploy

Push to `main`. GitHub Pages serves the repo root. The scrape workflow runs daily and commits `data/hours.json`.
