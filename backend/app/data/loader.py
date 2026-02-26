"""
Main data loading pipeline — combines nflverse, FO, and PFR data
into the database. Run this to backfill historical data or refresh current season.
"""
from __future__ import annotations
import logging
import pandas as pd
from sqlalchemy.orm import Session
from app.db.models import Team, Game, TeamWeekStats
from app.data.nflverse import load_schedules, load_pbp_epa
from app.data.football_outsiders import scrape_dvoa_season, get_latest_dvoa

logger = logging.getLogger(__name__)

NFL_TEAMS = {
    "ARI": "Arizona Cardinals",    "ATL": "Atlanta Falcons",
    "BAL": "Baltimore Ravens",     "BUF": "Buffalo Bills",
    "CAR": "Carolina Panthers",    "CHI": "Chicago Bears",
    "CIN": "Cincinnati Bengals",   "CLE": "Cleveland Browns",
    "DAL": "Dallas Cowboys",       "DEN": "Denver Broncos",
    "DET": "Detroit Lions",        "GB":  "Green Bay Packers",
    "HOU": "Houston Texans",       "IND": "Indianapolis Colts",
    "JAX": "Jacksonville Jaguars", "KC":  "Kansas City Chiefs",
    "LAC": "Los Angeles Chargers", "LAR": "Los Angeles Rams",
    "LV":  "Las Vegas Raiders",    "MIA": "Miami Dolphins",
    "MIN": "Minnesota Vikings",    "NE":  "New England Patriots",
    "NO":  "New Orleans Saints",   "NYG": "New York Giants",
    "NYJ": "New York Jets",        "PHI": "Philadelphia Eagles",
    "PIT": "Pittsburgh Steelers",  "SEA": "Seattle Seahawks",
    "SF":  "San Francisco 49ers",  "TB":  "Tampa Bay Buccaneers",
    "TEN": "Tennessee Titans",     "WAS": "Washington Commanders",
}

TEAM_CONFERENCES = {
    "ARI": ("NFC", "NFC West"),   "ATL": ("NFC", "NFC South"),
    "BAL": ("AFC", "AFC North"),  "BUF": ("AFC", "AFC East"),
    "CAR": ("NFC", "NFC South"),  "CHI": ("NFC", "NFC North"),
    "CIN": ("AFC", "AFC North"),  "CLE": ("AFC", "AFC North"),
    "DAL": ("NFC", "NFC East"),   "DEN": ("AFC", "AFC West"),
    "DET": ("NFC", "NFC North"),  "GB":  ("NFC", "NFC North"),
    "HOU": ("AFC", "AFC South"),  "IND": ("AFC", "AFC South"),
    "JAX": ("AFC", "AFC South"),  "KC":  ("AFC", "AFC West"),
    "LAC": ("AFC", "AFC West"),   "LAR": ("NFC", "NFC West"),
    "LV":  ("AFC", "AFC West"),   "MIA": ("AFC", "AFC East"),
    "MIN": ("NFC", "NFC North"),  "NE":  ("AFC", "AFC East"),
    "NO":  ("NFC", "NFC South"),  "NYG": ("NFC", "NFC East"),
    "NYJ": ("AFC", "AFC East"),   "PHI": ("NFC", "NFC East"),
    "PIT": ("AFC", "AFC North"),  "SEA": ("NFC", "NFC West"),
    "SF":  ("NFC", "NFC West"),   "TB":  ("NFC", "NFC South"),
    "TEN": ("AFC", "AFC South"),  "WAS": ("NFC", "NFC East"),
}


def seed_teams(db: Session) -> dict[str, int]:
    """Ensure all 32 teams exist in DB. Returns abbr→id mapping."""
    abbr_to_id = {}
    for abbr, full_name in NFL_TEAMS.items():
        team = db.query(Team).filter_by(abbr=abbr).first()
        if not team:
            conf, div = TEAM_CONFERENCES.get(abbr, (None, None))
            team = Team(abbr=abbr, full_name=full_name, conference=conf, division=div)
            db.add(team)
            db.flush()
        abbr_to_id[abbr] = team.id
    db.commit()
    logger.info("Seeded %d teams", len(abbr_to_id))
    return abbr_to_id


def load_season_schedule(db: Session, season: int, team_map: dict[str, int]) -> None:
    """Load or update schedule/results for a season from nflverse."""
    import datetime
    df = load_schedules(seasons=[season])
    if df.empty:
        logger.warning("No schedule data for season %d", season)
        return

    count = 0
    for _, row in df.iterrows():
        home_id = team_map.get(row["home_team"])
        away_id = team_map.get(row["away_team"])
        if not home_id or not away_id:
            continue

        game = db.query(Game).filter_by(
            season=season, week=int(row["week"]), home_team_id=home_id
        ).first()

        game_date = None
        if pd.notna(row.get("gameday")):
            try:
                game_date = datetime.date.fromisoformat(str(row["gameday"]))
            except (ValueError, TypeError):
                pass

        home_score = int(row["home_score"]) if pd.notna(row.get("home_score")) else None
        away_score = int(row["away_score"]) if pd.notna(row.get("away_score")) else None
        home_win = None
        if home_score is not None and away_score is not None:
            home_win = home_score > away_score

        if game:
            game.home_score = home_score
            game.away_score = away_score
            game.home_win = home_win
            game.game_date = game_date
        else:
            game = Game(
                season=season,
                week=int(row["week"]),
                game_date=game_date,
                home_team_id=home_id,
                away_team_id=away_id,
                home_score=home_score,
                away_score=away_score,
                home_win=home_win,
                is_neutral=bool(row.get("neutral_site", False)),
            )
            db.add(game)
            count += 1

    db.commit()
    logger.info("Loaded %d new games for season %d", count, season)


def _compute_stats_from_schedules(schedules: pd.DataFrame) -> pd.DataFrame:
    """
    Derive per-team per-week stats entirely from nflverse schedule data.
    Returns DataFrame: team, season, week, point_diff, recent_form, rest_days, srs
    """
    if schedules.empty:
        return pd.DataFrame()

    sched = schedules.copy()
    # Only completed games
    completed = sched[sched["home_score"].notna() & sched["away_score"].notna()].copy()
    completed["home_score"] = completed["home_score"].astype(float)
    completed["away_score"] = completed["away_score"].astype(float)

    # Build one row per team per game
    home_rows = completed[["season", "week", "home_team", "away_team", "home_score", "away_score"]].copy()
    home_rows.rename(columns={"home_team": "team", "away_team": "opponent"}, inplace=True)
    home_rows["point_diff"] = home_rows["home_score"] - home_rows["away_score"]
    home_rows["is_home"] = True

    away_rows = completed[["season", "week", "away_team", "home_team", "away_score", "home_score"]].copy()
    away_rows.rename(columns={"away_team": "team", "home_team": "opponent"}, inplace=True)
    away_rows["point_diff"] = away_rows["away_score"] - away_rows["home_score"]
    away_rows["is_home"] = False

    games = pd.concat([home_rows, away_rows], ignore_index=True)
    games = games.sort_values(["team", "season", "week"])

    # Rolling 4-game recent form (uses prior games, not current)
    games["recent_form"] = (
        games.groupby(["team", "season"])["point_diff"]
        .transform(lambda x: x.shift(1).rolling(4, min_periods=1).mean())
    )

    # Rest days: weeks between games * 7 (first game = 10 days)
    games["prev_week"] = games.groupby(["team", "season"])["week"].shift(1)
    games["rest_days"] = ((games["week"] - games["prev_week"]) * 7).fillna(10).astype(int)

    # Compute SRS per team per season: iterative MOV + SOS adjustment (3 iterations)
    srs_map: dict[tuple, float] = {}
    for (season_val,), grp in games.groupby(["season"]):
        team_mov = grp.groupby("team")["point_diff"].mean().to_dict()
        srs = {t: v for t, v in team_mov.items()}
        for _ in range(3):
            new_srs: dict[str, float] = {}
            for team, tg in grp.groupby("team"):
                sos = tg["opponent"].map(lambda o: srs.get(o, 0.0)).mean()
                new_srs[team] = team_mov.get(team, 0.0) + sos * 0.5
            srs = new_srs
        for team, val in srs.items():
            srs_map[(team, int(season_val))] = val

    games["srs"] = games.apply(
        lambda r: srs_map.get((r["team"], int(r["season"])), 0.0), axis=1
    )

    return games[["team", "season", "week", "point_diff", "recent_form", "rest_days", "srs"]]


def load_team_stats(db: Session, season: int, team_map: dict[str, int], include_dvoa: bool = False) -> None:
    """
    Build TeamWeekStats from nflverse EPA + schedule-derived stats.
    DVOA is optional (off by default — FO blocks scrapers).
    PFR is no longer used; point diff, SRS, and rest are computed from nflverse schedules.
    """
    schedules = load_schedules(seasons=[season])
    epa_df = load_pbp_epa(season)
    dvoa_df = scrape_dvoa_season(season) if include_dvoa else pd.DataFrame()
    sched_stats = _compute_stats_from_schedules(schedules)

    # Build rest days for all team-weeks (including unplayed/future games)
    rest_days_map: dict[tuple, int] = {}
    if not schedules.empty:
        all_sched = schedules.sort_values(["season", "week"])
        all_teams = set(all_sched["home_team"].tolist()) | set(all_sched["away_team"].tolist())
        for team in all_teams:
            team_games = all_sched[
                (all_sched["home_team"] == team) | (all_sched["away_team"] == team)
            ].sort_values("week")
            prev_week = None
            for _, row in team_games.iterrows():
                w = int(row["week"])
                rest_days_map[(team, season, w)] = (
                    10 if prev_week is None else int((w - prev_week) * 7)
                )
                prev_week = w

    # Collect all team-weeks that appear in EPA data or schedule
    all_team_weeks: set[tuple] = set()
    if not epa_df.empty:
        for _, row in epa_df.iterrows():
            all_team_weeks.add((str(row["team"]), int(row["week"])))
    if not sched_stats.empty:
        for _, row in sched_stats.iterrows():
            all_team_weeks.add((str(row["team"]), int(row["week"])))

    # Index lookup DataFrames for fast access
    epa_idx = (
        epa_df.set_index(["team", "week"]) if not epa_df.empty else pd.DataFrame()
    )
    sched_idx = (
        sched_stats.set_index(["team", "week"]) if not sched_stats.empty else pd.DataFrame()
    )
    dvoa_idx = (
        dvoa_df.set_index(["team", "week"]) if not dvoa_df.empty else pd.DataFrame()
    )

    upserted = 0
    for (team_abbr, week) in sorted(all_team_weeks):
        team_id = team_map.get(team_abbr)
        if not team_id:
            continue

        stats = db.query(TeamWeekStats).filter_by(
            team_id=team_id, season=season, week=week
        ).first()
        if not stats:
            stats = TeamWeekStats(team_id=team_id, season=season, week=week)
            db.add(stats)

        key = (team_abbr, week)

        # EPA
        if not epa_idx.empty and key in epa_idx.index:
            row = epa_idx.loc[key]
            stats.off_epa_per_play = float(row.get("off_epa_per_play") or 0)
            stats.def_epa_per_play = float(row.get("def_epa_per_play") or 0)

        # Schedule-derived stats
        if not sched_idx.empty and key in sched_idx.index:
            row = sched_idx.loc[key]
            stats.point_differential = float(row.get("point_diff") or 0)
            stats.recent_form = float(row.get("recent_form") or 0)
            stats.srs = float(row.get("srs") or 0)

        # DVOA (optional)
        if not dvoa_idx.empty and key in dvoa_idx.index:
            row = dvoa_idx.loc[key]
            stats.total_dvoa = row.get("total_dvoa")
            stats.offense_dvoa = row.get("offense_dvoa")
            stats.defense_dvoa = row.get("defense_dvoa")
            stats.st_dvoa = row.get("st_dvoa")

        stats.rest_days = rest_days_map.get((team_abbr, season, week), 7)
        upserted += 1

    db.commit()
    logger.info("Upserted %d team-week stats records for season %d", upserted, season)


def backfill_historical(db: Session, seasons: list[int] | None = None, include_dvoa: bool = False) -> None:
    """Backfill all data for historical seasons (2015–2024)."""
    if seasons is None:
        seasons = list(range(2015, 2025))

    team_map = seed_teams(db)

    for season in seasons:
        logger.info("=== Backfilling season %d ===", season)
        load_season_schedule(db, season, team_map)
        load_team_stats(db, season, team_map, include_dvoa=include_dvoa)

    logger.info("Backfill complete for seasons %s", seasons)


def refresh_current_season(db: Session, season: int, current_week: int, include_dvoa: bool = False) -> None:
    """Refresh data for the current season up to the given week."""
    team_map = seed_teams(db)
    load_season_schedule(db, season, team_map)
    load_team_stats(db, season, team_map, include_dvoa=include_dvoa)
    logger.info("Refreshed season %d through week %d", season, current_week)
