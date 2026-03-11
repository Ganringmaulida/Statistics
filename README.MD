# Sports Prediction Engine — G+1

## Real-Time Data Sources (No API Key Required)

| Sport  | Stats Source         | Fixtures Source | Key Required? |
|--------|---------------------|-----------------|---------------|
| EPL    | Understat.com (xG)  | ESPN API        | ❌ No         |
| UCL    | Understat.com (xG)  | ESPN API        | ❌ No         |
| NBA    | stats.nba.com       | ESPN API        | ❌ No         |
| NHL    | api-web.nhle.com    | NHL Official    | ❌ No         |
| Odds   | The-Odds-API        | —               | ✅ Free tier  |

## Setup

```bash
pip install -r requirements.txt
python app.py
```

## Optional API Keys (config.yaml)

```yaml
the_odds_api:
  api_key: "your_key"   # https://the-odds-api.com — free 500 req/month

api_football:
  api_key: "your_key"   # https://api-football.com — free 100 req/day (injuries)
```

## G+1 Improvements

- ✅ Real-time stats: Understat / NHL API / NBA Stats / ESPN
- ✅ Dixon-Coles correction (ρ = -0.13) for soccer Poisson model
- ✅ Backtester: records all predictions, calculates Brier Score / Log Loss / ROI
- ✅ Data source badges in UI
- ✅ Cache TTL reduced (6h stats, 3h fixtures)

## Data Flow

```
Understat ──┐
NHL API  ───┤→ get_team_stats()
NBA Stats ──┤
ESPN     ───┘

ESPN     ──┐
NHL API  ───┤→ get_fixtures()
API-Football┘

The-Odds-API → get_odds()

→ build_profiles()        [strength_profiler]
→ calculate_probability() [probability_engine + Dixon-Coles]
→ recommend_bet()         [bet_selector]
→ backtester.record()     [backtester]
```

## Backtester Usage

```python
from analytics.backtester import Backtester
bt = Backtester()

# After results come in:
bt.update_result("Arsenal_Chelsea_2026-03-10", home_score=2, away_score=1)

# Generate report:
bt.print_summary()
```

Or via CLI: `python app.py --backtest`