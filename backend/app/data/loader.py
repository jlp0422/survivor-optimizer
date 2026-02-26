"""
Main data loading pipeline — combines nflverse, FO, and PFR data
into the database. Run this to backfill historical data or refresh current season.
"""
from __future__ import annotations
import logging
from sqlalchemy.orm import Session
from app.db.models import Team, Game, TeamWeekStats
from app.data.nflverse import load_schedules, load_pbp_epa
from app.data.football_outsiders import scrape_dvoa_season, get_latest_dvoa
from app.data.pro_football_reference import scrape_srs_season, compute_point_differentials

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


def load_team_stats(db: Session, season: int, team_map: dict[str, int]) -> None:
    """
    Combine DVOA, EPA, SRS, and point differential data into TeamWeekStats.
    """
    # Load all data sources
    epa_df = load_pbp_epa(season)
    dvoa_df = scrape_dvoa_season(season)
    srs_df = scrape_srs_season(season)
    pdiff_df = compute_point_differentials(season)

    # Get schedule for rest days computation
    schedules = load_schedules(seasons=[season])

    # Build rest days lookup
    rest_days_map: dict[tuple, int] = {}
    if not schedules.empty:
        schedules_sorted = schedules.sort_values(["season", "week"])
        for team in schedules_sorted["home_team"].unique():
            team_games = schedules_sorted[
                (schedules_sorted["home_team"] == team) |
                (schedules_sorted["away_team"] == team)
            ].copy()
            team_games = team_games.sort_values("week")
            for i, row in enumerate(team_games.itertuples()):
                if i == 0:
                    rest_days_map[(team, season, row.week)] = 10  # assume full rest first week
                else:
                    prev_week = team_games.iloc[i - 1]["week"]
                    week_diff = row.week - prev_week
                    rest_days_map[(team, season, row.week)] = week_diff * 7

    # Get all weeks from any source
    all_team_weeks: set[tuple] = set()
    for df, team_col, week_col in [
        (epa_df, "team", "week"),
        (dvoa_df, "team", "week"),
        (pdiff_df, "team", "week"),
    ]:
        if not df.empty and week_col in df.columns:
            for _, row in df.iterrows():
                all_team_weeks.add((str(row[team_col]), int(row[week_col])))

    # SRS is season-level, not week-level
    srs_lookup = {}
    if not srs_df.empty:
        for _, row in srs_df.iterrows():
            srs_lookup[str(row["team"])] = {
                "srs": row.get("srs"),
                "mov": row.get("mov"),
            }

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

        # EPA
        if not epa_df.empty:
            epa_row = epa_df[
                (epa_df["team"] == team_abbr) & (epa_df["week"] == week)
            ]
            if not epa_row.empty:
                stats.off_epa_per_play = float(epa_row.iloc[0].get("off_epa_per_play", 0) or 0)
                stats.def_epa_per_play = float(epa_row.iloc[0].get("def_epa_per_play", 0) or 0)

        # DVOA
        if not dvoa_df.empty:
            dvoa_row = dvoa_df[
                (dvoa_df["team"] == team_abbr) & (dvoa_df["week"] == week)
            ]
            if not dvoa_row.empty:
                stats.total_dvoa = dvoa_row.iloc[0].get("total_dvoa")
                stats.offense_dvoa = dvoa_row.iloc[0].get("offense_dvoa")
                stats.defense_dvoa = dvoa_row.iloc[0].get("defense_dvoa")
                stats.st_dvoa = dvoa_row.iloc[0].get("st_dvoa")

        # Point diff + recent form
        if not pdiff_df.empty:
            pdiff_row = pdiff_df[
                (pdiff_df["team"] == team_abbr) & (pdiff_df["week"] == week)
            ]
            if not pdiff_row.empty:
                stats.point_differential = pdiff_row.iloc[0].get("point_diff")
                stats.recent_form = pdiff_row.iloc[0].get("recent_form")

        # SRS (season-level)
        if team_abbr in srs_lookup:
            stats.srs = srs_lookup[team_abbr].get("srs")

        # Rest days
        stats.rest_days = rest_days_map.get((team_abbr, season, week), 7)
        upserted += 1

    db.commit()
    logger.info("Upserted %d team-week stats records for season %d", upserted, season)


def backfill_historical(db: Session, seasons: list[int] | None = None) -> None:
    """Backfill all data for historical seasons (2015–2024)."""
    if seasons is None:
        seasons = list(range(2015, 2025))

    team_map = seed_teams(db)

    for season in seasons:
        logger.info("=== Backfilling season %d ===", season)
        load_season_schedule(db, season, team_map)
        load_team_stats(db, season, team_map)

    logger.info("Backfill complete for seasons %s", seasons)


def refresh_current_season(db: Session, season: int, current_week: int) -> None:
    """Refresh data for the current season up to the given week."""
    team_map = seed_teams(db)
    load_season_schedule(db, season, team_map)
    load_team_stats(db, season, team_map)
    logger.info("Refreshed season %d through week %d", season, current_week)
