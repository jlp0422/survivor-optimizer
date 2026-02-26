"""Pydantic schemas for API request/response models."""
from datetime import date, datetime
from typing import Optional
from pydantic import BaseModel, Field


# ── Teams ──────────────────────────────────────────────────────────────────

class TeamSchema(BaseModel):
    id: int
    abbr: str
    full_name: str
    conference: Optional[str] = None
    division: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Games / Schedule ───────────────────────────────────────────────────────

class GameSchema(BaseModel):
    id: int
    season: int
    week: int
    game_date: Optional[date] = None
    home_team: str
    away_team: str
    home_score: Optional[int] = None
    away_score: Optional[int] = None
    home_win: Optional[bool] = None
    home_win_prob: Optional[float] = None
    away_win_prob: Optional[float] = None
    is_neutral: bool = False

    model_config = {"from_attributes": True}


class ScheduleResponse(BaseModel):
    season: int
    weeks: dict[int, list[GameSchema]]


# ── Team Week Stats ────────────────────────────────────────────────────────

class TeamStatsSchema(BaseModel):
    team: str
    season: int
    week: int
    total_dvoa: Optional[float] = None
    offense_dvoa: Optional[float] = None
    defense_dvoa: Optional[float] = None
    off_epa_per_play: Optional[float] = None
    def_epa_per_play: Optional[float] = None
    srs: Optional[float] = None
    recent_form: Optional[float] = None
    rest_days: Optional[int] = None

    model_config = {"from_attributes": True}


# ── Entries ────────────────────────────────────────────────────────────────

class EntryCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=50)
    season: int = Field(..., ge=2015, le=2030)


class EntrySchema(BaseModel):
    id: int
    name: str
    season: int
    is_alive: bool
    eliminated_week: Optional[int] = None
    created_at: datetime
    used_teams: list[str] = []

    model_config = {"from_attributes": True}


# ── Picks ──────────────────────────────────────────────────────────────────

class PickSubmit(BaseModel):
    entry_id: int
    team_abbr: str
    season: int
    week: int


class PickSchema(BaseModel):
    id: int
    entry_id: int
    team: str
    season: int
    week: int
    win_prob: Optional[float] = None
    is_recommended: bool
    outcome: Optional[bool] = None
    submitted_at: datetime

    model_config = {"from_attributes": True}


# ── Recommendations ────────────────────────────────────────────────────────

class PickRecommendation(BaseModel):
    entry_id: int
    week: int
    recommended_team: str
    win_prob: Optional[float] = None
    survival_prob: float
    portfolio_coverage: float
    strategy_picks: dict[int, str] = {}    # {week: team_abbr}


class RecommendResponse(BaseModel):
    season: int
    week: int
    recommendations: list[PickRecommendation]


# ── Simulation ─────────────────────────────────────────────────────────────

class SimulationRequest(BaseModel):
    season: int
    week: int
    n_simulations: int = Field(default=50000, ge=1000, le=500000)


class TeamSurvivalProb(BaseModel):
    team: str
    win_prob: float
    survival_prob: float
    opponent: Optional[str] = None
    is_home: bool = True


class SimulationResponse(BaseModel):
    season: int
    week: int
    n_simulations: int
    team_survival_probs: list[TeamSurvivalProb]
    scarcity_by_week: dict[int, int] = {}


# ── Results Update ─────────────────────────────────────────────────────────

class ResultsUpdate(BaseModel):
    season: int
    week: int


class UpdateResponse(BaseModel):
    season: int
    week: int
    games_updated: int
    win_probs_updated: int
    message: str


# ── Team Schedule ──────────────────────────────────────────────────────────

class TeamGameSchema(BaseModel):
    week: int
    opponent: str
    is_home: bool
    win_prob: Optional[float] = None
    is_played: bool
    result: Optional[str] = None  # "W", "L", or None


class TeamScheduleResponse(BaseModel):
    team: str
    season: int
    games: list[TeamGameSchema]
    used_by_entries: list[int] = []   # entry_ids that already used this team
