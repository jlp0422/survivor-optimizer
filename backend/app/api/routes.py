"""FastAPI route handlers."""
import json
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db, Game, Team, Entry, Pick, TeamWeekStats, SimulationRun
from app.api.schemas import (
    ScheduleResponse, GameSchema,
    EntryCreate, EntrySchema,
    PickSubmit, PickSchema,
    RecommendResponse, PickRecommendation,
    SimulationResponse, SimulationRequest, TeamSurvivalProb,
    UpdateResponse, ResultsUpdate,
    TeamScheduleResponse, TeamGameSchema,
)
from app.models.win_probability import WinProbabilityModel, update_game_win_probs
from app.optimizer.monte_carlo import (
    simulate_portfolio, simulate_single_entry, get_remaining_matchups,
    get_scarcity_analysis, EntryState, _build_win_matrix
)
from app.data.loader import refresh_current_season

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api")

# Module-level model singleton (loaded lazily)
_model: Optional[WinProbabilityModel] = None


def get_model() -> WinProbabilityModel:
    global _model
    if _model is None:
        _model = WinProbabilityModel()
        _model.load()
    return _model


# ── Schedule ───────────────────────────────────────────────────────────────

@router.get("/schedule/{season}", response_model=ScheduleResponse)
def get_schedule(season: int, db: Session = Depends(get_db)):
    games = (
        db.query(Game)
        .filter(Game.season == season)
        .order_by(Game.week, Game.id)
        .all()
    )
    if not games:
        raise HTTPException(status_code=404, detail=f"No schedule found for season {season}")

    team_abbrs = {t.id: t.abbr for t in db.query(Team).all()}
    weeks: dict[int, list[GameSchema]] = {}

    for g in games:
        week = g.week
        if week not in weeks:
            weeks[week] = []
        weeks[week].append(GameSchema(
            id=g.id,
            season=g.season,
            week=g.week,
            game_date=g.game_date,
            home_team=team_abbrs.get(g.home_team_id, ""),
            away_team=team_abbrs.get(g.away_team_id, ""),
            home_score=g.home_score,
            away_score=g.away_score,
            home_win=g.home_win,
            home_win_prob=g.home_win_prob,
            away_win_prob=g.away_win_prob,
            is_neutral=g.is_neutral or False,
        ))

    return ScheduleResponse(season=season, weeks=weeks)


# ── Entries ────────────────────────────────────────────────────────────────

@router.get("/entries", response_model=list[EntrySchema])
def list_entries(season: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(Entry)
    if season:
        q = q.filter(Entry.season == season)
    entries = q.order_by(Entry.id).all()

    result = []
    for e in entries:
        used_teams = [
            db.query(Team).get(p.team_id).abbr
            for p in e.picks
        ]
        schema = EntrySchema(
            id=e.id,
            name=e.name,
            season=e.season,
            is_alive=e.is_alive,
            eliminated_week=e.eliminated_week,
            created_at=e.created_at,
            used_teams=used_teams,
        )
        result.append(schema)
    return result


@router.post("/entries", response_model=EntrySchema, status_code=201)
def create_entry(body: EntryCreate, db: Session = Depends(get_db)):
    entry = Entry(name=body.name, season=body.season)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return EntrySchema(
        id=entry.id,
        name=entry.name,
        season=entry.season,
        is_alive=entry.is_alive,
        eliminated_week=entry.eliminated_week,
        created_at=entry.created_at,
        used_teams=[],
    )


# ── Picks ──────────────────────────────────────────────────────────────────

@router.post("/picks/submit", response_model=PickSchema, status_code=201)
def submit_pick(body: PickSubmit, db: Session = Depends(get_db)):
    entry = db.query(Entry).get(body.entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    if not entry.is_alive:
        raise HTTPException(status_code=400, detail="Entry is already eliminated")

    team = db.query(Team).filter_by(abbr=body.team_abbr).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {body.team_abbr} not found")

    # Check team hasn't been used by this entry
    existing = db.query(Pick).filter_by(
        entry_id=body.entry_id, team_id=team.id
    ).first()
    if existing:
        raise HTTPException(
            status_code=400,
            detail=f"{body.team_abbr} already used by this entry (week {existing.week})"
        )

    # Check not already picked this week
    week_pick = db.query(Pick).filter_by(
        entry_id=body.entry_id, season=body.season, week=body.week
    ).first()
    if week_pick:
        raise HTTPException(status_code=400, detail=f"Already have a pick for week {body.week}")

    # Get win prob
    game = (
        db.query(Game)
        .filter(
            Game.season == body.season,
            Game.week == body.week,
            (Game.home_team_id == team.id) | (Game.away_team_id == team.id),
        )
        .first()
    )
    win_prob = None
    if game:
        if game.home_team_id == team.id:
            win_prob = game.home_win_prob
        else:
            win_prob = game.away_win_prob

    pick = Pick(
        entry_id=body.entry_id,
        team_id=team.id,
        season=body.season,
        week=body.week,
        win_prob=win_prob,
        is_recommended=False,
    )
    db.add(pick)
    db.commit()
    db.refresh(pick)

    return PickSchema(
        id=pick.id,
        entry_id=pick.entry_id,
        team=body.team_abbr,
        season=pick.season,
        week=pick.week,
        win_prob=pick.win_prob,
        is_recommended=pick.is_recommended,
        outcome=pick.outcome,
        submitted_at=pick.submitted_at,
    )


# ── Recommendations ────────────────────────────────────────────────────────

@router.get("/picks/recommend/{week}", response_model=RecommendResponse)
def get_recommendations(
    week: int,
    season: int,
    db: Session = Depends(get_db),
):
    entries = db.query(Entry).filter_by(season=season, is_alive=True).all()
    if not entries:
        raise HTTPException(status_code=404, detail="No alive entries found")

    entry_states = []
    for e in entries:
        used = set()
        for p in e.picks:
            team = db.query(Team).get(p.team_id)
            if team:
                used.add(team.abbr)
        entry_states.append(EntryState(
            entry_id=e.id,
            used_teams=used,
            is_alive=e.is_alive,
        ))

    recs = simulate_portfolio(
        db=db,
        season=season,
        current_week=week,
        n_entries=len(entry_states),
        entry_states=entry_states,
        n_sims=50_000,
    )

    recommendations = [
        PickRecommendation(
            entry_id=r["entry_id"],
            week=r["week"],
            recommended_team=r["recommended_team"],
            win_prob=r["win_prob"],
            survival_prob=r["survival_prob"],
            portfolio_coverage=r["portfolio_coverage"],
            strategy_picks=r.get("strategy_picks", {}),
        )
        for r in recs
    ]

    return RecommendResponse(season=season, week=week, recommendations=recommendations)


# ── Results Update ─────────────────────────────────────────────────────────

@router.post("/results/update/{week}", response_model=UpdateResponse)
def update_results(week: int, body: ResultsUpdate, db: Session = Depends(get_db)):
    """
    Trigger full data refresh for the current week:
    1. Reload schedule (captures new results)
    2. Update win probabilities for upcoming games
    3. Update pick outcomes for the completed week
    """
    from app.data.loader import seed_teams, load_season_schedule, load_team_stats

    team_map = seed_teams(db)
    load_season_schedule(db, body.season, team_map)
    load_team_stats(db, body.season, team_map)

    model = get_model()
    win_probs_updated = update_game_win_probs(db, model, body.season)

    # Update pick outcomes for the completed week
    games_updated = _update_pick_outcomes(db, body.season, week)

    return UpdateResponse(
        season=body.season,
        week=week,
        games_updated=games_updated,
        win_probs_updated=win_probs_updated,
        message=f"Season {body.season} week {week} updated successfully",
    )


def _update_pick_outcomes(db: Session, season: int, week: int) -> int:
    """Mark picks as won/lost based on game results."""
    picks = db.query(Pick).filter_by(season=season, week=week).all()
    updated = 0

    for pick in picks:
        if pick.outcome is not None:
            continue

        game = (
            db.query(Game)
            .filter(
                Game.season == season,
                Game.week == week,
                Game.home_win.isnot(None),
                (Game.home_team_id == pick.team_id) | (Game.away_team_id == pick.team_id),
            )
            .first()
        )

        if not game:
            continue

        if game.home_team_id == pick.team_id:
            pick.outcome = game.home_win
        else:
            pick.outcome = not game.home_win  # away team won if home didn't

        # Update entry survival status if they lost
        if pick.outcome is False:
            entry = db.query(Entry).get(pick.entry_id)
            if entry and entry.is_alive:
                entry.is_alive = False
                entry.eliminated_week = week

        updated += 1

    db.commit()
    return updated


# ── Team Schedule ──────────────────────────────────────────────────────────

@router.get("/teams/{team_abbr}/schedule", response_model=TeamScheduleResponse)
def get_team_schedule(
    team_abbr: str,
    season: int,
    db: Session = Depends(get_db),
):
    team = db.query(Team).filter_by(abbr=team_abbr.upper()).first()
    if not team:
        raise HTTPException(status_code=404, detail=f"Team {team_abbr} not found")

    games = (
        db.query(Game)
        .filter(
            Game.season == season,
            (Game.home_team_id == team.id) | (Game.away_team_id == team.id),
        )
        .order_by(Game.week)
        .all()
    )

    team_abbrs = {t.id: t.abbr for t in db.query(Team).all()}
    game_schemas = []

    for g in games:
        is_home = g.home_team_id == team.id
        opponent_id = g.away_team_id if is_home else g.home_team_id
        opponent_abbr = team_abbrs.get(opponent_id, "")
        win_prob = g.home_win_prob if is_home else g.away_win_prob

        result = None
        if g.home_win is not None:
            won = g.home_win if is_home else not g.home_win
            result = "W" if won else "L"

        game_schemas.append(TeamGameSchema(
            week=g.week,
            opponent=opponent_abbr,
            is_home=is_home,
            win_prob=win_prob,
            is_played=g.home_win is not None,
            result=result,
        ))

    # Which entries have already used this team
    used_by = [
        p.entry_id
        for p in db.query(Pick).filter_by(team_id=team.id, season=season).all()
    ]

    return TeamScheduleResponse(
        team=team_abbr.upper(),
        season=season,
        games=game_schemas,
        used_by_entries=used_by,
    )


# ── Simulation ─────────────────────────────────────────────────────────────

@router.get("/simulate/{week}", response_model=SimulationResponse)
def run_simulation(
    week: int,
    season: int,
    n_simulations: int = 50000,
    entry_id: Optional[int] = None,
    db: Session = Depends(get_db),
):
    """
    Run Monte Carlo and return per-team survival probabilities for the given week.
    If entry_id is provided, respects that entry's used teams.
    """
    used_teams: set[str] = set()
    if entry_id:
        entry = db.query(Entry).get(entry_id)
        if entry:
            for p in entry.picks:
                team = db.query(Team).get(p.team_id)
                if team:
                    used_teams.add(team.abbr)

    matchups_by_week = get_remaining_matchups(db, season, week)
    if not matchups_by_week:
        raise HTTPException(status_code=404, detail="No matchup data available")

    weeks = sorted(matchups_by_week.keys())
    all_teams = sorted(set(
        m.team_abbr
        for w_matchups in matchups_by_week.values()
        for m in w_matchups
    ))
    import numpy as np
    team_idx = {t: i for i, t in enumerate(all_teams)}

    win_matrix = _build_win_matrix(matchups_by_week, weeks, all_teams)
    used_mask = np.zeros(len(all_teams), dtype=bool)
    for t in used_teams:
        ti = team_idx.get(t)
        if ti is not None:
            used_mask[ti] = True

    survival_probs = simulate_single_entry(
        win_matrix=win_matrix,
        used_mask=used_mask,
        weeks=weeks,
        all_teams=all_teams,
        n_sims=n_simulations,
    )

    scarcity = get_scarcity_analysis(matchups_by_week, used_teams)

    # Build response with win probs for current week
    week_matchups = matchups_by_week.get(week, [])
    win_prob_lookup = {m.team_abbr: (m.win_prob, m.opponent_abbr, m.is_home) for m in week_matchups}

    team_probs = []
    for team_abbr, surv_prob in sorted(survival_probs.items(), key=lambda x: -x[1]):
        if team_abbr in used_teams:
            continue
        wp_info = win_prob_lookup.get(team_abbr, (None, None, True))
        team_probs.append(TeamSurvivalProb(
            team=team_abbr,
            win_prob=wp_info[0] or 0.0,
            survival_prob=surv_prob,
            opponent=wp_info[1],
            is_home=wp_info[2],
        ))

    # Save simulation run
    run = SimulationRun(
        season=season,
        week=week,
        n_simulations=n_simulations,
        results_json=json.dumps(survival_probs),
    )
    db.add(run)
    db.commit()

    return SimulationResponse(
        season=season,
        week=week,
        n_simulations=n_simulations,
        team_survival_probs=team_probs,
        scarcity_by_week=scarcity,
    )
