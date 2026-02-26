"""
Win probability model for NFL survivor pool.

Logistic regression trained on historical seasons (2015–2024).
Features: DVOA differential, EPA differential, SRS differential,
          home flag, rest advantage, recent form differential.

Calibrated with Platt scaling (CalibratedClassifierCV).
"""
import json
import logging
import pickle
from pathlib import Path
from typing import Optional
import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression
from sklearn.calibration import CalibratedClassifierCV
from sklearn.model_selection import cross_val_score
from sklearn.metrics import brier_score_loss, log_loss
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sqlalchemy.orm import Session
from app.db.models import Game, TeamWeekStats

logger = logging.getLogger(__name__)

MODEL_PATH = Path(__file__).resolve().parents[4] / "data" / "win_prob_model.pkl"
METRICS_PATH = Path(__file__).resolve().parents[4] / "data" / "model_metrics.json"

HOME_FIELD_PTS = 3.0   # points worth of home field advantage


def build_feature_matrix(db: Session, seasons: list[int]) -> tuple[np.ndarray, np.ndarray]:
    """
    Build feature matrix X and label vector y from historical games.

    Features per game (from home team's perspective):
      0. dvoa_diff          (home_total_dvoa - away_total_dvoa)
      1. off_dvoa_diff      (home_off_dvoa - away_off_dvoa)
      2. def_dvoa_diff      (away_def_dvoa - home_def_dvoa)  ← lower def DVOA is better
      3. epa_off_diff       (home_off_epa - away_off_epa)
      4. epa_def_diff       (away_def_epa - home_def_epa)
      5. srs_diff           (home_srs - away_srs)
      6. form_diff          (home_recent_form - away_recent_form)
      7. rest_advantage     (home_rest_days - away_rest_days)
      8. is_home            always 1.0 (captures baseline home field)
      9. is_neutral         1.0 if neutral site
    """
    X_rows = []
    y_rows = []

    games = (
        db.query(Game)
        .filter(Game.season.in_(seasons), Game.home_win.isnot(None))
        .all()
    )

    stats_cache: dict[tuple, dict] = {}

    def get_stats(team_id: int, season: int, week: int) -> dict:
        key = (team_id, season, week)
        if key not in stats_cache:
            # Use latest available stats up to this week
            row = (
                db.query(TeamWeekStats)
                .filter(
                    TeamWeekStats.team_id == team_id,
                    TeamWeekStats.season == season,
                    TeamWeekStats.week <= week,
                )
                .order_by(TeamWeekStats.week.desc())
                .first()
            )
            stats_cache[key] = {
                "total_dvoa": row.total_dvoa or 0.0 if row else 0.0,
                "offense_dvoa": row.offense_dvoa or 0.0 if row else 0.0,
                "defense_dvoa": row.defense_dvoa or 0.0 if row else 0.0,
                "off_epa": row.off_epa_per_play or 0.0 if row else 0.0,
                "def_epa": row.def_epa_per_play or 0.0 if row else 0.0,
                "srs": row.srs or 0.0 if row else 0.0,
                "recent_form": row.recent_form or 0.0 if row else 0.0,
                "rest_days": row.rest_days or 7 if row else 7,
            }
        return stats_cache[key]

    skipped = 0
    for game in games:
        hs = get_stats(game.home_team_id, game.season, game.week)
        aws = get_stats(game.away_team_id, game.season, game.week)

        # Build feature row
        features = [
            (hs["total_dvoa"] - aws["total_dvoa"]),
            (hs["offense_dvoa"] - aws["offense_dvoa"]),
            (aws["defense_dvoa"] - hs["defense_dvoa"]),   # inverted: lower def dvoa is better
            (hs["off_epa"] - aws["off_epa"]),
            (aws["def_epa"] - hs["def_epa"]),             # inverted
            (hs["srs"] - aws["srs"]),
            (hs["recent_form"] - aws["recent_form"]),
            float(hs["rest_days"] - aws["rest_days"]),
            0.0 if game.is_neutral else 1.0,              # is_home for home team
            1.0 if game.is_neutral else 0.0,
        ]

        # Skip if all stats are zero (missing data)
        if all(f == 0.0 for f in features[:6]):
            skipped += 1
            continue

        X_rows.append(features)
        y_rows.append(1 if game.home_win else 0)

    logger.info(
        "Built feature matrix: %d samples from %d games (%d skipped for missing data)",
        len(X_rows), len(games), skipped
    )

    return np.array(X_rows, dtype=np.float32), np.array(y_rows, dtype=np.int32)


def train_model(db: Session, train_seasons: list[int], val_season: Optional[int] = None) -> dict:
    """
    Train and calibrate win probability model.
    Returns metrics dict.
    """
    logger.info("Building training data for seasons: %s", train_seasons)
    X, y = build_feature_matrix(db, train_seasons)

    if len(X) < 100:
        raise ValueError(f"Insufficient training data: only {len(X)} samples")

    # Logistic regression in a pipeline with scaling
    base_model = Pipeline([
        ("scaler", StandardScaler()),
        ("lr", LogisticRegression(
            C=1.0,
            max_iter=1000,
            class_weight="balanced",
            solver="lbfgs",
            random_state=42,
        )),
    ])

    # Calibrate with Platt scaling (sigmoid) for well-calibrated probabilities
    calibrated = CalibratedClassifierCV(base_model, cv=5, method="sigmoid")
    calibrated.fit(X, y)

    # In-sample metrics
    y_prob = calibrated.predict_proba(X)[:, 1]
    train_brier = brier_score_loss(y, y_prob)
    train_logloss = log_loss(y, y_prob)

    metrics = {
        "train_seasons": train_seasons,
        "n_train_samples": len(X),
        "train_brier_score": round(train_brier, 4),
        "train_log_loss": round(train_logloss, 4),
        "home_win_rate": round(float(y.mean()), 4),
    }

    # Validation on held-out season
    if val_season is not None:
        logger.info("Validating on season %d", val_season)
        X_val, y_val = build_feature_matrix(db, [val_season])
        if len(X_val) > 0:
            y_val_prob = calibrated.predict_proba(X_val)[:, 1]
            val_brier = brier_score_loss(y_val, y_val_prob)
            val_logloss = log_loss(y_val, y_val_prob)
            val_acc = float((calibrated.predict(X_val) == y_val).mean())
            metrics.update({
                "val_season": val_season,
                "n_val_samples": len(X_val),
                "val_brier_score": round(val_brier, 4),
                "val_log_loss": round(val_logloss, 4),
                "val_accuracy": round(val_acc, 4),
            })
            logger.info(
                "Validation Brier: %.4f (target < 0.22), Accuracy: %.1f%%",
                val_brier, val_acc * 100
            )

    # Save model
    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(MODEL_PATH, "wb") as f:
        pickle.dump(calibrated, f)
    logger.info("Model saved to %s", MODEL_PATH)

    # Save metrics
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2)

    return metrics


def load_model() -> Optional[CalibratedClassifierCV]:
    """Load trained model from disk."""
    if not MODEL_PATH.exists():
        logger.warning("No model found at %s — run train_model() first", MODEL_PATH)
        return None
    with open(MODEL_PATH, "rb") as f:
        return pickle.load(f)


FEATURE_NAMES = [
    "dvoa_diff", "off_dvoa_diff", "def_dvoa_diff",
    "epa_off_diff", "epa_def_diff",
    "srs_diff", "form_diff", "rest_advantage",
    "is_home", "is_neutral",
]


class WinProbabilityModel:
    """
    Wrapper for predicting win probabilities for specific matchups.
    """

    def __init__(self):
        self._model = None

    def load(self) -> bool:
        self._model = load_model()
        return self._model is not None

    def predict(
        self,
        home_stats: dict,
        away_stats: dict,
        is_neutral: bool = False,
    ) -> tuple[float, float]:
        """
        Predict win probabilities for a matchup.
        Returns (home_win_prob, away_win_prob).
        """
        if self._model is None:
            if not self.load():
                # Fallback: SRS-based logistic
                return self._srs_fallback(home_stats, away_stats, is_neutral)

        features = np.array([[
            (home_stats.get("total_dvoa", 0) - away_stats.get("total_dvoa", 0)),
            (home_stats.get("offense_dvoa", 0) - away_stats.get("offense_dvoa", 0)),
            (away_stats.get("defense_dvoa", 0) - home_stats.get("defense_dvoa", 0)),
            (home_stats.get("off_epa_per_play", 0) - away_stats.get("off_epa_per_play", 0)),
            (away_stats.get("def_epa_per_play", 0) - home_stats.get("def_epa_per_play", 0)),
            (home_stats.get("srs", 0) - away_stats.get("srs", 0)),
            (home_stats.get("recent_form", 0) - away_stats.get("recent_form", 0)),
            float(home_stats.get("rest_days", 7) - away_stats.get("rest_days", 7)),
            0.0 if is_neutral else 1.0,
            1.0 if is_neutral else 0.0,
        ]], dtype=np.float32)

        probs = self._model.predict_proba(features)[0]
        home_prob = float(probs[1])
        away_prob = 1.0 - home_prob
        return home_prob, away_prob

    def _srs_fallback(
        self,
        home_stats: dict,
        away_stats: dict,
        is_neutral: bool,
    ) -> tuple[float, float]:
        """Simple SRS-based logistic fallback when model isn't trained yet."""
        home_srs = home_stats.get("srs", 0.0)
        away_srs = away_stats.get("srs", 0.0)
        hfa = 0.0 if is_neutral else HOME_FIELD_PTS
        # Convert point spread to probability via logistic function
        # σ(spread / 13.86) gives ~50% at 0, ~75% at +7
        spread = (home_srs - away_srs) + hfa
        home_prob = float(1.0 / (1.0 + np.exp(-spread / 13.86)))
        return home_prob, 1.0 - home_prob

    def predict_batch(self, matchups: list[dict]) -> list[tuple[float, float]]:
        """
        Batch predict. Each matchup dict: {home_stats, away_stats, is_neutral}.
        Returns list of (home_win_prob, away_win_prob).
        """
        return [
            self.predict(m["home_stats"], m["away_stats"], m.get("is_neutral", False))
            for m in matchups
        ]


def update_game_win_probs(db: Session, model: WinProbabilityModel, season: int) -> int:
    """
    Update win_prob fields on all unplayed games for a season.
    Returns number of games updated.
    """
    games = (
        db.query(Game)
        .filter(Game.season == season, Game.home_win.is_(None))
        .all()
    )

    updated = 0
    for game in games:
        def get_latest(team_id: int) -> dict:
            row = (
                db.query(TeamWeekStats)
                .filter(
                    TeamWeekStats.team_id == team_id,
                    TeamWeekStats.season == season,
                    TeamWeekStats.week < game.week,
                )
                .order_by(TeamWeekStats.week.desc())
                .first()
            )
            if not row:
                return {}
            return {
                "total_dvoa": row.total_dvoa or 0,
                "offense_dvoa": row.offense_dvoa or 0,
                "defense_dvoa": row.defense_dvoa or 0,
                "off_epa_per_play": row.off_epa_per_play or 0,
                "def_epa_per_play": row.def_epa_per_play or 0,
                "srs": row.srs or 0,
                "recent_form": row.recent_form or 0,
                "rest_days": row.rest_days or 7,
            }

        home_stats = get_latest(game.home_team_id)
        away_stats = get_latest(game.away_team_id)

        home_prob, away_prob = model.predict(home_stats, away_stats, game.is_neutral or False)
        game.home_win_prob = home_prob
        game.away_win_prob = away_prob
        updated += 1

    db.commit()
    logger.info("Updated win probabilities for %d games (season %d)", updated, season)
    return updated
