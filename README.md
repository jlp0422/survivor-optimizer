# NFL Survivor Pool Optimizer

Monte Carlo-based optimizer for NFL survivor pools. Supports single-entry and multi-entry portfolio optimization across the full season.

## Stack

- **Backend**: Python 3.12, FastAPI, SQLite (SQLAlchemy), scikit-learn
- **Frontend**: React 18, Vite, TypeScript, Tailwind CSS, Recharts
- **Data**: nflverse-data (parquet), Football Outsiders DVOA, Pro Football Reference SRS

## Quick Start

### 1. Install backend

```bash
cd backend
uv sync          # or: pip install -e .
```

### 2. Run one-time setup (backfill + train model)

```bash
# From backend/
python scripts/setup.py --seasons 2015 2016 2017 2018 2019 2020 2021 2022 2023 2024 --val-season 2023
```

This will:
- Initialize the SQLite database
- Download nflverse schedule + EPA data (cached to `data/cache/`)
- Scrape Football Outsiders DVOA (rate-limited)
- Scrape PFR SRS data
- Train logistic regression win probability model (target Brier < 0.22)
- Update win probabilities for 2024 season

### 3. Start the API

```bash
cd backend
uvicorn app.main:app --reload
# API at http://localhost:8000
# Docs at http://localhost:8000/docs
```

### 4. Start the frontend

```bash
cd frontend
npm install
npm run dev
# App at http://localhost:5173
```

## Weekly Update Flow

After each week's games complete:

```bash
curl -X POST http://localhost:8000/api/results/update/WEEK \
  -H "Content-Type: application/json" \
  -d '{"season": 2024, "week": WEEK}'
```

Or click **Refresh Results** in the dashboard.

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/schedule/{season}` | Full season schedule with win probs |
| GET | `/api/picks/recommend/{week}?season=` | Recommended picks per entry |
| POST | `/api/picks/submit` | Submit a pick for an entry |
| POST | `/api/results/update/{week}` | Refresh results + win probs |
| GET | `/api/teams/{team}/schedule?season=` | Team's schedule + availability |
| GET | `/api/simulate/{week}?season=` | Run Monte Carlo simulation |
| GET | `/api/entries?season=` | List all entries |
| POST | `/api/entries` | Create new entry |

## Model

Logistic regression trained on 2015–2024 seasons with Platt scaling calibration.

Features: DVOA differential, EPA per play differential, SRS differential, home field, rest days, recent form.

Target metric: Brier score < 0.22 on held-out season (random baseline ≈ 0.25).

## Optimizer

- **Single entry**: Beam search over pick sequences, N=50,000 Monte Carlo simulations
- **Multi-entry portfolio**: Greedy marginal coverage — subsequent entries penalized for duplicating picks from prior entries
- **Season-level**: Forward-looking strategy uses all remaining weeks; scarcity analysis identifies bottleneck weeks
