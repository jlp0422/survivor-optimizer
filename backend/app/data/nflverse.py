"""
Load data from nflverse-data GitHub releases (parquet files).
No R required — pure pandas + pyarrow.
"""
import logging
import time
from pathlib import Path
from typing import Optional
import pandas as pd
import requests

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

# nflverse-data GitHub release URL patterns
NFLVERSE_BASE = "https://github.com/nflverse/nflverse-data/releases/download"

URLS = {
    "schedules": f"{NFLVERSE_BASE}/schedules/schedules.parquet",
    "team_stats": f"{NFLVERSE_BASE}/player_stats/player_stats.parquet",
    "pbp_template": f"{NFLVERSE_BASE}/pbp/play_by_play_{{season}}.parquet",
}

# Canonical team abbreviation mapping (nflverse → our standard)
TEAM_ABBR_MAP = {
    "ARI": "ARI", "ATL": "ATL", "BAL": "BAL", "BUF": "BUF",
    "CAR": "CAR", "CHI": "CHI", "CIN": "CIN", "CLE": "CLE",
    "DAL": "DAL", "DEN": "DEN", "DET": "DET", "GB":  "GB",
    "HOU": "HOU", "IND": "IND", "JAX": "JAX", "KC":  "KC",
    "LA":  "LAR", "LAC": "LAC", "LAR": "LAR", "LV":  "LV",
    "MIA": "MIA", "MIN": "MIN", "NE":  "NE",  "NO":  "NO",
    "NYG": "NYG", "NYJ": "NYJ", "PHI": "PHI", "PIT": "PIT",
    "SEA": "SEA", "SF":  "SF",  "TB":  "TB",  "TEN": "TEN",
    "WAS": "WAS", "JAC": "JAX",
}


def _cached_parquet(url: str, cache_name: str, max_age_hours: int = 24) -> pd.DataFrame:
    cache_path = CACHE_DIR / f"{cache_name}.parquet"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < max_age_hours:
            logger.debug("Loading %s from cache", cache_name)
            return pd.read_parquet(cache_path)

    logger.info("Downloading %s from %s", cache_name, url)
    resp = requests.get(url, timeout=120, headers={"User-Agent": "survivor-optimizer/0.1"})
    resp.raise_for_status()
    cache_path.write_bytes(resp.content)
    return pd.read_parquet(cache_path)


def load_schedules(seasons: Optional[list[int]] = None) -> pd.DataFrame:
    """
    Return schedule DataFrame with columns:
    season, week, game_type, gameday, home_team, away_team,
    home_score, away_score, result (positive=home win margin)
    """
    df = _cached_parquet(URLS["schedules"], "schedules", max_age_hours=6)
    df["home_team"] = df["home_team"].map(lambda x: TEAM_ABBR_MAP.get(x, x))
    df["away_team"] = df["away_team"].map(lambda x: TEAM_ABBR_MAP.get(x, x))

    # Filter to regular season + playoffs, remove preseason
    df = df[df["game_type"].isin(["REG", "WC", "DIV", "CON", "SB"])].copy()

    if seasons:
        df = df[df["season"].isin(seasons)]

    return df.reset_index(drop=True)


def load_pbp_epa(season: int) -> pd.DataFrame:
    """
    Load play-by-play for a season, aggregate to team-week EPA per play.
    Returns DataFrame with: season, week, team, off_epa_per_play, def_epa_per_play
    """
    url = URLS["pbp_template"].format(season=season)
    cache_name = f"pbp_{season}"
    # PBP files are large and rarely updated mid-season
    max_age = 168 if season < 2024 else 12  # 1 week for historical, 12h for current

    try:
        pbp = _cached_parquet(url, cache_name, max_age_hours=max_age)
    except Exception as e:
        logger.warning("Could not load PBP for %d: %s", season, e)
        return pd.DataFrame()

    # Filter to regular season plays with valid EPA
    pbp = pbp[
        (pbp["season_type"] == "REG") &
        (pbp["epa"].notna()) &
        (pbp["posteam"].notna())
    ].copy()

    pbp["posteam"] = pbp["posteam"].map(lambda x: TEAM_ABBR_MAP.get(x, x))
    pbp["defteam"] = pbp["defteam"].map(lambda x: TEAM_ABBR_MAP.get(x, x))

    # Offensive EPA: plays where team has possession
    off_epa = (
        pbp.groupby(["season", "week", "posteam"])["epa"]
        .mean()
        .reset_index()
        .rename(columns={"posteam": "team", "epa": "off_epa_per_play"})
    )

    # Defensive EPA: plays where team is defending
    def_epa = (
        pbp.groupby(["season", "week", "defteam"])["epa"]
        .mean()
        .reset_index()
        .rename(columns={"defteam": "team", "epa": "def_epa_per_play"})
    )

    merged = off_epa.merge(def_epa, on=["season", "week", "team"], how="outer")
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
