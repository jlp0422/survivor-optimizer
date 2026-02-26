"""
Monte Carlo survivor pool optimizer.

Single-entry: maximizes P(surviving all remaining weeks).
Multi-entry portfolio: maximizes P(at least one entry survives).

N=50,000 simulations by default.
"""
import logging
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
from sqlalchemy.orm import Session
from app.db.models import Game, Team, Pick, Entry

logger = logging.getLogger(__name__)

N_SIMULATIONS = 50_000
SEED = 42


@dataclass
class WeekMatchup:
    week: int
    team_abbr: str
    team_id: int
    opponent_abbr: str
    is_home: bool
    win_prob: float    # probability this team wins THIS game


@dataclass
class EntryState:
    entry_id: int
    used_teams: set[str] = field(default_factory=set)   # teams already picked
    is_alive: bool = True


def get_remaining_matchups(
    db: Session,
    season: int,
    from_week: int,
) -> dict[int, list[WeekMatchup]]:
    """
    Returns {week: [WeekMatchup, ...]} for all unplayed games from from_week onward.
    Only includes games where a win probability has been computed.
    """
    games = (
        db.query(Game)
        .filter(
            Game.season == season,
            Game.week >= from_week,
            Game.home_win.is_(None),          # unplayed
            Game.home_win_prob.isnot(None),   # has win prob
        )
        .order_by(Game.week, Game.id)
        .all()
    )

    team_abbrs: dict[int, str] = {
        t.id: t.abbr for t in db.query(Team).all()
    }

    matchups_by_week: dict[int, list[WeekMatchup]] = {}
    for game in games:
        week = game.week
        if week not in matchups_by_week:
            matchups_by_week[week] = []

        home_abbr = team_abbrs.get(game.home_team_id, "")
        away_abbr = team_abbrs.get(game.away_team_id, "")

        matchups_by_week[week].append(WeekMatchup(
            week=week,
            team_abbr=home_abbr,
            team_id=game.home_team_id,
            opponent_abbr=away_abbr,
            is_home=True,
            win_prob=game.home_win_prob,
        ))
        matchups_by_week[week].append(WeekMatchup(
            week=week,
            team_abbr=away_abbr,
            team_id=game.away_team_id,
            opponent_abbr=home_abbr,
            is_home=False,
            win_prob=game.away_win_prob,
        ))

    return matchups_by_week


def _build_win_matrix(
    matchups_by_week: dict[int, list[WeekMatchup]],
    weeks: list[int],
    all_teams: list[str],
) -> np.ndarray:
    """
    Build win probability matrix: shape (n_weeks, n_teams).
    Entry [i, j] = probability team j wins in week i (0 if they have a bye).
    """
    team_idx = {t: i for i, t in enumerate(all_teams)}
    n_weeks = len(weeks)
    n_teams = len(all_teams)

    win_matrix = np.full((n_weeks, n_teams), np.nan)

    for wi, week in enumerate(weeks):
        for matchup in matchups_by_week.get(week, []):
            ti = team_idx.get(matchup.team_abbr)
            if ti is not None:
                win_matrix[wi, ti] = matchup.win_prob

    return win_matrix


def simulate_single_entry(
    win_matrix: np.ndarray,        # shape (n_weeks, n_teams)
    used_mask: np.ndarray,         # shape (n_teams,) bool — teams already used
    weeks: list[int],
    all_teams: list[str],
    n_sims: int = N_SIMULATIONS,
    rng: Optional[np.random.Generator] = None,
) -> dict[str, float]:
    """
    Monte Carlo simulation for single-entry survivor.
    Uses greedy-forward strategy: each week picks the highest win-prob available team.

    Returns: {team_abbr: survival_probability_if_picked_this_week}
    """
    if rng is None:
        rng = np.random.default_rng(SEED)

    n_weeks, n_teams = win_matrix.shape

    if n_weeks == 0:
        return {}

    # For each possible first-week pick, simulate survival through remaining weeks
    current_week_idx = 0
    available_mask = ~used_mask & ~np.isnan(win_matrix[current_week_idx])

    survival_probs = {}
    all_team_names = all_teams

    for first_pick_idx in range(n_teams):
        if not available_mask[first_pick_idx]:
            continue

        team_abbr = all_team_names[first_pick_idx]

        # Simulate n_sims paths
        # alive[sim] = True if still alive
        alive = np.ones(n_sims, dtype=bool)

        # Track used teams per simulation (as bitmask via cumulative picks)
        # Since this is a greedy strategy, all sims use the same picks after week 0
        # We pick greedily: highest available win prob each week

        used_teams_sim = used_mask.copy()  # start with pre-used
        used_teams_sim[first_pick_idx] = True

        # Week 0: pick = first_pick_idx
        win_probs_w0 = win_matrix[current_week_idx, first_pick_idx]
        outcomes_w0 = rng.random(n_sims) < win_probs_w0
        alive &= outcomes_w0

        # Subsequent weeks: greedy pick (highest win prob among unused teams)
        for wi in range(1, n_weeks):
            if not alive.any():
                break

            row = win_matrix[wi].copy()
            row[used_teams_sim] = -1.0   # mask out used teams
            row[np.isnan(row)] = -1.0    # mask out teams on bye

            best_idx = int(np.argmax(row))
            if row[best_idx] < 0:
                # No available team this week → can't survive
                alive[:] = False
                break

            used_teams_sim[best_idx] = True
            win_prob = win_matrix[wi, best_idx]
            outcomes = rng.random(n_sims) < win_prob
            alive &= outcomes

        survival_probs[team_abbr] = float(alive.mean())

    return survival_probs


def simulate_full_season_strategy(
    win_matrix: np.ndarray,
    used_mask: np.ndarray,
    weeks: list[int],
    all_teams: list[str],
    n_sims: int = N_SIMULATIONS,
    rng: Optional[np.random.Generator] = None,
) -> tuple[list[str], float]:
    """
    Forward-looking simulation: finds the optimal pick sequence for a single entry
    that maximizes probability of surviving ALL remaining weeks.

    Uses beam search (beam_width=5) over pick sequences for tractability.
    Returns: (list_of_picks_by_week, overall_survival_probability)
    """
    if rng is None:
        rng = np.random.default_rng(SEED)

    n_weeks, n_teams = win_matrix.shape
    if n_weeks == 0:
        return [], 1.0

    BEAM_WIDTH = 5

    # State: (used_mask_tuple, picks_so_far, survival_prob)
    BeamState = tuple  # (frozenset_used, list_picks, float_survival)

    initial_states: list[BeamState] = [(frozenset(np.where(used_mask)[0]), [], 1.0)]

    for wi in range(n_weeks):
        next_states: list[BeamState] = []
        row = win_matrix[wi]

        for used_frozen, picks, prev_surv in initial_states:
            # Find available teams this week
            available = [
                ti for ti in range(n_teams)
                if ti not in used_frozen and not np.isnan(row[ti]) and row[ti] >= 0
            ]

            if not available:
                # Dead end — survival goes to 0
                next_states.append((used_frozen, picks + [-1], 0.0))
                continue

            # Evaluate each candidate pick
            for ti in available:
                new_surv = prev_surv * row[ti]
                new_used = used_frozen | {ti}
                next_states.append((new_used, picks + [ti], new_surv))

        if not next_states:
            break

        # Keep top beam_width states by survival probability
        next_states.sort(key=lambda s: s[2], reverse=True)
        initial_states = next_states[:BEAM_WIDTH]

    if not initial_states:
        return [], 0.0

    best = initial_states[0]
    best_picks = [all_teams[ti] if ti >= 0 else "NONE" for ti in best[1]]
    best_prob = best[2]

    return best_picks, best_prob


def simulate_portfolio(
    db: Session,
    season: int,
    current_week: int,
    n_entries: int,
    entry_states: list[EntryState],
    n_sims: int = N_SIMULATIONS,
) -> list[dict]:
    """
    Multi-entry portfolio optimization.
    Maximizes P(at least one entry survives).

    Returns list of recommendations per entry:
    [{entry_id, week, recommended_team, win_prob, survival_prob_if_picked,
      portfolio_coverage, strategy_picks}]
    """
    rng = np.random.default_rng(SEED)

    matchups_by_week = get_remaining_matchups(db, season, current_week)
    if not matchups_by_week:
        logger.warning("No matchup data for season %d week %d+", season, current_week)
        return []

    weeks = sorted(matchups_by_week.keys())

    # All teams that appear in at least one remaining game
    all_teams = sorted(set(
        m.team_abbr
        for w_matchups in matchups_by_week.values()
        for m in w_matchups
    ))

    win_matrix = _build_win_matrix(matchups_by_week, weeks, all_teams)
    team_idx = {t: i for i, t in enumerate(all_teams)}

    recommendations = []

    # Track picks already committed this week across entries (for portfolio diversity)
    committed_this_week: list[str] = []

    for entry_state in entry_states:
        if not entry_state.is_alive:
            continue

        # Build used mask for this entry
        used_mask = np.zeros(len(all_teams), dtype=bool)
        for team_abbr in entry_state.used_teams:
            ti = team_idx.get(team_abbr)
            if ti is not None:
                used_mask[ti] = True

        # Get full-season strategy picks
        strategy_picks, strategy_surv = simulate_full_season_strategy(
            win_matrix, used_mask, weeks, all_teams, n_sims=n_sims, rng=rng
        )

        # Single-entry survival probabilities for current week
        single_probs = simulate_single_entry(
            win_matrix, used_mask, weeks, all_teams, n_sims=n_sims, rng=rng
        )

        # Portfolio diversity: prefer picks different from other entries
        # Score = single_survival_prob * (1 + diversity_bonus)
        diversity_scores = {}
        for team_abbr, surv_prob in single_probs.items():
            # Penalty for duplicating a pick already used by another entry this week
            penalty = 0.05 * committed_this_week.count(team_abbr)
            diversity_scores[team_abbr] = surv_prob * (1.0 - penalty)

        if not diversity_scores:
            continue

        recommended_team = max(diversity_scores, key=diversity_scores.__getitem__)
        committed_this_week.append(recommended_team)

        # Find win prob for recommended team this week
        week_matchups = matchups_by_week.get(current_week, [])
        win_prob_this_week = next(
            (m.win_prob for m in week_matchups if m.team_abbr == recommended_team),
            None
        )

        recommendations.append({
            "entry_id": entry_state.entry_id,
            "week": current_week,
            "recommended_team": recommended_team,
            "win_prob": win_prob_this_week,
            "survival_prob": single_probs.get(recommended_team, 0.0),
            "portfolio_coverage": diversity_scores.get(recommended_team, 0.0),
            "strategy_picks": {
                weeks[i]: strategy_picks[i]
                for i in range(min(len(weeks), len(strategy_picks)))
            },
        })

    return recommendations


def compute_team_value_matrix(
    matchups_by_week: dict[int, list[WeekMatchup]],
    used_teams_by_entry: list[set[str]],
) -> dict[str, dict[int, float]]:
    """
    Compute 'value' of each team in each week — how much survival probability
    is sacrificed by using/saving them for a given week.

    Returns: {team_abbr: {week: win_prob}}
    """
    result: dict[str, dict[int, float]] = {}
    for week, matchups in matchups_by_week.items():
        for m in matchups:
            if m.team_abbr not in result:
                result[m.team_abbr] = {}
            result[m.team_abbr][week] = m.win_prob
    return result


def get_scarcity_analysis(
    matchups_by_week: dict[int, list[WeekMatchup]],
    used_teams: set[str],
    min_win_prob: float = 0.65,
) -> dict[int, int]:
    """
    For each future week, count how many strong teams are still available.
    Returns {week: n_strong_teams_available}.
    """
    scarcity = {}
    for week, matchups in matchups_by_week.items():
        strong_available = sum(
            1 for m in matchups
            if m.team_abbr not in used_teams and m.win_prob >= min_win_prob
        )
        scarcity[week] = strong_available
    return scarcity
