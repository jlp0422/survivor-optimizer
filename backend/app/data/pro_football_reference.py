"""
Scrape team game logs and SRS ratings from Pro Football Reference.
Rate-limited to 1 req/sec. Uses lxml for parsing.
"""
from __future__ import annotations
import logging
import time
from pathlib import Path
import pandas as pd
import requests
from bs4 import BeautifulSoup, Comment

logger = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parents[3] / "data" / "cache"
CACHE_DIR.mkdir(parents=True, exist_ok=True)

PFR_BASE = "https://www.pro-football-reference.com"
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# PFR team abbreviation → our standard
PFR_TEAM_MAP = {
    "crd": "ARI", "atl": "ATL", "rav": "BAL", "buf": "BUF",
    "car": "CAR", "chi": "CHI", "cin": "CIN", "cle": "CLE",
    "dal": "DAL", "den": "DEN", "det": "DET", "gnb": "GB",
    "htx": "HOU", "clt": "IND", "jax": "JAX", "kan": "KC",
    "sdg": "LAC", "lac": "LAC", "ram": "LAR", "rai": "LV",
    "lvr": "LV", "mia": "MIA", "min": "MIN", "nwe": "NE",
    "nor": "NO",  "nyg": "NYG", "nyj": "NYJ", "phi": "PHI",
    "pit": "PIT", "sea": "SEA", "sfo": "SF",  "tam": "TB",
    "oti": "TEN", "was": "WAS",
}


def _rate_limited_get(url: str, delay: float = 1.0) -> requests.Response:
    time.sleep(delay)
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    return resp


def _find_table_in_comments(soup: BeautifulSoup, table_id: str):
    """PFR hides some tables in HTML comments; this finds them."""
    for comment in soup.find_all(string=lambda t: isinstance(t, Comment)):
        if table_id in comment:
            comment_soup = BeautifulSoup(comment, "lxml")
            table = comment_soup.find("table", {"id": table_id})
            if table:
                return table
    return soup.find("table", {"id": table_id})


def scrape_team_season_log(team_pfr: str, season: int) -> pd.DataFrame:
    """
    Scrape game log for a team in a given season.
    Returns: week, date, home, opponent, pts_for, pts_against, result
    """
    cache_path = CACHE_DIR / f"pfr_{team_pfr}_{season}.parquet"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        # Use cache if it's historical (< 2024) or fresh (< 24h for current)
        if season < 2024 or age_hours < 24:
            return pd.read_parquet(cache_path)

    url = f"{PFR_BASE}/teams/{team_pfr}/{season}/gamelog/"
    logger.info("Scraping PFR game log: %s", url)

    try:
        resp = _rate_limited_get(url)
    except requests.HTTPError as e:
        logger.warning("PFR game log %s %d: %s", team_pfr, season, e)
        return pd.DataFrame()

    soup = BeautifulSoup(resp.text, "lxml")
    table = _find_table_in_comments(soup, "gamelog")

    if table is None:
        logger.warning("No gamelog table found for %s %d", team_pfr, season)
        return pd.DataFrame()

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        if tr.get("class") and "thead" in tr.get("class"):
            continue
        cells = tr.find_all(["td", "th"])
        if not cells:
            continue

        def cell(data_stat: str) -> str:
            el = tr.find(attrs={"data-stat": data_stat})
            return el.get_text(strip=True) if el else ""

        week_str = cell("week_num")
        if not week_str.isdigit():
            continue

        game_location = cell("game_location")
        opp_link = tr.find(attrs={"data-stat": "opp"})
        opp_pfr = ""
        if opp_link and opp_link.find("a"):
            href = opp_link.find("a")["href"]
            opp_pfr = href.split("/")[2] if "/teams/" in href else ""

        pts_str = cell("pts_off")
        opp_pts_str = cell("pts_def")

        try:
            pts = int(pts_str)
            opp_pts = int(opp_pts_str)
        except (ValueError, TypeError):
            pts = opp_pts = None

        rows.append({
            "team": PFR_TEAM_MAP.get(team_pfr, team_pfr.upper()),
            "season": season,
            "week": int(week_str),
            "is_home": game_location != "@",
            "opponent": PFR_TEAM_MAP.get(opp_pfr, opp_pfr.upper()),
            "pts_for": pts,
            "pts_against": opp_pts,
            "point_diff": (pts - opp_pts) if pts is not None else None,
            "result": cell("game_result"),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def scrape_srs_season(season: int) -> pd.DataFrame:
    """
    Scrape Simple Rating System (SRS) for all teams in a season.
    Returns: team, season, srs, sos (strength of schedule)
    """
    cache_path = CACHE_DIR / f"pfr_srs_{season}.parquet"
    if cache_path.exists():
        age_hours = (time.time() - cache_path.stat().st_mtime) / 3600
        if season < 2024 or age_hours < 24:
            return pd.read_parquet(cache_path)

    url = f"{PFR_BASE}/years/{season}/"
    logger.info("Scraping PFR SRS for %d", season)

    try:
        resp = _rate_limited_get(url)
    except Exception as e:
        logger.warning("PFR SRS %d: %s", season, e)
        return pd.DataFrame()

    soup = BeautifulSoup(resp.text, "lxml")
    table = _find_table_in_comments(soup, "team_stats")

    if table is None:
        return pd.DataFrame()

    rows = []
    for tr in table.find("tbody").find_all("tr"):
        if tr.get("class") and "thead" in tr.get("class"):
            continue

        def cell(data_stat: str) -> str:
            el = tr.find(attrs={"data-stat": data_stat})
            return el.get_text(strip=True) if el else ""

        team_name = cell("team")
        # Map PFR full name to abbreviation
        team_link = tr.find(attrs={"data-stat": "team"})
        team_abbr = None
        if team_link and team_link.find("a"):
            href = team_link.find("a")["href"]
            pfr_code = href.split("/")[2] if "/teams/" in href else ""
            team_abbr = PFR_TEAM_MAP.get(pfr_code)

        if not team_abbr:
            continue

        def safe_float(stat: str) -> float | None:
            val = cell(stat)
            try:
                return float(val)
            except (ValueError, TypeError):
                return None

        rows.append({
            "team": team_abbr,
            "season": season,
            "srs": safe_float("srs"),
            "sos": safe_float("sos"),
            "mov": safe_float("mov"),   # Margin of Victory
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df.to_parquet(cache_path, index=False)
    return df


def compute_point_differentials(season: int) -> pd.DataFrame:
    """
    Compute rolling point differentials for all teams in a season.
    Returns: team, season, week, point_diff (cumulative), recent_form (last 4 games)
    """
    # PFR team codes
    pfr_teams = list(PFR_TEAM_MAP.keys())

    frames = []
    for pfr_code in pfr_teams:
        our_abbr = PFR_TEAM_MAP[pfr_code]
        df = scrape_team_season_log(pfr_code, season)
        if not df.empty:
            frames.append(df)

    if not frames:
        return pd.DataFrame()

    all_games = pd.concat(frames, ignore_index=True)

    # Compute recent form (rolling 4-game average point diff)
    all_games = all_games.sort_values(["team", "season", "week"])
    all_games["recent_form"] = (
        all_games.groupby(["team", "season"])["point_diff"]
        .transform(lambda x: x.shift(1).rolling(4, min_periods=1).mean())
    )

    return all_games[["team", "season", "week", "point_diff", "recent_form", "is_home"]]
