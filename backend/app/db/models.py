from datetime import datetime
from sqlalchemy import (
    Column, Integer, String, Float, Boolean, DateTime, Date,
    ForeignKey, UniqueConstraint, Index, Text
)
from sqlalchemy.orm import DeclarativeBase, relationship


class Base(DeclarativeBase):
    pass


class Team(Base):
    __tablename__ = "teams"

    id = Column(Integer, primary_key=True)
    abbr = Column(String(5), unique=True, nullable=False)   # e.g. "KC"
    full_name = Column(String(50), nullable=False)           # e.g. "Kansas City Chiefs"
    conference = Column(String(5))                           # AFC / NFC
    division = Column(String(10))                            # AFC West

    games_home = relationship("Game", foreign_keys="Game.home_team_id", back_populates="home_team")
    games_away = relationship("Game", foreign_keys="Game.away_team_id", back_populates="away_team")
    stats = relationship("TeamWeekStats", back_populates="team")
    picks = relationship("Pick", back_populates="team")


class Game(Base):
    __tablename__ = "games"
    __table_args__ = (
        UniqueConstraint("season", "week", "home_team_id", name="uq_game"),
        Index("ix_games_season_week", "season", "week"),
    )

    id = Column(Integer, primary_key=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    game_date = Column(Date)
    home_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    away_team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    home_score = Column(Integer)
    away_score = Column(Integer)
    home_win = Column(Boolean)          # True/False/None (None = not played)
    is_neutral = Column(Boolean, default=False)
    location = Column(String(100))      # stadium/city

    # Computed win probabilities (updated by model)
    home_win_prob = Column(Float)
    away_win_prob = Column(Float)

    home_team = relationship("Team", foreign_keys=[home_team_id], back_populates="games_home")
    away_team = relationship("Team", foreign_keys=[away_team_id], back_populates="games_away")


class TeamWeekStats(Base):
    """Per-team per-week stats used as model features."""
    __tablename__ = "team_week_stats"
    __table_args__ = (
        UniqueConstraint("team_id", "season", "week", name="uq_team_week"),
        Index("ix_tws_season_week", "season", "week"),
    )

    id = Column(Integer, primary_key=True)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)

    # Football Outsiders DVOA
    total_dvoa = Column(Float)
    offense_dvoa = Column(Float)
    defense_dvoa = Column(Float)      # negative is better (fewer points allowed)
    st_dvoa = Column(Float)

    # nflverse EPA
    off_epa_per_play = Column(Float)
    def_epa_per_play = Column(Float)  # negative is better

    # Pro Football Reference SRS
    srs = Column(Float)
    point_differential = Column(Float)

    # Computed / schedule factors
    recent_form = Column(Float)        # avg point diff last 4 games
    rest_days = Column(Integer)        # days since last game

    team = relationship("Team", back_populates="stats")


class Entry(Base):
    """A single survivor pool entry."""
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True)
    name = Column(String(50), nullable=False)
    season = Column(Integer, nullable=False)
    is_alive = Column(Boolean, default=True)
    eliminated_week = Column(Integer)
    created_at = Column(DateTime, default=datetime.utcnow)

    picks = relationship("Pick", back_populates="entry")


class Pick(Base):
    """A pick made (or recommended) for a given entry+week."""
    __tablename__ = "picks"
    __table_args__ = (
        UniqueConstraint("entry_id", "season", "week", name="uq_pick"),
    )

    id = Column(Integer, primary_key=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=False)
    team_id = Column(Integer, ForeignKey("teams.id"), nullable=False)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)
    win_prob = Column(Float)           # model's predicted win prob at pick time
    is_recommended = Column(Boolean, default=True)
    outcome = Column(Boolean)          # True=survived, False=eliminated, None=pending
    submitted_at = Column(DateTime, default=datetime.utcnow)

    entry = relationship("Entry", back_populates="picks")
    team = relationship("Team", back_populates="picks")


class SimulationRun(Base):
    """Metadata for Monte Carlo simulation runs."""
    __tablename__ = "simulation_runs"

    id = Column(Integer, primary_key=True)
    season = Column(Integer, nullable=False)
    week = Column(Integer, nullable=False)          # week simulation was run FOR
    n_simulations = Column(Integer, default=50000)
    run_at = Column(DateTime, default=datetime.utcnow)
    results_json = Column(Text)                     # JSON blob of results
