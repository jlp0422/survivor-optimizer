"""
Scrape DVOA data from Football Outsiders.
Rate-limited to 1 req/sec. Caches to parquet.
"""
from __future__ import annotations
import logging
import time
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[4] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

FO_BASE = "https://www.footballoutsiders.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# FO team name → our abbreviation
FO_TEAM_MAP = {
    "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL",
    "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
    "Carolina Panthers": "CAR", "Chicago Bears": "CHI",
    "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
    "Dallas Cowboys": "DAL", "Denver Broncos": "DEN",
    "Detroit Lions": "DET", "Green Bay Packers": "GB",
    "Houston Texans": "HOU", "Indianapolis Colts": "IND",
    "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
    "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LAR",
    "Las Vegas Raiders": "LV", "Miami Dolphins": "MIA",
    "Minnesota Vikings": "MIN", "New England Patriots": "NE",
    "New Orleans Saints": "NO", "New York Giants": "NYG",
    "New York Jets": "NYJ", "Philadelphia Eagles": "PHI",
    "Pittsburgh Steelers": "PIT", "Seattle Seahawks": "SEA",
    "San Francisco 49ers": "SF", "Tampa Bay Buccaneers": "TB",
    "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
    # Historical names
    "Oakland Raiders": "LV", "San Diego Chargers": "LAC",
    "St. Louis Rams": "LAR", "Washington Redskins": "WAS",
    "Washington Football Team": "WAS",
}


def _rate_limited_get(url: str, delay: float = 1.0) -> requests.Response:
    time.sleep(delay)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp


def scrape_dvoa_week(season: int, week: int) -> pd.DataFrame:
    """
    Scrape DVOA table for a specific season/week.
    Returns DataFrame: team, season, week, total_dvoa, offense_dvoa, defense_dvoa, st_dvoa
    """
    cache_path = CACHE_DIR / f"dvoa_{season}_w{week:02d}.parquet"
    if cache_path.exists():
        return pd.read_parquet(cache_path)

    url = f"{FO_BASE}/dvoa-ratings/{season}/week{week}-dvoa-ratings"
    logger.info("Scraping FO DVOA: %s", url)

    try:
        resp = _rate_limited_get(url)
    except requests.HTTPError as e:
        logger.warning("FO DVOA %d w%d not available: %s", season, week, e)
        return pd.DataFrame()

    soup = BeautifulSoup(resp.text, "lxml")
    rows = []

    # FO DVOA table typically has id="team-stats" or class containing "dvoa"
    table = (
        soup.find("table", {"id": "team-stats"}) or
        soup.find("table", class_=lambda c: c and "dvoa" in c.lower())
    )

    if table is None:
        # Try to find any table with DVOA header
        for t in soup.find_all("table"):
            headers = [th.get_text(strip=True).upper() for th in t.find_all("th")]
            if "TOTAL DVOA" in headers or "TOTAL" in headers:
                table = t
                break

    if table is None:
        logger.warning("Could not find DVOA table for %d w%d", season, week)
        return pd.DataFrame()

    # Parse headers
    header_row = table.find("tr")
    headers = [th.get_text(strip=True).upper() for th in header_row.find_all(["th", "td"])]

    # Map column indices
    def find_col(keywords: list[str]) -> int:
        for i, h in enumerate(headers):
            if any(k in h for k in keywords):
                return i
        return -1

    team_col = find_col(["TEAM"])
    total_col = find_col(["TOTAL DVOA", "TOTAL"])
    off_col = find_col(["OFFENSE", "OFF DVOA", "OFF"])
    def_col = find_col(["DEFENSE", "DEF DVOA", "DEF"])
    st_col = find_col(["ST DVOA", "SPEC TEAMS", "SPECIAL"])

    for tr in table.find_all("tr")[1:]:
        cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 4:
            continue

        team_name = cells[team_col] if team_col >= 0 else ""
        team_abbr = FO_TEAM_MAP.get(team_name)
        if not team_abbr:
            # Try partial match
            for fo_name, abbr in FO_TEAM_MAP.items():
                if fo_name.split()[-1] in team_name:
                    team_abbr = abbr
                    break

        if not team_abbr:
            continue

        def safe_float(idx: int) -> float | None:
            if idx < 0 or idx >= len(cells):
                return None
            val = cells[idx].replace("%", "").replace(",", "")
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        rows.append({
            "team": team_abbr,
            "season": season,
            "week": week,
            "total_dvoa": safe_float(total_col),
            "offense_dvoa": safe_float(off_col),
            "defense_dvoa": safe_float(def_col),
            "st_dvoa": safe_float(st_col),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache_path, index=False)

    return df


def scrape_dvoa_season(season: int, through_week: int = 18) -> pd.DataFrame:
    """Scrape all weeks of a season's DVOA data."""
    frames = []
    for week in range(1, through_week + 1):
        df = scrape_dvoa_week(season, week)
        if not df.empty:
            frames.append(df)
        else:
            logger.info("No DVOA data for week %d — stopping", week)
            break

    if not frames:
        return pd.DataFrame()
    return pd.concat(frames, ignore_index=True)


def get_latest_dvoa(season: int) -> pd.DataFrame:
    """
    Get the most recent week's DVOA for a season (cumulative ratings).
    Returns one row per team with the latest available DVOA.
    """
    cache_path = CACHE_DIR / f"dvoa_{season}_latest.parquet"

    # Check if fresh (< 24h)
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if age_hours < 24:
            return pd.read_parquet(cache_path)

    url = f"{FO_BASE}/dvoa-ratings/{season}"
    logger.info("Scraping latest FO DVOA for %d", season)

    try:
        resp = _rate_limited_get(url)
    except Exception as e:
        logger.warning("Could not fetch latest DVOA: %s", e)
        if cache_path.exists():
            return pd.read_parquet(cache_path)
        return pd.DataFrame()

    soup = BeautifulSoup(resp.text, "lxml")
    # Reuse week scraper logic but parse from main page
    # (same table structure as weekly pages)
    rows = []
    table = soup.find("table", {"id": "team-stats"})
    if table is None:
        for t in soup.find_all("table"):
            ths = [th.get_text(strip=True).upper() for th in t.find_all("th")]
            if any("DVOA" in h for h in ths):
                table = t
                break

    if table is not None:
        header_row = table.find("tr")
        headers = [th.get_text(strip=True).upper() for th in header_row.find_all(["th", "td"])]

        def find_col(keywords):
            for i, h in enumerate(headers):
                if any(k in h for k in keywords):
                    return i
            return -1

        team_col = find_col(["TEAM"])
        total_col = find_col(["TOTAL DVOA", "TOTAL"])
        off_col = find_col(["OFFENSE", "OFF DVOA", "OFF"])
        def_col = find_col(["DEFENSE", "DEF DVOA", "DEF"])
        st_col = find_col(["ST DVOA", "SPEC TEAMS", "SPECIAL"])

        for tr in table.find_all("tr")[1:]:
            cells = [td.get_text(strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) < 4:
                continue
            team_name = cells[team_col] if team_col >= 0 else ""
            team_abbr = FO_TEAM_MAP.get(team_name)
            if not team_abbr:
                continue

            def safe_float(idx):
                if idx < 0 or idx >= len(cells):
                    return None
                try:
                    return float(cells[idx].replace("%", "").replace(",", ""))
                except (ValueError, TypeError):
                    return None

            rows.append({
                "team": team_abbr,
                "season": season,
                "total_dvoa": safe_float(total_col),
                "offense_dvoa": safe_float(off_col),
                "defense_dvoa": safe_float(def_col),
                "st_dvoa": safe_float(st_col),
            })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache_path, index=False)
    return df
