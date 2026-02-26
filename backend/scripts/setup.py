#!/usr/bin/env python3
"""
One-time setup script:
  1. Initialize the database
  2. Backfill historical data (2015–2024)
  3. Train win probability model
  4. Update win probabilities for current season

Usage: python scripts/setup.py [--seasons 2022 2023 2024] [--val-season 2023]
"""
import argparse
import logging
import sys
from pathlib import Path

# Add backend to path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db.session import init_db, SessionLocal
from app.data.loader import backfill_historical, seed_teams
from app.models.win_probability import train_model, update_game_win_probs, WinProbabilityModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s — %(message)s")
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="NFL Survivor Optimizer setup")
    parser.add_argument(
        "--seasons", nargs="+", type=int,
        default=list(range(2015, 2025)),
        help="Seasons to backfill (default: 2015-2024)"
    )
    parser.add_argument(
        "--val-season", type=int, default=2023,
        help="Hold-out season for model validation (default: 2023)"
    )
    parser.add_argument(
        "--skip-backfill", action="store_true",
        help="Skip data backfill (use if already done)"
    )
    parser.add_argument(
        "--skip-training", action="store_true",
        help="Skip model training"
    )
    args = parser.parse_args()

    logger.info("=== NFL Survivor Optimizer Setup ===")

    # 1. Initialize DB
    logger.info("Step 1: Initializing database")
    init_db()

    db = SessionLocal()
    try:
        # 2. Backfill historical data
        if not args.skip_backfill:
            logger.info("Step 2: Backfilling historical data for seasons %s", args.seasons)
            backfill_historical(db, seasons=args.seasons)
        else:
            logger.info("Step 2: Skipping backfill")
            seed_teams(db)

        # 3. Train model
        if not args.skip_training:
            train_seasons = [s for s in args.seasons if s != args.val_season]
            logger.info("Step 3: Training model on seasons %s, validating on %d",
                       train_seasons, args.val_season)
            metrics = train_model(db, train_seasons=train_seasons, val_season=args.val_season)
            logger.info("Model metrics: %s", metrics)
            val_brier = metrics.get("val_brier_score")
            if val_brier and val_brier < 0.22:
                logger.info("✓ Brier score %.4f meets target (< 0.22)", val_brier)
            elif val_brier:
                logger.warning("✗ Brier score %.4f exceeds target (< 0.22)", val_brier)
        else:
            logger.info("Step 3: Skipping model training")

        # 4. Update win probs for current season (2024/2025)
        logger.info("Step 4: Updating win probabilities for current season")
        model = WinProbabilityModel()
        if model.load():
            updated = update_game_win_probs(db, model, season=2024)
            logger.info("Updated win probs for %d games", updated)
        else:
            logger.warning("No model available — skipping win prob update")

    finally:
        db.close()

    logger.info("=== Setup complete! ===")
    logger.info("Start the API server: uvicorn app.main:app --reload")


if __name__ == "__main__":
    main()
