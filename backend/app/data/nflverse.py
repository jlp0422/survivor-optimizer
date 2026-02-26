"""
Load data from nflverse via nfl_data_py — the official Python interface.
Handles URL fetching, caching, and parquet loading automatically.
"""
from __future__ import annotations
import logging
from pathlib import Path
from typing import Optional
import pandas as pd
import nfl_data_py as nfl

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# Canonical team abbreviation normalization
TEAM_ABBR_MAP = {
    "LA":  "LAR", "LAR": "LAR", "SD": "LAC", "OAK": "LV",
    "STL": "LAR", "JAC": "JAX",
}


def _normalize_team(abbr: str) -> str:
    if not isinstance(abbr, str):
        return abbr
    return TEAM_ABBR_MAP.get(abbr, abbr)


ALL_SEASONS = list(range(1999, 2026))


def load_schedules(seasons: Optional[list[int]] = None) -> pd.DataFrame:
    """
    Return schedule DataFrame. Columns include:
    season, week, game_type, gameday, home_team, away_team,
    home_score, away_score, result, neutral_site

    Always fetches the full range and caches it so per-season calls hit the cache.
    """
    cache_path = CACHE_DIR / "schedules.parquet"

    # Check cache (refresh if > 6 hours old)
    import time
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 6:
            logger.debug("Loading schedules from cache")
            df = pd.read_parquet(cache_path)
            if seasons:
                df = df[df["season"].isin(seasons)]
            return df.reset_index(drop=True)

    # Always fetch the full history so subsequent per-season calls hit cache
    fetch_seasons = ALL_SEASONS
    logger.info("Fetching full schedule history via nfl_data_py (%d seasons)", len(fetch_seasons))
    df = nfl.import_schedules(fetch_seasons)

    df["home_team"] = df["home_team"].map(_normalize_team)
    df["away_team"] = df["away_team"].map(_normalize_team)

    # Filter to regular season + playoffs
    if "game_type" in df.columns:
        df = df[df["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])].copy()

    df.to_parquet(cache_path, index=False)
    return df.reset_index(drop=True)


def load_pbp_epa(season: int) -> pd.DataFrame:
    """
    Load play-by-play for a season and aggregate to team-week EPA per play.
    Returns DataFrame: season, week, team, off_epa_per_play, def_epa_per_play
    """
    cache_path = CACHE_DIR / f"epa_{season}.parquet"

    import time
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        max_age = 168 if season < 2024 else 12
        if age_hours < max_age:
            logger.debug("Loading EPA %d from cache", season)
            return pd.read_parquet(cache_path)

    logger.info("Fetching EPA data for season %d via nfl_data_py", season)
    try:
        pbp = nfl.import_pbp_data(
            [season],
            columns=["season", "week", "season_type", "posteam", "defteam", "epa"],
            downcast=True,
        )
    except Exception as e:
        logger.warning("Could not load PBP for %d: %s", season, e)
        return pd.DataFrame()

    pbp = pbp[
        (pbp["season_type"] == "REG") &
        pbp["epa"].notna() &
        pbp["posteam"].notna()
    ].copy()

    pbp["posteam"] = pbp["posteam"].map(_normalize_team)
    pbp["defteam"] = pbp["defteam"].map(_normalize_team)

    off_epa = (
        pbp.groupby(["season", "week", "posteam"])["epa"]
        .mean()
        .reset_index()
        .rename(columns={"posteam": "team", "epa": "off_epa_per_play"})
    )

    def_epa = (
        pbp.groupby(["season", "week", "defteam"])["epa"]
        .mean()
        .reset_index()
        .rename(columns={"defteam": "team", "epa": "def_epa_per_play"})
    )

    merged = off_epa.merge(def_epa, on=["season", "week", "team"], how="outer")
    merged.to_parquet(cache_path, index=False)
    return merged


def load_epa_multi_season(seasons: list[int]) -> pd.DataFrame:
    """Load and concatenate EPA data for multiple seasons."""
    frames = []
    for season in seasons:
        df = load_pbp_epa(season)
        if not df.empty:
            frames.append(df)
    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)
